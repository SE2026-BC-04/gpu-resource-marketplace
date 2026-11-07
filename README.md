# GPU Resource Marketplace

GPU Resource Marketplace is a simulation-only modular-monolith MVP for GPU providers and customers. Phase 1 integrates Authentication, GPU Listings, and Jobs submit/read/cancel on the production React, FastAPI, and PostgreSQL runtime. It does not execute GPU workloads: a submitted Job remains `QUEUED` until it is cancelled or a later approved phase adds execution.

## Requirements

- Docker Engine with Docker Compose v2 for the complete local stack
- Python 3.12 and uv 0.13.4 for backend and simulator development
- Node.js 24 and npm for frontend development
- Git

## Clone the repository

```powershell
git clone https://github.com/SE2026-BC-04/gpu-resource-marketplace.git
Set-Location gpu-resource-marketplace
```

The containers use digest-pinned Python 3.12, Node 24, and PostgreSQL 16 images. Python dependencies are locked separately for the shared API/Manager package and the isolated Simulator; frontend dependencies are locked in `frontend/package-lock.json`.

## Configure local signing secrets

The following PowerShell helper uses the operating system cryptographic random number generator, so this step does not depend on the Python launcher.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
function New-LocalHexSecret {
    $randomBytes = New-Object byte[] 32
    $randomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomGenerator.GetBytes($randomBytes)
        return [BitConverter]::ToString($randomBytes).Replace('-', '').ToLowerInvariant()
    } finally {
        $randomGenerator.Dispose()
    }
}
$jwtSetting = Select-String -Path .env -Pattern '^GPU_MARKETPLACE_JWT_SECRET=.*$'
if (-not $jwtSetting -or $jwtSetting.Line -eq 'GPU_MARKETPLACE_JWT_SECRET=') {
    $jwtSecret = New-LocalHexSecret
    if ($jwtSetting) {
        (Get-Content .env) -replace '^GPU_MARKETPLACE_JWT_SECRET=.*$', "GPU_MARKETPLACE_JWT_SECRET=$jwtSecret" | Set-Content -Encoding Ascii .env
    } else {
        Add-Content -Encoding Ascii .env "GPU_MARKETPLACE_JWT_SECRET=$jwtSecret"
    }
    Remove-Variable jwtSecret
}
$cursorSetting = Select-String -Path .env -Pattern '^GPU_MARKETPLACE_LISTING_CURSOR_SECRET=.*$'
if (-not $cursorSetting -or $cursorSetting.Line -eq 'GPU_MARKETPLACE_LISTING_CURSOR_SECRET=') {
    $cursorSecret = New-LocalHexSecret
    if ($cursorSetting) {
        (Get-Content .env) -replace '^GPU_MARKETPLACE_LISTING_CURSOR_SECRET=.*$', "GPU_MARKETPLACE_LISTING_CURSOR_SECRET=$cursorSecret" | Set-Content -Encoding Ascii .env
    } else {
        Add-Content -Encoding Ascii .env "GPU_MARKETPLACE_LISTING_CURSOR_SECRET=$cursorSecret"
    }
    Remove-Variable cursorSecret
}
$jobsCursorSetting = Select-String -Path .env -Pattern '^GPU_MARKETPLACE_JOBS_CURSOR_SECRET=.*$'
if (-not $jobsCursorSetting -or $jobsCursorSetting.Line -eq 'GPU_MARKETPLACE_JOBS_CURSOR_SECRET=') {
    $jobsCursorSecret = New-LocalHexSecret
    if ($jobsCursorSetting) {
        (Get-Content .env) -replace '^GPU_MARKETPLACE_JOBS_CURSOR_SECRET=.*$', "GPU_MARKETPLACE_JOBS_CURSOR_SECRET=$jobsCursorSecret" | Set-Content -Encoding Ascii .env
    } else {
        Add-Content -Encoding Ascii .env "GPU_MARKETPLACE_JOBS_CURSOR_SECRET=$jobsCursorSecret"
    }
    Remove-Variable jobsCursorSecret
}
```

## Provision PostgreSQL and local demo accounts

The Compose file does not run migrations or create user accounts. On a fresh local database, provision runtime roles, apply the reviewed migrations, and create demo accounts before starting the full stack. The following PowerShell commands use the existing `.env`; keep it local and ignored by Git.

Run the entire provisioning block in one PowerShell window. It waits for PostgreSQL health and stops on any non-zero bootstrap or migration exit code. The helper suppresses native command output on failure so an error cannot print a credential-bearing DSN.

```powershell
# Load the simple KEY=value entries from .env into this PowerShell process.
foreach ($envLine in Get-Content -LiteralPath .env) {
    if ($envLine -match '^(?<key>[A-Za-z_][A-Za-z0-9_]*)=(?<value>.*)$') {
        Set-Item -Path "Env:$($Matches.key)" -Value $Matches.value
    }
}

