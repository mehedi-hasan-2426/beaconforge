param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'BeaconForge\tools'),
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$manifest = Get-Content (Join-Path $projectRoot 'tools\windows-toolchain.json') -Raw | ConvertFrom-Json

if (-not $manifest.tools -or $manifest.minimumFreeGB -lt 10) {
    throw 'Invalid toolchain manifest or unsafe disk threshold'
}

$names = @()
foreach ($tool in $manifest.tools) {
    if ($tool.name -notmatch '^[a-z][a-z0-9-]*$' -or $names -contains $tool.name) {
        throw 'Invalid or duplicated tool name'
    }
    $names += $tool.name
    $uri = [uri]$tool.url
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin 'dl.k8s.io','github.com','get.helm.sh') {
        throw "Unexpected download origin for $($tool.name)"
    }
    if ($tool.sha256 -notmatch '^[a-f0-9]{64}$' -or $tool.version -notmatch '^v\d+\.\d+\.\d+$') {
        throw "Invalid version or checksum for $($tool.name)"
    }
    if ($tool.archive -notin 'none','zip' -or $tool.executable -notmatch '^[a-z][a-z0-9-]*\.exe$' -or $tool.estimatedMB -le 0) {
        throw "Invalid installation metadata for $($tool.name)"
    }
}

if ($ValidateOnly) {
    Write-Output "Validated $($manifest.tools.Count) pinned tools"
    return
}

if ($env:OS -ne 'Windows_NT' -or $env:PROCESSOR_ARCHITECTURE -ne 'AMD64') {
    throw 'This installer supports Windows AMD64 only'
}

$installPath = [IO.Path]::GetFullPath($InstallRoot)
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($installPath))
$requiredBytes = $manifest.minimumFreeGB * 1GB + ($manifest.tools | Measure-Object -Property estimatedMB -Sum).Sum * 1MB
if ($drive.AvailableFreeSpace -lt $requiredBytes) {
    throw "Installation would leave less than $($manifest.minimumFreeGB) GB free; free disk space first"
}

New-Item -ItemType Directory -Force $installPath | Out-Null
$downloadDirectory = Join-Path $installPath 'downloads'
New-Item -ItemType Directory -Force $downloadDirectory | Out-Null
$ProgressPreference = 'SilentlyContinue'
$executableDirectories = @()

foreach ($tool in $manifest.tools) {
    $extension = if ($tool.archive -eq 'zip') { '.zip' } else { '.exe' }
    $downloadPath = Join-Path $downloadDirectory "$($tool.name)-$($tool.version)$extension"
    if (-not (Test-Path $downloadPath)) {
        Invoke-WebRequest -UseBasicParsing -Uri $tool.url -OutFile $downloadPath
    }
    $actualHash = (Get-FileHash $downloadPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $tool.sha256) {
        throw "Checksum mismatch for $($tool.name); refusing installation"
    }
    $toolDirectory = Join-Path $installPath "$($tool.name)-$($tool.version)"
    if ($tool.archive -eq 'zip') {
        $completionMarker = Join-Path $toolDirectory '.verified'
        if (-not (Test-Path $completionMarker)) {
            if (Test-Path $toolDirectory) { throw "Incomplete installation exists at $toolDirectory; inspect it before retrying" }
            Expand-Archive -LiteralPath $downloadPath -DestinationPath $toolDirectory
            New-Item -ItemType File $completionMarker | Out-Null
        }
    }
    else {
        New-Item -ItemType Directory -Force $toolDirectory | Out-Null
        $executablePath = Join-Path $toolDirectory $tool.executable
        if (Test-Path $executablePath) {
            if ((Get-FileHash $executablePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $tool.sha256) {
                throw "Existing executable differs from the manifest: $executablePath"
            }
        }
        else {
            Move-Item -LiteralPath $downloadPath -Destination $executablePath
        }
    }
    $executables = @(Get-ChildItem $toolDirectory -Filter $tool.executable -Recurse -File)
    if ($executables.Count -ne 1) { throw "Expected one $($tool.executable) in $toolDirectory" }
    $executableDirectories += $executables[0].DirectoryName
    Write-Output "Installed $($tool.name) $($tool.version): $($executables[0].FullName)"
}

$previousUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$userEntries = @($previousUserPath -split ';' | Where-Object { $_ })
foreach ($directory in $executableDirectories) {
    if ($userEntries -notcontains $directory) { $userEntries += $directory }
}
[Environment]::SetEnvironmentVariable('Path', ($userEntries -join ';'), 'User')
$processEntries = @($env:Path -split ';' | Where-Object { $_ })
foreach ($directory in $executableDirectories) {
    if ($processEntries -notcontains $directory) { $processEntries += $directory }
}
$env:Path = $processEntries -join ';'
Write-Output 'User PATH updated; new terminals can access the installed tools'