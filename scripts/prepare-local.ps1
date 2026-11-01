$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$path = Join-Path $root '.env'
if (Test-Path -LiteralPath $path) { throw 'Existing .env will not be overwritten' }
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $values = foreach ($name in @('POSTGRES_PASSWORD','RABBITMQ_PASSWORD')) {
        $bytes = New-Object byte[] 32
        $random.GetBytes($bytes)
        $secret = ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
        "$name=$secret"
    }
    [IO.File]::WriteAllLines($path, $values)
    New-Item -ItemType Directory -Force (Join-Path $root '.local') | Out-Null
    Write-Output 'Created local service credentials in ignored .env; values are not printed'
}
finally { $random.Dispose() }