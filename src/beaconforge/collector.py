import hashlib
import hmac
import json
import re
from datetime import UTC, date, datetime
from typing import Any

import httpx


class CollectionError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token: str | None = None, client: httpx.Client | None = None) -> None:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = client or httpx.Client(
            base_url="https://api.github.com", headers=headers, timeout=20, follow_redirects=False
        )

    def get(self, path: str) -> Any:
        response = self.client.get(path)
        if response.status_code != 200:
            raise CollectionError(
                f"GitHub metadata request failed with HTTP {response.status_code}"
            )
        return response.json()

    def pages(self, path: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for page in range(1, 101):
            batch = self.get(f"{path}?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise CollectionError("Unexpected GitHub pagination response")
            records.extend(batch)
            if len(batch) < 100:
                return records
        raise CollectionError("Pagination bound reached; coverage cannot be declared complete")


def collect_events(github: GitHub, repository: str, start: date, end: date) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository):
        raise CollectionError("Repository must be owner/name")
    if not 1 <= (end - start).days <= 90:
        raise CollectionError("Collection window must contain 1 to 90 UTC days")
    deployments = github.pages(f"/repos/{repository}/deployments")
    events: list[dict[str, Any]] = []
    for deployment in deployments:
        if not deployment.get("production_environment") and str(
            deployment.get("environment", "")
        ).lower() not in ("production", "prod"):
            continue
        statuses = github.pages(f"/repos/{repository}/deployments/{int(deployment['id'])}/statuses")
        terminal = next(
            (
                status
                for status in statuses
                if status.get("state") in ("success", "failure", "error")
            ),
            None,
        )
        if terminal is None:
            continue
        occurred = datetime.fromisoformat(terminal["created_at"].replace("Z", "+00:00"))
        if not start <= occurred.astimezone(UTC).date() < end:
            continue
        metadata = github.get(f"/repos/{repository}/commits/{deployment['sha']}")
        authored = metadata.get("commit", {}).get("author", {}).get("date")
        sha = metadata.get("sha")
        commits = []
        if authored and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha):
            commits = [{"sha": sha, "authored_at": authored}]
        events.append(
            {
                "kind": "deployment",
                "external_id": f"github:{repository}:{deployment['id']}",
                "occurred_at": occurred.isoformat(),
                "environment": "production",
                "outcome": "success" if terminal["state"] == "success" else "failure",
                "commits": commits,
                "commit_scope": "head_only",
            }
        )
    return events


def send_event(
    client: httpx.Client, credentials: dict[str, str], event: dict[str, Any], delivery_id: str
) -> dict[str, Any]:
    body = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    signature = (
        "sha256="
        + hmac.new(credentials["signing_secret"].encode(), body, hashlib.sha256).hexdigest()
    )
    response = client.post(
        "/v1/events",
        content=body,
        headers={
            "X-Project-Key": credentials["api_key"],
            "X-BeaconForge-Signature": signature,
            "Idempotency-Key": delivery_id,
            "Content-Type": "application/json",
        },
    )
    if response.status_code != 202:
        raise CollectionError(f"Ingestion rejected event with HTTP {response.status_code}")
    return dict(response.json())
