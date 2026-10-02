# Metric definitions

Reports use whole UTC days: `start` is inclusive, `end` is exclusive. Both are
dates, the range must contain 1 to 90 days, and only production deployments count.
Builds, tests, previews, staging releases, and cancelled deployments do not count.

Deployment events describe completed production deployment attempts. Successful
attempts count toward deployment frequency. Both successful and failed attempts
form the change-failure denominator; a failed attempt is not automatically an
incident. A confirmed incident explicitly references its causing deployment.

| Metric | Definition | Missing-data behaviour |
|---|---|---|
| Deployment frequency | Successful production deployments divided by days in the window | Observed rate plus deployment coverage; unknown if collection is incomplete |
| Lead time | Median seconds from an included commit's authored timestamp to its first successful production deployment | Unknown without commit timestamps; report observed sample count and deployment coverage |
| Change failure rate | Distinct completed production deployments linked to a confirmed service incident divided by completed production deployments | Unknown unless incident coverage is explicitly declared complete for the window; unknown with no deployments |
| Failed-deployment recovery time | Median seconds from deployment-caused incident start to confirmed restoration | Unknown unless incident coverage is complete and every incident in scope has a valid restoration; report resolved and unresolved counts |

Incidents are attributed to the UTC day of their causing deployment, even if the
incident or restoration arrives later. Two incidents affecting the same deployment
count once in the failure-rate numerator but remain two recovery observations.
Recovery timestamps must not precede incident start. Commit timestamps must not
follow deployment completion. A commit repeated across deployments contributes
only to its first observed successful deployment.

Project coverage is an explicit interval, not a conclusion inferred from silence.
A collector may declare deployment coverage only after reading every page in its
requested scope successfully. GitHub deployment records do not prove incident
coverage, so the GitHub collector never declares incident completeness.

Rollups are replaceable projections of accepted events. Late events cause the
project's affected projection to be rebuilt. API reads aggregate those stored
daily projections, not the complete event log. Reports include processed-event
counts and pending-event counts so asynchronous lag is visible.