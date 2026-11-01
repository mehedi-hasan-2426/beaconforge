# Local v1 threat model

Assets: project credentials, signing secrets, accepted events, metric integrity,
database state, and broker access. Boundaries: client to API, API to PostgreSQL,
outbox publisher to RabbitMQ, and worker to PostgreSQL. Local Compose publishes
only the API on loopback. Internet exposure and cloud deployment are out of scope.

| STRIDE category | Threat | Control |
|---|---|---|
| Spoofing | Forged events or another project's credentials | Random project API keys stored as hashes; raw-body HMAC-SHA256; constant-time signature comparison |
| Tampering | Payload changed in transit; delivery ID reused with different content | Signature verification, strict schemas, immutable accepted event data, idempotency constraints and conflict response |
| Repudiation | Untraceable acceptance or replay | Server-generated event IDs, timestamps, delivery IDs, processing state and replay count; no secret-bearing logs |
| Information disclosure | Cross-project reads, key leakage, sensitive payload fields | All reads and replays scoped to authenticated project; secret files excluded from Git; schema rejects unknown fields; no body or authentication logging |
| Denial of service | Large requests, unbounded pagination, endless retries | 64 KiB request cap, bounded page size/report windows, broker retry limits, bounded outbox batches and worker concurrency |
| Elevation of privilege | Broker task execution or unauthorized database access | Broker/database not published on host; dedicated worker task names, JSON-only task serialization, scoped project authorization and non-root application containers |

Signing secrets are separate from API keys. Local signing secrets live in an
ignored credentials file, and its contents must not be pasted into logs, issues,
or chat. The database stores signing secrets because it must verify HMAC; database
access is therefore trusted. Encryption at rest and a secret manager would be
required before multi-user public hosting.

TLS, edge rate limiting, centralized audit storage, automated credential rotation,
and public abuse protection are not implemented by the local deployment. API-key
compromise permits access to that project. A signature proves possession of its
secret, not that the deployment or incident assertion is true.