. .\tools\local_setup.ps1
$ErrorActionPreference = 'Stop'

try {
    Assert-LocalSetupEnvironment

    # Start only PostgreSQL and wait for its Compose healthcheck before role bootstrap.
    Invoke-LocalSetupNativeCommand -Step 'PostgreSQL healthy' -Command {
        docker compose --env-file .env up --detach --wait --wait-timeout 120 postgres
    }

    function New-LocalRolePassword {
        $randomBytes = New-Object byte[] 32
        $randomGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $randomGenerator.GetBytes($randomBytes)
            return [BitConverter]::ToString($randomBytes).Replace('-', '').ToLowerInvariant()
        } finally {
            $randomGenerator.Dispose()
        }
    }

    # Create role passwords only when missing. Persist them before bootstrap so a
    # later retry reuses the same values. Existing PostgreSQL roles are never rotated.
    if (-not $env:GPU_MARKETPLACE_API_DB_PASSWORD) {
        $env:GPU_MARKETPLACE_API_DB_PASSWORD = New-LocalRolePassword
    }
    if (-not $env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD) {
        $env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD = New-LocalRolePassword
    }
    Set-LocalEnvValue -Key 'GPU_MARKETPLACE_API_DB_PASSWORD' -Value $env:GPU_MARKETPLACE_API_DB_PASSWORD -EnvPath .env
    Set-LocalEnvValue -Key 'GPU_MARKETPLACE_MANAGER_DB_PASSWORD' -Value $env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD -EnvPath .env

    $databasePort = if ($env:POSTGRES_HOST_PORT) { $env:POSTGRES_HOST_PORT } else { '5432' }
    $escapedOwnerUsername = [uri]::EscapeDataString($env:POSTGRES_USER)
    $escapedOwnerPassword = [uri]::EscapeDataString($env:POSTGRES_PASSWORD)
    $escapedDatabase = [uri]::EscapeDataString($env:POSTGRES_DB)
    $ownerDatabaseUrl = "postgresql+psycopg://$escapedOwnerUsername`:$escapedOwnerPassword@127.0.0.1`:$databasePort/$escapedDatabase"
    $env:GPU_MARKETPLACE_MIGRATION_DATABASE_URL = $ownerDatabaseUrl
    Set-LocalEnvValue -Key 'GPU_MARKETPLACE_MIGRATION_DATABASE_URL' -Value $ownerDatabaseUrl -EnvPath .env

    # The bootstrap is create-only. It never rotates an existing role password.
    Invoke-LocalSetupNativeCommand -Step 'Runtime role bootstrap' -Command {
        uv run --project backend --locked python -m gpu_marketplace.common.db_roles
    }

    # Replace owner DSNs in both this shell and .env before Compose can read either one.
    Set-LocalRuntimeDatabaseUrls -EnvPath .env

    # Migrations use the owner URL, separately from both restricted runtime URLs.
    $env:GPU_MARKETPLACE_DATABASE_URL = $ownerDatabaseUrl
    Invoke-LocalSetupNativeCommand -Step 'Alembic migration to head' -Command {
        uv run --project backend --locked alembic -c backend/alembic.ini upgrade head
    }
    Invoke-LocalSetupNativeCommand -Step 'Alembic current revision' -Command {
        uv run --project backend --locked alembic -c backend/alembic.ini current
    }
    Invoke-LocalSetupNativeCommand -Step 'Database revision matches repository head' -Command {
        uv run --project backend --locked python tools/verify_alembic_head.py
    }

    # Validate the effective Compose config without printing the resolved secrets.
    $composeConfigText = docker compose --env-file .env config --format json 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Compose configuration validation failed; output was suppressed.' }
    try {
        $composeConfig = $composeConfigText | ConvertFrom-Json
    } catch {
        throw 'Compose configuration could not be parsed; output was suppressed.'
    }
    $apiComposeDsn = [string]$composeConfig.services.api.environment.GPU_MARKETPLACE_DATABASE_URL
    $managerComposeDsn = [string]$composeConfig.services.manager.environment.GPU_MARKETPLACE_DATABASE_URL
    $apiComposeUser = [regex]::Match($apiComposeDsn, '^postgresql\+psycopg://(?<user>[^:@/]+):').Groups['user'].Value
    $managerComposeUser = [regex]::Match($managerComposeDsn, '^postgresql\+psycopg://(?<user>[^:@/]+):').Groups['user'].Value
    if ($apiComposeDsn -ne $env:GPU_MARKETPLACE_API_DATABASE_URL -or $apiComposeUser -ne 'gpm_api_app') {
        throw 'Compose API configuration does not use the restricted API login; DSN details were suppressed.'
    }
    if ($managerComposeDsn -ne $env:GPU_MARKETPLACE_MANAGER_DATABASE_URL -or $managerComposeUser -ne 'gpm_manager_app') {
        throw 'Compose Manager configuration does not use the restricted Manager login; DSN details were suppressed.'
    }
    Remove-Variable composeConfigText, composeConfig, apiComposeDsn, managerComposeDsn, apiComposeUser, managerComposeUser

    # Test API/Manager native logins after grants exist. This detects stale passwords
    # without rotating roles. A mismatch stops before demo accounts or V1 startup.
    Invoke-LocalSetupNativeCommand -Step 'Restricted runtime role verification' -Command {
        uv run --project backend --locked python tools/verify_runtime_roles.py
    }

    # Interactive prompts do not echo passwords. This CLI refuses remote hosts,
    # databases other than gpu_marketplace, and non-owner connections.
    uv run --project backend --locked python -m gpu_marketplace.common.local_demo_accounts --allow-local-dev-db
    if ($LASTEXITCODE -ne 0) {
        throw "Demo-account provisioning failed (exit code $LASTEXITCODE). Setup stopped."
    }
} catch {
    Write-Error 'Local provisioning stopped. Review the failed step and exit code; sensitive command output was suppressed.'
    throw
}
```

The account tool inserts one active `WORKER` and one active `CLIENT`, hashes their passwords with the configured Scrypt implementation, and refuses to overwrite existing login names. It changes no schema or roles and stores no plaintext password. This bootstrap sequence is for a fresh local development database. Existing PostgreSQL roles are create-only: if a reused volume has unknown or mismatched runtime passwords, native login verification stops setup without changing them. Resolve credentials with the database operator; do not regenerate passwords or use `--rotate-password`.

The demo-account tool accepts only a PostgreSQL URL with an explicit loopback host, TCP port, username, and the `gpu_marketplace` database; it rejects every URL query parameter. It also refuses to connect if `PGHOST`, `PGHOSTADDR`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSERVICE`, or `PGSERVICEFILE` is set in the current PowerShell environment. Inspect and clear any such routing overrides before running the tool.

