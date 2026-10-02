import time
from typing import Protocol

from sqlalchemy import select

from beaconforge.database import Database, EventRow, Outbox


class Publisher(Protocol):
    def publish(self, event_id: str, revision: int, purpose: str) -> None: ...


def dispatch(database: Database, publisher: Publisher, limit: int = 25, retries: int = 3) -> int:
    published = 0
    with database.sessions.begin() as session:
        rows = session.scalars(
            select(Outbox)
            .where(
                Outbox.published_at.is_(None),
                Outbox.next_attempt <= time.time(),
                Outbox.attempts < retries,
            )
            .order_by(Outbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for row in rows:
            try:
                publisher.publish(row.event_id, row.revision, row.purpose)
            except Exception:
                row.attempts += 1
                row.next_attempt = time.time() + min(2**row.attempts, 30)
                if row.attempts >= retries and row.purpose == "process":
                    event = session.get(EventRow, row.event_id)
                    if event and event.status == "accepted" and event.replay_count == row.revision:
                        event.status, event.failure_code = "dead_letter", "broker_unavailable"
                        session.add(
                            Outbox(event_id=event.id, revision=event.replay_count, purpose="dead")
                        )
            else:
                row.published_at = time.time()
                published += 1
    return published
