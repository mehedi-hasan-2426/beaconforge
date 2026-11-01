from datetime import date

import httpx
import pytest

from beaconforge.collector import CollectionError, GitHub, collect_events


def test_real_metadata_mapping_never_invents_incidents_or_complete_changes() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if "/statuses" in request.url.path:
            return httpx.Response(
                200,
                json=[
                    {"state": "inactive"},
                    {"state": "success", "created_at": "2026-10-01T12:00:00Z"},
                ],
            )
        if "/commits/" in request.url.path:
            return httpx.Response(
                200, json={"sha": "a" * 40, "commit": {"author": {"date": "2026-10-01T10:00:00Z"}}}
            )
        return httpx.Response(
            200,
            json=[
                {"id": 1, "environment": "Production", "sha": "a" * 40},
                {"id": 2, "environment": "preview", "sha": "b" * 40},
            ],
        )

    github = GitHub(
        client=httpx.Client(
            transport=httpx.MockTransport(respond), base_url="https://api.github.com"
        )
    )
    events = collect_events(github, "owner/repo", date(2026, 10, 1), date(2026, 10, 2))
    assert len(events) == 1
    assert events[0]["commit_scope"] == "head_only"
    assert events[0]["external_id"] == "github:owner/repo:1"


def test_collection_failure_does_not_declare_coverage() -> None:
    github = GitHub(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(403)),
            base_url="https://api.github.com",
        )
    )
    with pytest.raises(CollectionError):
        collect_events(github, "owner/repo", date(2026, 10, 1), date(2026, 10, 2))
    with pytest.raises(CollectionError):
        collect_events(github, "../invalid", date(2026, 10, 1), date(2026, 10, 2))
