from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from statistics import median
from typing import TypedDict


@dataclass(frozen=True)
class Change:
    sha: str
    authored_at: datetime


@dataclass(frozen=True)
class Observation:
    kind: str
    external_id: str
    occurred_at: datetime
    environment: str = "production"
    outcome: str = "success"
    commits: tuple[Change, ...] = ()
    deployment_id: str | None = None
    restored_at: datetime | None = None
    commit_scope: str = "unknown"
    incident_id: str | None = None


@dataclass
class Day:
    deployments: int = 0
    successes: int = 0
    failed_deployments: int = 0
    incidents: int = 0
    unresolved: int = 0
    lead_seconds: list[float] = field(default_factory=list)
    recovery_seconds: list[float] = field(default_factory=list)
    complete_change_sets: int = 0


class Metric(TypedDict):
    value: float | None
    observed: float | None
    samples: int
    unit: str


def project_days(observations: list[Observation]) -> dict[date, Day]:
    deployments = {
        item.external_id: item
        for item in observations
        if item.kind == "deployment" and item.environment == "production"
    }
    days: defaultdict[date, Day] = defaultdict(Day)
    seen_commits: set[str] = set()
    for deployment in sorted(deployments.values(), key=lambda item: item.occurred_at):
        day = days[deployment.occurred_at.astimezone(UTC).date()]
        day.deployments += 1
        if deployment.outcome != "success":
            continue
        day.successes += 1
        if deployment.commit_scope == "complete" and deployment.commits:
            day.complete_change_sets += 1
        for commit in deployment.commits:
            if commit.sha not in seen_commits:
                day.lead_seconds.append(
                    (deployment.occurred_at - commit.authored_at).total_seconds()
                )
                seen_commits.add(commit.sha)
    restorations: dict[str, datetime] = {}
    for restoration in (item for item in observations if item.kind == "restoration"):
        incident_id = restoration.incident_id or ""
        existing = restorations.get(incident_id)
        if existing is None or restoration.occurred_at < existing:
            restorations[incident_id] = restoration.occurred_at
    failed: set[str] = set()
    for incident in (item for item in observations if item.kind == "incident"):
        causing_deployment = deployments.get(incident.deployment_id or "")
        if causing_deployment is None:
            continue
        if incident.occurred_at < causing_deployment.occurred_at:
            raise ValueError("incident cannot precede causing deployment")
        day = days[causing_deployment.occurred_at.astimezone(UTC).date()]
        day.incidents += 1
        failed.add(causing_deployment.external_id)
        restored_at = incident.restored_at or restorations.get(incident.external_id)
        if restored_at is None:
            day.unresolved += 1
        else:
            if restored_at < incident.occurred_at:
                raise ValueError("restoration cannot precede incident")
            day.recovery_seconds.append((restored_at - incident.occurred_at).total_seconds())
    for deployment_id in failed:
        deployment = deployments[deployment_id]
        days[deployment.occurred_at.astimezone(UTC).date()].failed_deployments += 1
    return dict(days)


def summarize(
    days: list[Day], window_days: int, deployments_complete: bool, incidents_complete: bool
) -> dict[str, Metric]:
    deployments = sum(day.deployments for day in days)
    successes = sum(day.successes for day in days)
    leads = [value for day in days for value in day.lead_seconds]
    recoveries = [value for day in days for value in day.recovery_seconds]
    unresolved = sum(day.unresolved for day in days)
    failed = sum(day.failed_deployments for day in days)

    def metric(value: float | None, known: bool, samples: int, unit: str) -> Metric:
        return {
            "value": value if known else None,
            "observed": value,
            "samples": samples,
            "unit": unit,
        }

    return {
        "deployment_frequency": metric(
            successes / window_days, deployments_complete, successes, "per_day"
        ),
        "lead_time": metric(
            float(median(leads)) if leads else None,
            deployments_complete and sum(day.complete_change_sets for day in days) == successes,
            len(leads),
            "seconds",
        ),
        "change_failure_rate": metric(
            failed / deployments if deployments else None,
            deployments_complete and incidents_complete,
            deployments,
            "ratio",
        ),
        "failed_deployment_recovery_time": metric(
            float(median(recoveries)) if recoveries else None,
            incidents_complete and deployments_complete and unresolved == 0,
            len(recoveries),
            "seconds",
        ),
    }