## Start and use the V1 application

After provisioning, start the five Compose services:

```powershell
docker compose --env-file .env up --build
```

At the default ports, open `http://localhost:5173`. Sign in as the Worker account created above and create an ACTIVE GPU Listing. Sign out, sign in as the Client, browse Listings, submit a Job, view it, and cancel it while it is `QUEUED`. Phase 1 has no Manager scheduler or Simulator execution, so Jobs do not advance to `RUNNING` automatically.

When upgrading an existing `.env`, preserve the JWT and cursor secrets. The provisioning commands add separate API and Manager role DSNs; keep them stable across restarts. Each cursor key must be distinct from the JWT secret and from the other cursor key. Compose starts five services: `frontend`, `api`, `manager`, `simulator`, and `postgres`.

The API exposes `/health/live`, `/health/ready`, Auth, GPU Listings and Jobs submit/read/cancel routes. Job submission uses the owner-approved `demo-v1-public1` protected-reference version, creates the Job and reference atomically, and never returns the reference in a public DTO or sends it to the Simulator. Current readiness checks database connectivity and Auth table access; full Listings/Jobs readiness remains an owner-decision gate documented in the [integration progress record](docs/development/handoffs/GPU-INT-01_integration_progress.md). A fresh database volume is not migrated automatically; follow [backend/migrations/README.md](backend/migrations/README.md) and the local setup above. Keep the three distinct signing secrets and database role passwords in the ignored `.env`; they are never checked into source control. `.env.example` starts with local bootstrap credentials and is not evidence of D1 least-privilege runtime access; the setup procedure replaces API and Manager DSNs with `gpm_api_app` and `gpm_manager_app`. The Manager currently checks database connectivity and shuts down on SIGINT/SIGTERM. The Simulator is a separate runtime with health endpoints only and has no database package, credentials, host port, or database-network attachment.

