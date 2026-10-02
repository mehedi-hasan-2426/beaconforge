import argparse
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from beaconforge.collector import GitHub, collect_events, send_event
from beaconforge.config import Settings
from beaconforge.database import Database
from beaconforge.services import create_project


def write_credentials(path: Path, credentials: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(credentials, output)


def main() -> int:
    parser = argparse.ArgumentParser(prog="beaconforge")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    project = commands.add_parser("create-project")
    project.add_argument("--name", required=True)
    project.add_argument("--credentials", type=Path, required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--repository", required=True)
    collect.add_argument("--credentials", type=Path, required=True)
    collect.add_argument("--api-url", default="http://127.0.0.1:8081")
    collect.add_argument("--start", type=date.fromisoformat, required=True)
    collect.add_argument("--end", type=date.fromisoformat, required=True)
    commands.add_parser("sync-dead-letters")
    arguments = parser.parse_args()
    if arguments.command in ("init-db", "create-project"):
        settings = Settings()
        database = Database(settings.database_url.get_secret_value())
        if arguments.command == "init-db":
            database.initialize()
            print("Database schema initialized")
        else:
            if not 1 <= len(arguments.name.strip()) <= 100:
                parser.error("Project name must be 1 to 100 characters")
            if arguments.credentials.exists():
                parser.error("Credential file already exists; refusing overwrite")
            credentials = create_project(database, arguments.name.strip())
            write_credentials(arguments.credentials, credentials)
            print(f"Project created; credentials stored in {arguments.credentials}")
        database.engine.dispose()
    elif arguments.command == "collect":
        target = urlsplit(arguments.api_url)
        if target.scheme != "http" or target.hostname not in ("127.0.0.1", "localhost", "::1"):
            parser.error("Local collector submits only to a loopback HTTP API")
        credentials = json.loads(arguments.credentials.read_text(encoding="utf-8"))
        github = GitHub(os.environ.get("GH_TOKEN"))
        try:
            events = collect_events(github, arguments.repository, arguments.start, arguments.end)
            with httpx.Client(base_url=arguments.api_url, timeout=10) as client:
                for event in events:
                    send_event(client, credentials, event, event["external_id"])
                response = client.put(
                    "/v1/coverage",
                    headers={"X-Project-Key": credentials["api_key"]},
                    json={
                        "deployment_start": arguments.start.isoformat(),
                        "deployment_end": arguments.end.isoformat(),
                    },
                )
                response.raise_for_status()
            print(
                f"Collected {len(events)} production deployments; incident coverage remains unknown"
            )
        finally:
            github.client.close()
    else:
        from beaconforge.worker import synchronize_dead_letters

        print(f"Synchronized {synchronize_dead_letters()} broker dead letters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
