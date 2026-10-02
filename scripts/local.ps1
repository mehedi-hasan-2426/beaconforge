param(
    [ValidateSet('Test', 'Run', 'Build')]
    [string]$Action = 'Test'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent

function Invoke-Go {
    param([string[]]$GoArguments)
    $toolchain = & go -C $projectRoot env GOVERSION
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not resolve the project Go toolchain'
    }
    $previousToolchain = $env:GOTOOLCHAIN
    try {
        $env:GOTOOLCHAIN = $toolchain
        & go -C $projectRoot @GoArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Go command failed: $($GoArguments -join ' ')"
        }
    }
    finally {
        $env:GOTOOLCHAIN = $previousToolchain
    }
}

switch ($Action) {
    'Test' {
        Invoke-Go -GoArguments @('vet', './...')
        Invoke-Go -GoArguments @('test', './...', '-count=1', '-cover')
        Invoke-Go -GoArguments @('run', 'golang.org/x/vuln/cmd/govulncheck@v1.8.0', './...')
    }
    'Run' {
        Invoke-Go -GoArguments @('run', './cmd/api')
    }
    'Build' {
        $buildDirectory = Join-Path $projectRoot '.tmp'
        New-Item -ItemType Directory -Force $buildDirectory | Out-Null
        $binaryName = if ($env:OS -eq 'Windows_NT') { 'api.exe' } else { 'api' }
        Invoke-Go -GoArguments @('build', '-trimpath', '-o', (Join-Path $buildDirectory $binaryName), './cmd/api')
    }
}