Stop services with `docker compose --env-file .env down`. This keeps the PostgreSQL volume. Add `--volumes` only when you intentionally want to delete all local database data.

## Development checks

Install uv 0.13.4, then run from the repository root:

```powershell
uv sync --project backend --locked --group dev
uv run --project backend --locked --group dev pytest backend/tests tests
uv sync --project simulator --locked --group dev
uv run --project simulator --locked --group dev pytest simulator/tests
```

The guarded Phase 1 PostgreSQL E2E test also drives the production frontend in Chromium. Run `npm ci` in `frontend/` and install Chromium with `npx playwright install chromium` before running it. The test only executes when the disposable database safety markers described in `backend/tests/db_safety.py` are set; without them pytest reports the database case as skipped.

For the frontend:

```powershell
cd frontend
npm ci
npm test
npm run typecheck
npm run build
```

Validate and exercise the Compose topology with:

```powershell
docker compose --env-file .env config --quiet
uv run --project backend --locked python tools/compose_smoke.py
```

The smoke check starts a uniquely named Compose project on dynamically allocated loopback ports, waits for all services to become healthy, and runs `SELECT 1` from the host through PostgreSQL's published port. It also checks API and Manager database readiness, verifies that the Simulator cannot reach PostgreSQL, and confirms cleanup removes only the smoke project's resources while preserving any existing local stack.

## Repository map

- `backend/` contains the shared Python package, Auth/Listings/Jobs API, Manager process, Alembic migrations, PostgreSQL adapters, and safety-guarded tests.
- `simulator/` is a separate Python project and container boundary.
- `frontend/` contains the React/TypeScript/Vite client.
- `compose.yaml` defines the five local services and their isolated networks.
- `docs/architecture/` and `docs/design/` hold the approved architecture, phase plans, contracts, and design decisions.
- `docs/development/handoffs/GPU-INT-01_integration_progress.md` records integration progress, evidence, and remaining review gates.
- `tests/` contains cross-service architecture and configuration checks.

No public account registration endpoint is provided; accounts are provisioned by an operator. The local demo-account tool is intentionally restricted to an explicitly confirmed loopback development database. The MVP remains simulation-only, and Phase 2 scheduling/execution is outside this repository workflow.
