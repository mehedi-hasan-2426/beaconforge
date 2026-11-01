import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError

from beaconforge.database import Database, Delivery, EventRow, Outbox, Project, Rollup
from beaconforge.domain import Change, Day, Observation, project_days, summarize
from beaconforge.schemas import Coverage, Event


class Problem(Exception):
    def __init__(self, status: int, title: str, detail: str) -> None:
        self.status, self.title, self.detail = status, title, detail


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_project(database: Database, name: str) -> dict[str, str]:
    key = "bf_" + secrets.token_urlsafe(32)
    secret = secrets.token_hex(32)
    with database.sessions.begin() as session:
        project = Project(name=name, key_digest=digest(key), signing_secret=secret)
        session.add(project)
        session.flush()
        project_id = project.id
    return {"project_id": project_id, "api_key": key, "signing_secret": secret}


def authenticate(database: Database, key: str | None) -> Project:
    if not key or len(key) > 256:
        raise Problem(401, "Unauthorized", "A valid project API key is required")
    with database.sessions() as session:
        project = session.scalar(select(Project).where(Project.key_digest == digest(key)))
        if project is None:
            raise Problem(401, "Unauthorized", "A valid project API key is required")
        return project


def verify_signature(secret: str, body: bytes, signature: str | None) -> None:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if signature is None or not signature.isascii() or not hmac.compare_digest(expected, signature):
        raise Problem(401, "Unauthorized", "Request signature is invalid")


def receipt(row: EventRow, duplicate: bool) -> dict[str, Any]:
    return {"event_id": row.id, "status": row.status, "duplicate": duplicate}


