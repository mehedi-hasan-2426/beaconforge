from datetime import UTC, date, datetime, timedelta

import pytest

from beaconforge.domain import Change, Observation, project_days, summarize
from beaconforge.schemas import Event

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


def test_unknown_incidents_never_become_zero() -> None:
    deployment = Observation("deployment", "d1", NOW)
    result = summarize(list(project_days([deployment]).values()), 1, True, False)
    assert result["deployment_frequency"]["value"] == 1
    assert result["change_failure_rate"]["value"] is None
    assert result["failed_deployment_recovery_time"]["value"] is None


def test_first_deployment_of_commit_and_late_incident() -> None:
    change = Change("a" * 40, NOW - timedelta(hours=2))
    deployment = Observation("deployment", "d1", NOW, commits=(change,))
    second = Observation("deployment", "d2", NOW + timedelta(hours=1), commits=(change,))
    incident = Observation(
        "incident",
        "i1",
        NOW + timedelta(days=1),
        deployment_id="d1",
        restored_at=NOW + timedelta(days=1, minutes=10),
    )
    day = project_days([second, incident, deployment])[date(2026, 10, 1)]
    assert day.lead_seconds == [7200]
    result = summarize([day], 1, True, True)
    assert result["change_failure_rate"]["value"] == 0.5
    assert result["failed_deployment_recovery_time"]["value"] == 600


def test_unknown_collection_and_unresolved_incident() -> None:
    deployment = Observation("deployment", "d1", NOW)
    incident = Observation("incident", "i1", NOW, deployment_id="d1")
    result = summarize(list(project_days([deployment, incident]).values()), 1, False, False)
    assert all(item["value"] is None for item in result.values())


def test_preview_and_failed_attempt_do_not_count_as_success() -> None:
    events = [
        Observation("deployment", "d1", NOW, environment="preview"),
        Observation("deployment", "d2", NOW, outcome="failure"),
    ]
    day = project_days(events)[NOW.date()]
    assert day.deployments == 1
    assert day.successes == 0
    assert day.failed_deployments == 0


def test_incident_schema_requires_attribution() -> None:
    with pytest.raises(ValueError):
        Event(kind="incident", external_id="i1", occurred_at=NOW)


def test_schema_rejects_naive_timestamps_and_unknown_fields() -> None:
    with pytest.raises(ValueError):
        Event.model_validate(
            {"kind": "deployment", "external_id": "d1", "occurred_at": "2026-10-01T12:00:00"}
        )
    with pytest.raises(ValueError):
        Event.model_validate(
            {
                "kind": "deployment",
                "external_id": "d1",
                "occurred_at": NOW.isoformat(),
                "secret": "not accepted",
            }
        )


def test_late_restoration_resolves_an_immutable_incident() -> None:
    deployment = Observation("deployment", "d1", NOW)
    incident = Observation("incident", "i1", NOW + timedelta(minutes=5), deployment_id="d1")
    restoration = Observation("restoration", "r1", NOW + timedelta(minutes=15), incident_id="i1")
    day = project_days([deployment, incident, restoration])[NOW.date()]
    assert day.unresolved == 0
    assert day.recovery_seconds == [600]
