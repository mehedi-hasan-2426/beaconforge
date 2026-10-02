# Design decisions

## PostgreSQL is the acceptance boundary

Accepted events and outbox records commit in one transaction. The API returns
202 only after that commit. A broker outage therefore does not discard accepted
events. A database outage rejects acceptance with a problem response. A publish
followed by a publisher crash can deliver twice; database constraints and worker
state make repeated processing harmless.

## RabbitMQ and Celery separate acceptance from work

Celery supplies maintained task delivery and retry machinery. RabbitMQ messages
are durable, publisher confirms are enabled, and workers acknowledge after task
processing. Failed processing receives bounded retries. Exhausted events are
recorded as dead letters in PostgreSQL and mirrored to a separate broker queue.
The project-authenticated replay endpoint requeues the stored event through the
same transactional outbox. It never edits the original payload.

## Daily rollups favour understandable consistency

Worker processing rebuilds a project's daily rollups from its accepted,
processable events. A project row lock serializes updates within one project;
different projects remain independent. This is intentionally a small-fleet v1
strategy, not a claim of unlimited throughput. Reads aggregate at most 90 stored
daily rows. Late-event correctness is preferred over an elaborate incremental
projection engine.

## GitHub collection is explicit evidence

A local collector reads GitHub deployment/status records, follows pagination,
and reports only completed production deployments. It does not reinterpret CI
success as deployment success. Commit metadata can supply an observed lead-time
sample but does not prove which complete change set was deployed. Collection
limitations appear as coverage, and incident completeness is never invented.

## Existing Go starter remains available

The Python DORA service is added alongside the original Go reference service
during the pivot. Its licence and source are preserved. The DORA deployment uses
its own Python image and Compose configuration; the Go container remains a
separate example until migration is complete and verified.