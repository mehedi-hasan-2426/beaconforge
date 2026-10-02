# Contributing to BeaconForge

Small fixes, clearer setup instructions, and reproducible bug reports are welcome.
Keep changes focused on the existing service. Discuss new infrastructure separately
instead of bundling it into a service or documentation fix.

## Before You Start

Read [README.md](README.md) for the current capabilities and limitations. Search
existing issues and pull requests after the repository is published. Discuss a
large architectural change before investing in its implementation.

Never put credentials, private business data, or exploit details in a public issue.
Use [SECURITY.md](SECURITY.md) for security concerns and follow
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Local Setup

The Go release is declared in [go.mod](go.mod). Go can select and download it
automatically. PowerShell is needed only for the helper scripts; Docker is needed
only for container checks.

The direct Go checks work without PowerShell:

```sh
go vet ./...
go test ./... -count=1 -cover
```

For Windows users, these helpers run from the repository root:

```powershell
.\scripts\local.ps1 -Action Test
.\scripts\local.ps1 -Action Build
```

The test command runs static analysis, behaviour tests, and vulnerability scanning.
These checks need network access on the first run to download tools and consult
the vulnerability database.

Format changed Go files before submitting a pull request:

```powershell
go fmt ./...
```

When a supported C compiler is available, also run:

```powershell
go test -race ./... -count=1
```

Linux CI runs race detection. If your environment cannot run a check, say so in
the pull request instead of reporting it as passed.

## Optional Windows Tooling

These helpers are preparation for separate platform work, not prerequisites for
running BeaconForge. The current service has no Kubernetes deployment, database,
monitoring backend, or GitOps configuration.

Validate the pinned download manifests without installing or downloading anything:

```powershell
.\scripts\install-tools.ps1 -ValidateOnly
.\scripts\download-charts.ps1 -ValidateOnly
```

To install the tools or fetch chart packages intentionally:

```powershell
.\scripts\install-tools.ps1
.\scripts\download-charts.ps1
```

The Windows AMD64 installer puts kubectl, kind, Helm, Argo CD, and the portable
Podman client under `%LOCALAPPDATA%\BeaconForge\tools` and adds their directories
to the user-level `PATH`. It changes no machine-level `PATH` and launches no
administrator installer. Existing terminals may need restarting. Check your
organisation's software policy before running it on a work machine.

The chart helper requires Helm. It stores verified archives in `.tmp/charts`,
excluded from Git, and checks that Helm can read them. Downloaded charts cover
Prometheus/Grafana, Argo CD, CloudNativePG, and OpenTelemetry. The helper does not
install them into a cluster. A Podman client or WSL distribution by itself does
not mean a container engine is running.

Versions, URLs, and SHA-256 hashes live in
[windows-toolchain.json](tools/windows-toolchain.json) and
[helm-charts.json](tools/helm-charts.json). Update those manifests from upstream
release metadata rather than changing the downloader's implementation. These
pins need manual maintenance; Dependabot does not update them.

Both helpers check host free space and protect a 10 GB reserve before downloads.
That is a download guard, not a capacity guarantee for a cluster. Container images,
virtual disks, and persistent data need additional space. Windows host capacity
also limits a dynamically growing WSL disk, regardless of its reported virtual
capacity. No cluster or cloud resources are created by these scripts.

## Change Design

- Preserve public behaviour unless the change explicitly requires otherwise.
- Put configuration in its owning layer rather than copying values across files.
- Keep the entry point focused on dependency wiring, not business logic.
- Reuse real shared responsibilities; do not abstract similar-looking code just
  to satisfy a DRY checklist.
- Use the standard library when it is a good fit. Explain the need for a new
  dependency and consider its maintenance, security, and licence.
- Keep ordinary development local and free of cloud provisioning.
- Make destructive operations explicit, and document recovery or rollback when
  the change affects deployment or persisted data.

## Code Style

Use descriptive names, cohesive functions, explicit errors, and Go's formatter.
Do not add comments or comment headers to source code, scripts, or workflow files.
Put operational explanations in documentation and express behaviour through tests.

Do not use em dashes in repository text. Keep wording plain and specific. Avoid
calling a capability production-ready or secure without evidence and clear limits.

## Tests

Cover the behaviour that changes, meaningful boundaries, and failure paths. Prefer
testing public behaviour over assertions about implementation details. Mock an
external system when needed, not the application logic you are trying to test.

Do not remove a check, ignore a vulnerability, weaken a threshold, or enable a
policy bypass just to get a green result. Explain genuine exceptions separately
and get them reviewed.

For documentation-only changes, check links, paths, and examples against the
implementation. Do not run the whole Go suite after every wording edit. For code
changes, run a focused test after the coherent change, then the wider checks
required for the affected behaviour and CI. Keep CI gates intact.

## Pull Requests

After publication, work on a short-lived branch from `main` and open a pull
request. Keep it focused on one independently testable outcome.

Use the pull request template to describe the problem, the change, verification
commands and results, and any remaining risks. Include documentation changes when
configuration, usage, or operational behaviour changes.

Required checks and branch protection must be configured in GitHub. The presence
of workflow files alone does not enforce them. Do not claim hosted CI passed when
you have only validated its syntax locally.

On publication, enable available Dependabot alerts, security updates, secret
scanning, push protection, and private vulnerability reporting. Restrict changes
to `main` through pull requests and require the job names that actually run.
Use code-scanning merge protection where available; a successful CodeQL job does
not by itself mean that it found no alerts.

## Commits and Licensing

Write short, imperative commit subjects that explain the change:

```text
Validate empty listener addresses
Document the container shutdown window
Add a readiness failure regression test
```

By submitting a contribution, you agree to license it under this project's
[MIT License](LICENSE). Submit only work you have the right to contribute, and
retain required attribution for third-party material.