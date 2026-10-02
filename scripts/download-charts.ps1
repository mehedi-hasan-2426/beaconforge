param(
    [string]$Destination = (Join-Path (Split-Path $PSScriptRoot -Parent) '.tmp\charts'),
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$manifest = Get-Content (Join-Path $projectRoot 'tools\helm-charts.json') -Raw | ConvertFrom-Json

if (-not $manifest.charts -or $manifest.minimumFreeGB -lt 10) {
    throw 'Invalid chart manifest or unsafe disk threshold'
}

$names = @()
foreach ($chart in $manifest.charts) {
    if ($chart.name -notmatch '^[a-z][a-z0-9-]*$' -or $names -contains $chart.name) {
        throw 'Invalid or duplicated chart name'
    }
    $names += $chart.name
    $uri = [uri]$chart.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com' -or $uri.UserInfo) {
        throw "Unexpected download origin for $($chart.name)"
    }
    if ($chart.sha256 -notmatch '^[a-f0-9]{64}$' -or $chart.version -notmatch '^\d+\.\d+\.\d+$') {
        throw "Invalid version or checksum for $($chart.name)"
    }
}

if ($ValidateOnly) {
    Write-Output "Validated $($manifest.charts.Count) pinned charts"
    return
}

Get-Command helm -ErrorAction Stop | Out-Null
$destinationPath = [IO.Path]::GetFullPath($Destination)
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($destinationPath))
if ($drive.AvailableFreeSpace -lt $manifest.minimumFreeGB * 1GB + 64MB) {
    throw "Chart download would leave less than $($manifest.minimumFreeGB) GB free"
}
New-Item -ItemType Directory -Force $destinationPath | Out-Null
$ProgressPreference = 'SilentlyContinue'

foreach ($chart in $manifest.charts) {
    $packagePath = Join-Path $destinationPath "$($chart.name)-$($chart.version).tgz"
    if (-not (Test-Path $packagePath)) {
        Invoke-WebRequest -UseBasicParsing -Uri $chart.url -OutFile $packagePath
    }
    $actualHash = (Get-FileHash $packagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $chart.sha256) {
        throw "Checksum mismatch for $($chart.name); refusing package use"
    }
    helm show chart $packagePath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Helm could not read the verified package: $($chart.name)" }
    Write-Output "Downloaded and verified $($chart.name) $($chart.version)"
}

Write-Output "Chart packages are in $destinationPath; no workloads were deployed"