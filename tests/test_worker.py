from types import SimpleNamespace
from typing import Any

import pytest
from celery.exceptions import Reject

worker: Any = None


@pytest.fixture(autouse=True)
def worker_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    global worker
    monkeypatch.setenv("BEACONFORGE_DATABASE_URL", "sqlite://")
    from beaconforge import worker as module

    worker = module
    monkeypatch.setattr(
        module,
        "Database",
        lambda url: SimpleNamespace(engine=SimpleNamespace(dispose=lambda: None)),
    )
    return module


def test_publisher_routes_process_and_dead_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, list[Any], dict[str, Any]]] = []
    monkeypatch.setattr(
        worker.celery, "send_task", lambda name, args, **kw: calls.append((name, args, kw))
    )
    publisher = worker.CeleryPublisher()
    publisher.publish("e1", 1, "process")
    publisher.publish("e2", 2, "dead")
    assert calls[0] == (
        "beaconforge.process",
        ["e1", 1],
        {"queue": "beaconforge.events", "retry": False},
    )
    assert calls[1][0] == "beaconforge.dead_letter"
    assert calls[1][2]["queue"] == "beaconforge.dead"
    assert calls[1][2]["routing_key"] == "dead"


def test_process_event_success(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(
        worker, "process", lambda db, event_id, revision: seen.append((event_id, revision))
    )
    worker.process_event.run("e1", 1)
    assert seen == [("e1", 1)]


def failing(*args: Any) -> None:
    raise RuntimeError("boom")


class RetryCalled(Exception):
    pass


def test_process_event_retries_before_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "process", failing)

    def retry(**kwargs: Any) -> Exception:
        assert kwargs["countdown"] == 1
        return RetryCalled()

    monkeypatch.setattr(worker.process_event, "retry", retry)
    with pytest.raises(RetryCalled):
        worker.process_event.run("e1", 1)


def test_process_event_dead_letters_after_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "process", failing)
    dead: list[tuple[str, str, int]] = []
    monkeypatch.setattr(
        worker,
        "dead_letter",
        lambda db, event_id, reason, revision: dead.append((event_id, reason, revision)),
    )
    worker.process_event.push_request(retries=5)
    try:
        worker.process_event.run("e1", 2)
    finally:
        worker.process_event.pop_request()
    assert dead == [("e1", "processing_failed", 2)]


def test_process_event_rejects_when_dead_letter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "process", failing)
    monkeypatch.setattr(worker, "dead_letter", failing)
    worker.process_event.push_request(retries=5)
    try:
        with pytest.raises(Reject):
            worker.process_event.run("e1", 2)
    finally:
        worker.process_event.pop_request()


class StopLoop(Exception):
    pass


def test_run_outbox_logs_and_keeps_going(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(worker, "dispatch", failing)

    def stop(seconds: float) -> None:
        raise StopLoop

    monkeypatch.setattr(worker.time, "sleep", stop)
    with pytest.raises(StopLoop):
        worker.run_outbox()
    assert "Outbox batch unavailable" in caplog.text


def put_dead(event_id: str, revision: int) -> None:
    with worker.celery.connection_for_write() as connection:
        queue = connection.SimpleQueue(
            "beaconforge.dead", queue_opts={"durable": True}, exchange_opts={"durable": True}
        )
        queue.put([[event_id, revision], {}, {}])
        queue.close()


def test_synchronize_dead_letters_records_and_acks(monkeypatch: pytest.MonkeyPatch) -> None:
    dead: list[tuple[str, int]] = []
    monkeypatch.setattr(
        worker,
        "dead_letter",
        lambda db, event_id, reason, revision: dead.append((event_id, revision)),
    )
    put_dead("e1", 1)
    put_dead("e2", 2)
    assert worker.synchronize_dead_letters() == 2
    assert dead == [("e1", 1), ("e2", 2)]
    assert worker.synchronize_dead_letters() == 0


def test_synchronize_dead_letters_requeues_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "dead_letter", failing)
    put_dead("e3", 3)
    with pytest.raises(RuntimeError):
        worker.synchronize_dead_letters()
    recorded: list[str] = []
    monkeypatch.setattr(
        worker, "dead_letter", lambda db, event_id, reason, revision: recorded.append(event_id)
    )
    assert worker.synchronize_dead_letters() == 1
    assert recorded == ["e3"]
