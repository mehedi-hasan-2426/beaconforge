# Security Policy

## Project Status

BeaconForge is a local learning and reference project, not a supported public
production service. The current development line is the supported scope; there
are no released versions or long-term support branches yet.

## Reporting a Vulnerability

After publication, use GitHub's private vulnerability reporting through the
repository's Security tab when it is enabled. Do not disclose an exploit or paste
credentials into a public issue, discussion, or pull request.

If private reporting is unavailable, ask the maintainer to provide a private
reporting route without posting sensitive details. No private reporting channel
has been configured for this unpublished repository yet.

A useful report includes:

- The affected commit or version and relevant files.
- A minimal, safe reproduction with synthetic data.
- Expected and observed behaviour.
- The potential impact and any proposed mitigation.

If you discover a leaked credential, revoke or rotate it first. Do not send its
working value in the report. Removing it from the latest commit is not enough to
invalidate a secret or erase Git history.

This is a community-maintained project. There is no guaranteed response time or
security support agreement.

## Scope

Relevant areas include the Go service, configuration handling, local helper,
Docker build, GitHub Actions workflows, and dependency update configuration.

Third-party tools, Go itself, GitHub, and the separate inspiration repositories
have their own maintainers and disclosure processes. Configuration in this
project can still be reported here if it misuses one of those tools.

## Current Boundaries

- The host service binds to loopback by default. The documented container command
  also publishes its port on loopback only.
- The service has no authentication, authorisation, or TLS. Do not expose it to
  the internet or use it with sensitive production data.
- Request logs omit paths, query strings, request headers, and request bodies.
- HTTP timeouts and header-size limits are bounded, but they are not a complete
  denial-of-service defence.
- The runtime container uses a non-root user. Read-only storage, capability drops,
  process limits, and resource limits depend on the documented runtime command
  or a future deployment definition, not on the image alone.
- No application data is persisted yet. Recovery guarantees have not been tested
  for a database that does not exist.

## Automated Checks

The repository defines Go static analysis, tests, vulnerability scanning, Linux
race detection, gitleaks, CodeQL, dependency review, and Trivy checks. See
[README.md](README.md#security-and-limits) for the boundaries and blocking thresholds,
and [.github/workflows/security.yml](.github/workflows/security.yml) for the jobs.

Local verification is documented separately from hosted CI. Workflow definitions
are not proof that their checks passed. Dependabot alerts, private vulnerability
reporting, code-scanning protection, and branch rules need configuring when the
repository is published.