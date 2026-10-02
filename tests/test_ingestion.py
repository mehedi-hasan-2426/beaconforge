import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from beaconforge.api import create_app
from beaconforge.config import Settings
from beaconforge.database import Database, EventRow, Outbox
from beaconforge.services import create_project


def setup() -> tuple[Database, TestClient, dict[str, str]]:
    database = Database("sqlite://")
    database.initialize()
    credentials = create_project(database, "tests")
    return (
        database,
        TestClient(create_app(database, Settings(database_url="sqlite://"))),
        credentials,
    )


def event(external_id: str = "d1") -> dict[str, str]:
    return {
        "kind": "deployment",
        "external_id": external_id,
        "occurred_at": "2026-10-01T12:00:00+00:00",
    }


def headers(
    credentials: dict[str, str], body: bytes, delivery: str = "delivery1"
) -> dict[str, str]:
    return {
        "X-Project-Key": credentials["api_key"],
        "Idempotency-Key": delivery,
        "X-BeaconForge-Signature": "sha256="
        + hmac.new(credentials["signing_secret"].encode(), body, hashlib.sha256).hexdigest(),
        "Content-Type": "application/json",
    }


def test_acceptance_is_durable_and_duplicate_does_not_double_count() -> None:
    database, client, credentials = setup()
    body = json.dumps(event()).encode()
    first = client.post("/v1/events", content=body, headers=headers(credentials, body))
    second = client.post("/v1/events", content=body, headers=headers(credentials, body))
    assert first.status_code == second.status_code == 202
    assert second.json()["duplicate"] is True
    with database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(EventRow)) == 1
        assert session.scalar(select(func.count()).select_from(Outbox)) == 1


def test_conflicting_key_and_signature_failure() -> None:
    _, client, credentials = setup()
    body = json.dumps(event()).encode()
    client.post("/v1/events", content=body, headers=headers(credentials, body))
    changed = json.dumps(event("d2")).encode()
    assert (
        client.post(
            "/v1/events", content=changed, headers=headers(credentials, changed)
        ).status_code
        == 409
    )
    assert (
        client.post("/v1/events", content=changed, headers=headers(credentials, body)).status_code
        == 401
    )


def test_tenant_isolation_payload_limit_and_bad_cursor() -> None:
    database, client, credentials = setup()
    body = json.dumps(event()).encode()
    result = client.post("/v1/events", content=body, headers=headers(credentials, body)).json()
    other = create_project(database, "other")
    key = {"X-Project-Key": other["api_key"]}
    assert client.get("/v1/events", headers=key).json()["items"] == []
    assert client.post(f"/v1/events/{result['event_id']}/replay", headers=key).status_code == 404
    assert client.get("/v1/events?cursor=bad", headers=key).status_code == 422
    assert client.post("/v1/events", content=b"x" * 65537, headers=key).status_code == 413
