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

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
$jwtSetting = Select-String -Path .env -Pattern '^GPU_MARKETPLACE_JWT_SECRET=.*$'
if (-not $jwtSetting -or $jwtSetting.Line -eq 'GPU_MARKETPLACE_JWT_SECRET=') {
    $jwtSecret = py -3.12 -c "import secrets; print(secrets.token_hex(32))"
    if ($jwtSetting) {
        (Get-Content .env) -replace '^GPU_MARKETPLACE_JWT_SECRET=.*$', "GPU_MARKETPLACE_JWT_SECRET=$jwtSecret" | Set-Content -Encoding Ascii .env
    } else {
        Add-Content -Encoding Ascii .env "GPU_MARKETPLACE_JWT_SECRET=$jwtSecret"
    }
    Remove-Variable jwtSecret
}
$cursorSetting = Select-String -Path .env -Pattern '^GPU_MARKETPLACE_LISTING_CURSOR_SECRET=.*$'
if (-not $cursorSetting -or $cursorSetting.Line -eq 'GPU_MARKETPLACE_LISTING_CURSOR_SECRET=') {
    $cursorSecret = py -3.12 -c "import secrets; print(secrets.token_hex(32))"
    if ($cursorSetting) {
        (Get-Content .env) -replace '^GPU_MARKETPLACE_LISTING_CURSOR_SECRET=.*$', "GPU_MARKETPLACE_LISTING_CURSOR_SECRET=$cursorSecret" | Set-Content -Encoding Ascii .env
    } else {
        Add-Content -Encoding Ascii .env "GPU_MARKETPLACE_LISTING_CURSOR_SECRET=$cursorSecret"
    }
    Remove-Variable cursorSecret
}
$jobsCursorSetting = Select-String -Path .env -Pattern '^GPU_MARKETPLACE_JOBS_CURSOR_SECRET=.*$'
if (-not $jobsCursorSetting -or $jobsCursorSetting.Line -eq 'GPU_MARKETPLACE_JOBS_CURSOR_SECRET=') {
    $jobsCursorSecret = py -3.12 -c "import secrets; print(secrets.token_hex(32))"
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

```powershell
# Load the simple KEY=value entries from .env into this PowerShell process.
foreach ($envLine in Get-Content -LiteralPath .env) {
    if ($envLine -match '^(?<key>[A-Za-z_][A-Za-z0-9_]*)=(?<value>.*)$') {
        Set-Item -Path "Env:$($Matches.key)" -Value $Matches.value
    }
}

# Start only PostgreSQL while provisioning.
docker compose --env-file .env up --detach postgres

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

function Set-LocalEnvValue([string]$Key, [string]$Value) {
    $envLines = @(Get-Content -LiteralPath .env)
    $keyPattern = '^' + [regex]::Escape($Key) + '='
    $found = $false
    for ($index = 0; $index -lt $envLines.Count; $index++) {
        if ($envLines[$index] -match $keyPattern) {
            $envLines[$index] = "$Key=$Value"
            $found = $true
        }
    }
    if (-not $found) { $envLines += "$Key=$Value" }
    Set-Content -LiteralPath .env -Value $envLines -Encoding Ascii
}

# Create random role passwords once. On later runs, reuse the values already in .env.
if (-not $env:GPU_MARKETPLACE_API_DB_PASSWORD) {
    $env:GPU_MARKETPLACE_API_DB_PASSWORD = New-LocalRolePassword
}
if (-not $env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD) {
    $env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD = New-LocalRolePassword
}
$databasePort = if ($env:POSTGRES_HOST_PORT) { $env:POSTGRES_HOST_PORT } else { '5432' }
$escapedOwnerPassword = [uri]::EscapeDataString($env:POSTGRES_PASSWORD)
$ownerDatabaseUrl = "postgresql+psycopg://$($env:POSTGRES_USER):$escapedOwnerPassword@127.0.0.1:$databasePort/$($env:POSTGRES_DB)"
$env:GPU_MARKETPLACE_MIGRATION_DATABASE_URL = $ownerDatabaseUrl

# The bootstrap is create-only. Do not pass passwords as command-line arguments.
uv run --project backend --locked python -m gpu_marketplace.common.db_roles

# Run Alembic as the owner/migration connection, never as the API runtime role.
$env:GPU_MARKETPLACE_DATABASE_URL = $ownerDatabaseUrl
uv run --project backend --locked alembic upgrade head

# Persist local-only credentials/DSNs so API and Manager use their restricted login roles.
$apiPasswordForUrl = [uri]::EscapeDataString($env:GPU_MARKETPLACE_API_DB_PASSWORD)
$managerPasswordForUrl = [uri]::EscapeDataString($env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD)
Set-LocalEnvValue 'GPU_MARKETPLACE_API_DB_PASSWORD' $env:GPU_MARKETPLACE_API_DB_PASSWORD
Set-LocalEnvValue 'GPU_MARKETPLACE_MANAGER_DB_PASSWORD' $env:GPU_MARKETPLACE_MANAGER_DB_PASSWORD
Set-LocalEnvValue 'GPU_MARKETPLACE_MIGRATION_DATABASE_URL' $ownerDatabaseUrl
Set-LocalEnvValue 'GPU_MARKETPLACE_API_DATABASE_URL' "postgresql+psycopg://gpm_api_app:$apiPasswordForUrl@postgres:5432/$($env:POSTGRES_DB)"
Set-LocalEnvValue 'GPU_MARKETPLACE_MANAGER_DATABASE_URL' "postgresql+psycopg://gpm_manager_app:$managerPasswordForUrl@postgres:5432/$($env:POSTGRES_DB)"

# Interactive prompts do not echo passwords. The command refuses remote hosts,
# databases other than gpu_marketplace, and non-owner connections.
uv run --project backend --locked python -m gpu_marketplace.common.local_demo_accounts --allow-local-dev-db
```

The account tool inserts one active `WORKER` and one active `CLIENT`, hashes their passwords with the configured Scrypt implementation, and refuses to overwrite existing login names. It changes no schema or roles and stores no plaintext password. This bootstrap sequence is for a fresh local development database. If a reused volume contains runtime roles whose passwords are unknown, stop and resolve those credentials with its operator; do not regenerate passwords or use `--rotate-password`.

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
