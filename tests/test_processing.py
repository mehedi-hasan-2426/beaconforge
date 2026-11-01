import json
from datetime import date

import pytest
from sqlalchemy import select

from beaconforge.database import Database, EventRow, Outbox, Project
from beaconforge.outbox import dispatch
from beaconforge.schemas import Coverage, Event
from beaconforge.services import (
    Problem,
    accept,
    authenticate,
    create_project,
    dead_letter,
    metrics,
    process,
    replay,
    set_coverage,
)


def setup() -> tuple[Database, Project]:
    database = Database("sqlite://")
    database.initialize()
    credentials = create_project(database, "worker-tests")
    return database, authenticate(database, credentials["api_key"])


def deployment(external_id: str = "d1") -> Event:
    return Event.model_validate(
        {
            "kind": "deployment",
            "external_id": external_id,
            "occurred_at": "2026-10-01T12:00:00Z",
            "commits": [{"sha": "a" * 40, "authored_at": "2026-10-01T10:00:00Z"}],
        }
    )


class OfflinePublisher:
    def publish(self, event_id: str, revision: int, purpose: str) -> None:
        raise ConnectionError("broker down")


class RecordingPublisher:
    def __init__(self) -> None:
        self.deliveries: list[tuple[str, int, str]] = []

    def publish(self, event_id: str, revision: int, purpose: str) -> None:
        self.deliveries.append((event_id, revision, purpose))


def test_broker_failure_keeps_acceptance_and_replay_creates_new_revision() -> None:
    database, project = setup()
    accepted = accept(database, project, "key1", deployment())
    for _ in range(3):
        with database.sessions.begin() as session:
            for row in session.scalars(select(Outbox)):
                row.next_attempt = 0
        dispatch(database, OfflinePublisher())
    with database.sessions() as session:
        row = session.get(EventRow, accepted["event_id"])
        assert row is not None and row.status == "dead_letter"
    result = replay(database, project, accepted["event_id"])
    assert result["status"] == "accepted"
    recorder = RecordingPublisher()
    dispatch(database, recorder)
    assert (accepted["event_id"], 1, "process") in recorder.deliveries
    process(database, accepted["event_id"], 0)
    with database.sessions() as session:
        row = session.get(EventRow, accepted["event_id"])
        assert row is not None and row.status == "accepted"


def test_repeated_processing_and_late_incident_rebuild_rollup() -> None:
    database, project = setup()
    accepted = accept(database, project, "key1", deployment())
    process(database, accepted["event_id"])
    process(database, accepted["event_id"])
    incident = Event(
        kind="incident",
        external_id="i1",
        occurred_at="2026-10-01T12:10:00Z",
        deployment_id="d1",
        restored_at="2026-10-01T12:20:00Z",
    )
    incident_id = accept(database, project, "key2", incident)["event_id"]
    process(database, incident_id)
    set_coverage(
        database,
        project,
        Coverage(
            deployment_start=date(2026, 10, 1),
            deployment_end=date(2026, 10, 2),
            incident_start=date(2026, 10, 1),
            incident_end=date(2026, 10, 2),
        ),
    )
    report = metrics(database, project, date(2026, 10, 1), date(2026, 10, 2))
    assert report["metrics"]["deployment_frequency"]["value"] == 1
    assert report["metrics"]["change_failure_rate"]["value"] == 1
    assert report["metrics"]["failed_deployment_recovery_time"]["value"] == 600


def test_incident_before_deployment_goes_to_replayable_dead_letter() -> None:
    database, project = setup()
    incident = Event.model_validate(
        {
            "kind": "incident",
            "external_id": "i1",
            "occurred_at": "2026-10-01T12:10:00Z",
            "deployment_id": "missing",
        }
    )
    event_id = accept(database, project, "key1", incident)["event_id"]
    with pytest.raises(ValueError, match="deployment_not_processed"):
        process(database, event_id)
    dead_letter(database, event_id, "processing_failed")
    assert replay(database, project, event_id)["status"] == "accepted"
    with pytest.raises(Problem):
        replay(database, project, event_id)


def test_empty_metrics_and_invalid_window() -> None:
    database, project = setup()
    report = metrics(database, project, date(2026, 10, 1), date(2026, 10, 2))
    assert all(value["value"] is None for value in report["metrics"].values())
    assert json.dumps(report)
    with pytest.raises(Problem):
        metrics(database, project, date(2026, 10, 2), date(2026, 10, 1))