def accept(database: Database, project: Project, delivery_id: str, event: Event) -> dict[str, Any]:
    payload = event.model_dump(mode="json")
    payload_digest = digest(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    try:
        with database.sessions.begin() as session:
            delivery = session.get(Delivery, (project.id, delivery_id))
            row = session.scalar(
                select(EventRow).where(
                    EventRow.project_id == project.id, EventRow.external_id == event.external_id
                )
            )
            if delivery is not None and delivery.payload_digest != payload_digest:
                raise Problem(
                    409, "Conflict", "Idempotency key was already used for different content"
                )
            if row is not None and row.payload_digest != payload_digest:
                raise Problem(
                    409, "Conflict", "External event ID was already used for different content"
                )
            duplicate = row is not None
            if row is None:
                row = EventRow(
                    project_id=project.id,
                    external_id=event.external_id,
                    delivery_id=delivery_id,
                    payload_digest=payload_digest,
                    payload=payload,
                )
                session.add(row)
                session.flush()
                session.add(Outbox(event_id=row.id))
            if delivery is None:
                session.add(
                    Delivery(
                        project_id=project.id,
                        key=delivery_id,
                        event_id=row.id,
                        payload_digest=payload_digest,
                    )
                )
            return receipt(row, duplicate)
    except IntegrityError:
        with database.sessions() as session:
            delivery = session.get(Delivery, (project.id, delivery_id))
            row = session.scalar(
                select(EventRow).where(
                    EventRow.project_id == project.id, EventRow.external_id == event.external_id
                )
            )
            if (
                row is None
                or row.payload_digest != payload_digest
                or (delivery and delivery.payload_digest != payload_digest)
            ):
                raise Problem(
                    409, "Conflict", "Concurrent delivery conflicts with accepted content"
                ) from None
            return receipt(row, True)


def observation(payload: dict[str, Any]) -> Observation:
    event = Event.model_validate(payload)
    return Observation(
        event.kind,
        event.external_id,
        event.occurred_at,
        event.environment,
        event.outcome,
        tuple(Change(change.sha, change.authored_at) for change in event.commits),
        event.deployment_id,
        event.restored_at,
        event.commit_scope,
        event.incident_id,
    )


def process(database: Database, event_id: str, revision: int | None = None) -> None:
    with database.sessions.begin() as session:
        row = session.get(EventRow, event_id)
        if row is None or row.status in ("processed", "ignored", "dead_letter"):
            return
        if revision is not None and revision != row.replay_count:
            return
        project = session.scalar(
            select(Project).where(Project.id == row.project_id).with_for_update()
        )
        if project is None:
            raise ValueError("project_missing")
        event = Event.model_validate(row.payload)
        if event.kind == "incident":
            parent = session.scalar(
                select(EventRow).where(
                    EventRow.project_id == project.id,
                    EventRow.external_id == event.deployment_id,
                    EventRow.status == "processed",
                )
            )
            if parent is None:
                raise ValueError("deployment_not_processed")
        if event.kind == "restoration":
            parent = session.scalar(
                select(EventRow).where(
                    EventRow.project_id == project.id,
                    EventRow.external_id == event.incident_id,
                    EventRow.status == "processed",
                )
            )
            if parent is None or parent.payload["kind"] != "incident":
                raise ValueError("incident_not_processed")
        row.status = "processed" if event.environment == "production" else "ignored"
        row.processed_at = time.time()
        session.flush()
        rows = session.scalars(
            select(EventRow).where(
                EventRow.project_id == project.id, EventRow.status == "processed"
            )
        ).all()
        days = project_days([observation(item.payload) for item in rows])
        session.execute(delete(Rollup).where(Rollup.project_id == project.id))
        for day, values in days.items():
            session.add(Rollup(project_id=project.id, day=day, values=asdict(values)))


def dead_letter(
    database: Database, event_id: str, reason: str, revision: int | None = None
) -> None:
    with database.sessions.begin() as session:
        row = session.get(EventRow, event_id)
        if row is None or row.status in ("processed", "ignored", "dead_letter"):
            return
        if revision is not None and revision != row.replay_count:
            return
        row.status, row.failure_code = "dead_letter", reason
        session.add(Outbox(event_id=row.id, revision=row.replay_count, purpose="dead"))


def replay(database: Database, project: Project, event_id: str) -> dict[str, Any]:
    with database.sessions.begin() as session:
        row = session.scalar(
            select(EventRow)
            .where(EventRow.id == event_id, EventRow.project_id == project.id)
            .with_for_update()
        )
        if row is None:
            raise Problem(404, "Not found", "Event not found")
        if row.status != "dead_letter":
            raise Problem(409, "Conflict", "Only dead-letter events can be replayed")
        row.status, row.failure_code = "accepted", None
        row.replay_count += 1
        session.add(Outbox(event_id=row.id, revision=row.replay_count))
        return receipt(row, False)


def set_coverage(database: Database, project: Project, coverage: Coverage) -> None:
    with database.sessions.begin() as session:
        row = session.get(Project, project.id)
        if row is None:
            raise Problem(404, "Not found", "Project not found")
        for name, value in coverage.model_dump().items():
            setattr(row, name, value)


def list_events(
    database: Database, project: Project, limit: int, cursor: str | None
) -> dict[str, Any]:
    query = select(EventRow).where(EventRow.project_id == project.id)
    if cursor:
        try:
            value = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            timestamp, row_id = float(value[0]), str(value[1])
            if len(row_id) != 36:
                raise ValueError("invalid cursor")
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            raise Problem(422, "Invalid cursor", "Cursor is malformed") from None
        query = query.where(
            or_(
                EventRow.received_at > timestamp,
                and_(EventRow.received_at == timestamp, EventRow.id > row_id),
            )
        )
    with database.sessions() as session:
        rows = session.scalars(
            query.order_by(EventRow.received_at, EventRow.id).limit(limit + 1)
        ).all()
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit and page:
            last = page[-1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps([last.received_at, last.id]).encode()
            ).decode()
        return {
            "items": [
                {
                    "event_id": row.id,
                    "kind": row.payload["kind"],
                    "status": row.status,
                    "received_at": datetime.fromtimestamp(row.received_at, UTC).isoformat(),
                    "failure_code": row.failure_code,
                    "replay_count": row.replay_count,
                }
                for row in page
            ],
            "next_cursor": next_cursor,
        }


def metrics(database: Database, project: Project, start: date, end: date) -> dict[str, Any]:
    span = (end - start).days
    if not 1 <= span <= 90:
        raise Problem(422, "Invalid window", "Reporting window must contain 1 to 90 UTC days")
    with database.sessions() as session:
        current = session.get(Project, project.id)
        if current is None:
            raise Problem(404, "Not found", "Project not found")
        rows = session.scalars(
            select(Rollup).where(
                Rollup.project_id == project.id, Rollup.day >= start, Rollup.day < end
            )
        ).all()
        days = [Day(**row.values) for row in rows]
        deployments_complete = bool(
            current.deployment_start
            and current.deployment_end
            and current.deployment_start <= start
            and current.deployment_end >= end
        )
        incidents_complete = bool(
            current.incident_start
            and current.incident_end
            and current.incident_start <= start
            and current.incident_end >= end
        )
        pending = (
            session.scalar(
                select(func.count())
                .select_from(EventRow)
                .where(EventRow.project_id == project.id, EventRow.status == "accepted")
            )
            or 0
        )
        dead = (
            session.scalar(
                select(func.count())
                .select_from(EventRow)
                .where(EventRow.project_id == project.id, EventRow.status == "dead_letter")
            )
            or 0
        )
        if pending or dead:
            deployments_complete = False
            incidents_complete = False
        return {
            "project_id": project.id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "metrics": summarize(days, span, deployments_complete, incidents_complete),
            "coverage": {
                "deployments_complete": deployments_complete,
                "incidents_complete": incidents_complete,
                "pending_events": pending,
                "dead_letter_events": dead,
                "commit_samples": sum(len(day.lead_seconds) for day in days),
                "successful_deployments": sum(day.successes for day in days),
                "resolved_incidents": sum(len(day.recovery_seconds) for day in days),
                "unresolved_incidents": sum(day.unresolved for day in days),
            },
        }
