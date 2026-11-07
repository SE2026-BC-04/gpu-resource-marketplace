$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "local_setup.ps1")

$environmentNames = @(
    "POSTGRES_DB",
    "GPU_MARKETPLACE_API_DB_PASSWORD",
    "GPU_MARKETPLACE_MANAGER_DB_PASSWORD",
    "GPU_MARKETPLACE_API_DATABASE_URL",
    "GPU_MARKETPLACE_MANAGER_DATABASE_URL",
    "PGHOSTADDR"
)
$originalEnvironment = @{}
foreach ($name in $environmentNames) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ("gpm-local-setup-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $temporaryDirectory | Out-Null
$temporaryEnv = Join-Path $temporaryDirectory ".env"
$apiPassword = "api:p@ss/sentinel"
$managerPassword = "manager:p@ss/sentinel"
$ownerDsn = "postgresql+psycopg://gpu_marketplace:owner-sentinel@postgres:5432/gpu_marketplace"

try {
    @(
        "POSTGRES_DB=gpu_marketplace",
        "GPU_MARKETPLACE_API_DATABASE_URL=$ownerDsn",
        "GPU_MARKETPLACE_MANAGER_DATABASE_URL=$ownerDsn",
        "KEEP_THIS_SETTING=unchanged"
    ) | Set-Content -LiteralPath $temporaryEnv -Encoding Ascii

    $env:POSTGRES_DB = "gpu_marketplace"
    $env:GPU_MARKETPLACE_API_DB_PASSWORD = $apiPassword
    $env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD = $managerPassword
    $env:GPU_MARKETPLACE_API_DATABASE_URL = $ownerDsn
    $env:GPU_MARKETPLACE_MANAGER_DATABASE_URL = $ownerDsn
    [Environment]::SetEnvironmentVariable("PGHOSTADDR", $null, "Process")

    Set-LocalRuntimeDatabaseUrls -EnvPath $temporaryEnv

    $apiDsn = $env:GPU_MARKETPLACE_API_DATABASE_URL
    $managerDsn = $env:GPU_MARKETPLACE_MANAGER_DATABASE_URL
    $envLines = @(Get-Content -LiteralPath $temporaryEnv)
    $apiFileValue = (($envLines | Where-Object { $_.StartsWith("GPU_MARKETPLACE_API_DATABASE_URL=") } | Select-Object -First 1) -split "=", 2)[1]
    $managerFileValue = (($envLines | Where-Object { $_.StartsWith("GPU_MARKETPLACE_MANAGER_DATABASE_URL=") } | Select-Object -First 1) -split "=", 2)[1]

    if (-not $apiDsn.StartsWith("postgresql+psycopg://gpm_api_app:") -or $apiDsn -ne $apiFileValue) {
        throw "SETUP-02 failed: API runtime URL was not synchronized."
    }
    if (-not $managerDsn.StartsWith("postgresql+psycopg://gpm_manager_app:") -or $managerDsn -ne $managerFileValue) {
        throw "SETUP-02 failed: Manager runtime URL was not synchronized."
    }
    if ($apiDsn -match "owner-sentinel" -or $managerDsn -match "owner-sentinel") {
        throw "SETUP-02 failed: owner DSN remained in the PowerShell process."
    }
    if ($apiDsn -notmatch "api%3Ap%40ss%2Fsentinel" -or $managerDsn -notmatch "manager%3Ap%40ss%2Fsentinel") {
        throw "SETUP-12 failed: runtime password URL encoding was not applied."
    }
    if ($envLines -notcontains "KEEP_THIS_SETTING=unchanged") {
        throw "Local .env update removed an unrelated setting."
    }

    $env:PGHOSTADDR = "198.51.100.10"
    $routingError = ""
    try {
        Assert-LocalSetupEnvironment
    } catch {
        $routingError = $_.Exception.Message
    }
    if ($routingError -notmatch "PGHOSTADDR" -or $routingError.Contains("198.51.100.10")) {
        throw "Local setup did not safely reject ambient PostgreSQL routing."
    }
    [Environment]::SetEnvironmentVariable("PGHOSTADDR", $null, "Process")

    if ($env:OS -eq "Windows_NT") {
        $failingCommand = { & $env:ComSpec /d /c "echo setup-secret-sentinel 1>&2 & exit /b 23" }
    } else {
        $failingCommand = { sh -c 'printf "setup-secret-sentinel\\n" >&2; exit 23' }
    }

    foreach ($step in @("Role bootstrap", "Alembic migration")) {
        $continuedAfterFailure = $false
        $failureMessage = ""
        try {
            Invoke-LocalSetupNativeCommand -Step $step -Command $failingCommand
            $continuedAfterFailure = $true
        } catch {
            $failureMessage = $_.Exception.Message
        }
        if ($continuedAfterFailure) {
            throw "SETUP-07/08 failed: $step failure did not stop the setup block."
        }
        if ($failureMessage -notmatch [regex]::Escape("$step failed (exit code 23)") -or $failureMessage.Contains("setup-secret-sentinel")) {
            throw "SETUP-12 failed: native-command error was not safely redacted."
        }
    }

    Write-Output "PASS: stale owner DSNs were replaced in process and .env; setup failures stop safely; output contains no credentials."
} finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], "Process")
    }
    Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
