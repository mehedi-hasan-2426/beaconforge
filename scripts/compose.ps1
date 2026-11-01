param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$runtime = Get-Command podman -ErrorAction SilentlyContinue
if (-not $runtime) {
    $installed = @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'BeaconForge\tools') -Filter podman.exe -Recurse -File -ErrorAction SilentlyContinue)
    if ($installed.Count -ne 1) { throw 'A running Podman engine and client are required' }
    $runtimePath = $installed[0].FullName
}
else { $runtimePath = $runtime.Source }
$provider = Join-Path $root '.venv\Scripts\podman-compose.exe'
if (-not (Test-Path $provider)) { throw 'Install podman-compose in the project virtual environment first' }
Push-Location $root
$previous = $env:PODMAN_COMPOSE_PROVIDER
$previousPath = $env:PATH
try {
    $env:PODMAN_COMPOSE_PROVIDER = $provider
    $env:PATH = (Split-Path $runtimePath -Parent) + ';' + $previousPath
    & $runtimePath compose --in-pod false --parallel 1 --file (Join-Path $root 'compose.yaml') @Arguments
    if ($LASTEXITCODE -ne 0) { throw 'Compose operation failed' }
}
finally {
    $env:PODMAN_COMPOSE_PROVIDER = $previous
    $env:PATH = $previousPath
    Pop-Location
}