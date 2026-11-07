function Set-LocalEnvValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [string]$EnvPath = ".env"
    )

    if ($Value.Contains("`r") -or $Value.Contains("`n")) {
        throw "Refusing a multiline value for local environment key $Key."
    }

    $envLines = [System.Collections.Generic.List[string]]::new()
    if (Test-Path -LiteralPath $EnvPath) {
        foreach ($line in Get-Content -LiteralPath $EnvPath) {
            $envLines.Add([string]$line)
        }
    }

    $keyPattern = '^' + [regex]::Escape($Key) + '='
    $replacement = "$Key=$Value"
    $found = $false
    $updatedLines = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $envLines) {
        if ($line -match $keyPattern) {
            if (-not $found) {
                $updatedLines.Add($replacement)
                $found = $true
            }
        } else {
            $updatedLines.Add($line)
        }
    }
    if (-not $found) {
        $updatedLines.Add($replacement)
    }

    Set-Content -LiteralPath $EnvPath -Value $updatedLines -Encoding Ascii
}

function Set-LocalRuntimeDatabaseUrls {
    [CmdletBinding()]
    param([string]$EnvPath = ".env")

    $required = @(
        "POSTGRES_DB",
        "GPU_MARKETPLACE_API_DB_PASSWORD",
        "GPU_MARKETPLACE_MANAGER_DB_PASSWORD"
    )
    $missing = @($required | Where-Object { -not [Environment]::GetEnvironmentVariable($_, "Process") })
    if ($missing.Count -gt 0) {
        throw "Missing required local setup environment variables: $($missing -join ', ')."
    }

    $database = [uri]::EscapeDataString($env:POSTGRES_DB)
    $apiPassword = [uri]::EscapeDataString($env:GPU_MARKETPLACE_API_DB_PASSWORD)
    $managerPassword = [uri]::EscapeDataString($env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD)
    $apiDsn = "postgresql+psycopg://gpm_api_app:$apiPassword@postgres:5432/$database"
    $managerDsn = "postgresql+psycopg://gpm_manager_app:$managerPassword@postgres:5432/$database"

    # Keep Compose's process-environment and .env inputs aligned. A shell that loaded
    # .env before role bootstrap must not retain the earlier owner URLs.
    $env:GPU_MARKETPLACE_API_DATABASE_URL = $apiDsn
    $env:GPU_MARKETPLACE_MANAGER_DATABASE_URL = $managerDsn
    Set-LocalEnvValue -Key "GPU_MARKETPLACE_API_DATABASE_URL" -Value $apiDsn -EnvPath $EnvPath
    Set-LocalEnvValue -Key "GPU_MARKETPLACE_MANAGER_DATABASE_URL" -Value $managerDsn -EnvPath $EnvPath
}

function Assert-LocalSetupEnvironment {
    [CmdletBinding()]
    param()

    $routingVariables = @(
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGSERVICE",
        "PGSERVICEFILE"
    )
    $configured = @(
        $routingVariables | Where-Object {
            $null -ne [Environment]::GetEnvironmentVariable($_, "Process")
        }
    )
    if ($configured.Count -gt 0) {
        throw "Clear PostgreSQL routing environment variables before local setup: $($configured -join ', ')."
    }
}

function Invoke-LocalSetupNativeCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Step,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    try {
        & $Command 1>$null 2>$null
    } catch {
        throw "$Step failed before an exit code was returned. Output was suppressed; setup stopped."
    }

    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode -or $exitCode -ne 0) {
        $reportedCode = if ($null -eq $exitCode) { "unavailable" } else { [string]$exitCode }
        throw "$Step failed (exit code $reportedCode). Output was suppressed; setup stopped."
    }

    Write-Host "PASS: $Step"
}
