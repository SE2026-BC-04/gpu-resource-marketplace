# GPU Resource Marketplace

GPU Resource Marketplace is a modular-monolith platform foundation for GPU providers and customers. This change establishes the agreed runtime boundaries and local development workflow; it does not implement business workflows.

## Requirements

- Docker Engine with Docker Compose v2 for the complete local stack
- Python 3.12 and uv 0.13.4 for backend and simulator development
- Node.js 24 and npm for frontend development
- Git

The containers use digest-pinned Python 3.12, Node 24, and PostgreSQL 16 images. Python dependencies are locked separately for the shared API/Manager package and the isolated Simulator; frontend dependencies are locked in `frontend/package-lock.json`.

## Start the full stack

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
docker compose --env-file .env up --build
```

When upgrading an existing `.env`, keep the JWT and cursor secrets unchanged and add `GPU_MARKETPLACE_LISTING_CURSOR_SECRET`, `GPU_MARKETPLACE_JOBS_CURSOR_SECRET`, plus the two database URL entries from `.env.example`; do not replace them on each restart. Each cursor key is separate from the JWT secret and from the other cursor key, and stays stable across API restarts so existing cursors remain valid.

The local UI is at `http://localhost:5173`, the operational API at `http://localhost:8000`, and PostgreSQL is bound to `127.0.0.1:5432`. The sample credentials are for local development only. Compose starts five services: `frontend`, `api`, `manager`, `simulator`, and `postgres`.

The API exposes `/health/live`, `/health/ready`, Auth, GPU Listings and Jobs submit/read/cancel routes. Job submission uses the approved `demo-v1-public1` protected reference generator and commits the Job and reference atomically; the reference is never returned in a public DTO or sent to the Simulator. Readiness requires PostgreSQL connectivity and query access to the Auth `users` and `user_roles` tables. A fresh database volume is not migrated automatically; the API remains unready and Auth requests fail with a sanitized `503` until an operator provisions the database using the procedure in [backend/migrations/README.md](backend/migrations/README.md). This repository change does not provision an existing persistent database. The API requires dedicated `GPU_MARKETPLACE_JWT_SECRET`, `GPU_MARKETPLACE_LISTING_CURSOR_SECRET`, and `GPU_MARKETPLACE_JOBS_CURSOR_SECRET` values, each at least 32 UTF-8 bytes; generate them once for the local `.env` as shown above and keep them out of source control. Compose maps separate `GPU_MARKETPLACE_API_DATABASE_URL` and `GPU_MARKETPLACE_MANAGER_DATABASE_URL` values to the corresponding process configuration. The `.env.example` uses the local bootstrap/owner account for local development only; it is not evidence of D1 least-privilege runtime access. Nonlocal deployments must use the D1 `gpm_api_app` and `gpm_manager_app` logins respectively and keep owner/migration credentials separate. The Manager checks its database connection and shuts down on SIGINT/SIGTERM. The Simulator is an independent runtime with health endpoints only. It has no database package, credentials, host port, or database-network attachment.

Stop the stack with `docker compose --env-file .env down`. Add `--volumes` only when you intentionally want to delete the local PostgreSQL data.

## Development checks

Install uv 0.13.4, then run from the repository root:

```powershell
uv sync --project backend --locked --group dev
uv run --project backend --locked --group dev pytest backend/tests tests
uv sync --project simulator --locked --group dev
uv run --project simulator --locked --group dev pytest simulator/tests
```

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

- `backend/` contains the shared Python package and the API and Manager entry points. Domain packages are placeholders for later approved work.
- `simulator/` is a separate Python project and container boundary.
- `frontend/` contains the React/TypeScript/Vite client.
- `compose.yaml` defines the five local services and their isolated networks.
- `docs/architecture/` and `docs/design/` hold the approved architecture and design decisions.
- `docs/development/foundation-handoff.md` records the implementation boundaries and next-step ownership.
- `tests/` contains cross-service architecture and configuration checks.

No authentication, GPU listings, jobs, scheduling, business schemas, or business migrations are included. Authentication details still marked for owner decision remain outside this foundation task.
