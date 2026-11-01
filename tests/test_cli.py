import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from beaconforge import cli


def run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["beaconforge", *args])
    return cli.main()


@pytest.fixture
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"
    monkeypatch.setenv("BEACONFORGE_DATABASE_URL", url)
    return url


def test_init_db_and_create_project_write_credentials(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run(monkeypatch, "init-db") == 0
    target = tmp_path / "keys" / "project.json"
    assert run(monkeypatch, "create-project", "--name", " demo ", "--credentials", str(target)) == 0
    credentials = json.loads(target.read_text(encoding="utf-8"))
    assert "api_key" in credentials
    output = capsys.readouterr().out
    assert "Database schema initialized" in output
    assert "Project created" in output


def test_create_project_refuses_existing_file(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, "init-db")
    target = tmp_path / "existing.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        run(monkeypatch, "create-project", "--name", "demo", "--credentials", str(target))
    assert target.read_text(encoding="utf-8") == "{}"


def test_create_project_rejects_blank_name(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run(monkeypatch, "init-db")
    with pytest.raises(SystemExit):
        run(
            monkeypatch,
            "create-project",
            "--name",
            "   ",
            "--credentials",
            str(tmp_path / "x.json"),
        )


def test_collect_refuses_non_loopback_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        run(
            monkeypatch,
            "collect",
            "--repository",
            "owner/repo",
            "--credentials",
            str(tmp_path / "c.json"),
            "--api-url",
            "https://example.com",
            "--start",
            "2026-10-01",
            "--end",
            "2026-10-02",
        )


class FakeGitHub:
    def __init__(self, token: str | None) -> None:
        self.closed = False
        self.client = self

    def close(self) -> None:
        self.closed = True


def test_collect_sends_events_and_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    credentials = tmp_path / "c.json"
    credentials.write_text(json.dumps({"api_key": "key", "signing_secret": "s"}), encoding="utf-8")
    sent: list[str] = []
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    real_client = httpx.Client

    def client_factory(**kwargs: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cli, "GitHub", FakeGitHub)
    monkeypatch.setattr(
        cli, "collect_events", lambda *args: [{"external_id": "d1"}, {"external_id": "d2"}]
    )
    monkeypatch.setattr(cli, "send_event", lambda client, creds, event, key: sent.append(key))
    monkeypatch.setattr(cli.httpx, "Client", client_factory)
    result = run(
        monkeypatch,
        "collect",
        "--repository",
        "owner/repo",
        "--credentials",
        str(credentials),
        "--start",
        "2026-10-01",
        "--end",
        "2026-10-02",
    )
    assert result == 0
    assert sent == ["d1", "d2"]
    assert requests[-1].url.path == "/v1/coverage"
    assert requests[-1].headers["X-Project-Key"] == "key"
    assert json.loads(requests[-1].content) == {
        "deployment_start": "2026-10-01",
        "deployment_end": "2026-10-02",
    }
    assert "Collected 2 production deployments" in capsys.readouterr().out


def test_sync_dead_letters_reports_count(
    database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from beaconforge import worker

    monkeypatch.setattr(worker, "synchronize_dead_letters", lambda: 3)
    assert run(monkeypatch, "sync-dead-letters") == 0
    assert "Synchronized 3 broker dead letters" in capsys.readouterr().out
