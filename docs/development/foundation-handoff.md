# GPU-001 Foundation Handoff

**Status:** GPU-001 project foundation
**Scope:** executable service skeletons, local orchestration, and automated foundation checks

## Implemented source layout

```text
backend/
  src/gpu_marketplace/
    api/             # app factory and process entrypoint
    manager/         # lifecycle, process entrypoint, readiness command
    common/          # settings, logging, database engine/probe
    domain/          # empty SQLAlchemy metadata root
    repositories/    # persistence ownership boundary
    identity/        # Member 3 ownership boundary
    listings/        # Member 4 ownership boundary
    jobs/            # Member 5 ownership boundary
  migrations/        # Alembic bootstrap, empty versions/
  tests/
  pyproject.toml, uv.lock, Dockerfile, alembic.ini
simulator/
  src/gpu_marketplace_simulator/  # independent config, app, logging, entrypoint
  tests/
  pyproject.toml, uv.lock, Dockerfile
frontend/
  src/api/           # operational API client and tests
  src/ui/            # placeholder page and smoke test
  src/config.ts, src/main.tsx, src/styles.css
  package.json, package-lock.json, tsconfig.json, vite.config.ts, Dockerfile
tests/test_compose_topology.py
tools/compose_smoke.py
.github/workflows/foundation.yml
compose.yaml, .env.example, README.md
```

## Runtime boundaries

| Service | Package/runtime | Network access | Responsibility in this foundation |
| --- | --- | --- | --- |
| `frontend` | React 19, TypeScript, Vite, Node 24 | `frontend` only | Placeholder UI; browser calls the API through its loopback-published host URL |
| `api` | FastAPI in the shared backend package | `app` and `database` | HTTP entry point; liveness and database readiness endpoints |
| `manager` | Python process in the shared backend package | `app` and `database` | Independent worker entry point; database readiness and graceful process shutdown |
| `simulator` | Separate FastAPI package and image | `app` only | Isolated runtime with liveness/readiness endpoints; no database credentials or libraries |
| `postgres` | PostgreSQL 16 | `database` only | Persistent local development database |

API and Manager are separate processes sharing the modular-monolith package and SQLAlchemy configuration. The Simulator is not part of that package: it has its own `pyproject.toml`, lockfile, image, settings, and dependency graph. Compose provides no route from the Simulator to the database network. The frontend container is isolated; the browser uses the API's host-published loopback port.

## Backend ownership map

- `gpu_marketplace/api/` owns HTTP routing and app construction.
- `gpu_marketplace/manager/` owns the Manager process lifecycle.
- `gpu_marketplace/common/` owns settings, structured logging, and the shared SQLAlchemy engine/probe.
- `gpu_marketplace/domain/` and `gpu_marketplace/repositories/` reserve domain and persistence-layer package boundaries for later approved phases.
- `migrations/` contains Alembic bootstrap configuration and metadata loading only. It intentionally contains no business migration or table schema.
- `gpu_marketplace_simulator/` owns the isolated simulator HTTP/process skeleton and must remain free of backend imports, database credentials, and database drivers.

## Local workflow

Copy `.env.example` to `.env`, then run `docker compose --env-file .env up --build`. The API readiness endpoint executes `SELECT 1`; the API and Manager wait for a healthy PostgreSQL service through Compose. The sample password is for local development only.

Backend and Simulator locks are independent `uv.lock` files. Use the commands in the root README for their tests. Frontend CI runs `npm ci`, tests, TypeScript checks, and a production bundle build. `tools/compose_smoke.py` verifies all five services become healthy and checks that the Simulator cannot resolve or connect to `postgres`.

The backend Dockerfile's default health check targets the API. Compose overrides the Manager health check with a database probe because Manager is a separate process and does not host HTTP routes.

## Scope and follow-up ownership

This foundation does not implement authentication, authorization, users, GPU listings, reservations, jobs, scheduling, accounting, or business APIs. No business tables or Alembic revisions are created. Work that needs unresolved JWT claims or other owner decisions must wait for those decisions and its own approved task.

The JWT claim/header profile (`iss`, `aud`, `typ`, `sub`), fractional NumericDate details, exact whitespace repertoire and Unicode normalization remain `NEEDS_OWNER_DECISION` in API Contract v0.6 §14.3. These block Authentication implementation, not GPU-001. They have not been guessed in this foundation.

| Owner | Owned paths | Integration boundary |
| --- | --- | --- |
| Team lead | `common/`, `api/app.py`, `manager/`, `simulator/`, Compose, CI, shared configuration | Wires approved module routers and repository dependencies; coordinates integration/review |
| Member 2 | `backend/migrations/`, `domain/`, `repositories/`, database fixtures/tests | Owns SQLAlchemy models and synchronous repository implementation; keeps database access inside backend |
| Member 3 | `backend/src/gpu_marketplace/identity/`, related tests | Authentication/JWT/RBAC implementation waits for the remaining owner decisions |
| Member 4 | `backend/src/gpu_marketplace/listings/`, related tests | Implements approved Listing API using shared repository boundaries |
| Member 5 | `backend/src/gpu_marketplace/jobs/`, related tests | Implements approved Job Lifecycle API using shared repository boundaries |

The directory names in the first two rows are relative to `backend/src/gpu_marketplace/` unless prefixed otherwise. Each module owns its own tests. Backend direction is HTTP/process entrypoint -> module/domain -> repository boundary -> SQLAlchemy/PostgreSQL. Shared infrastructure never imports HTTP routers; modules must not call another module's private implementation. Future routers are assembled centrally by the team lead, rather than each member editing `api/app.py` concurrently. Constructor/function injection at repository boundaries allows unit tests to use test doubles; GPU-001's injected health probe demonstrates this pattern without inventing a business repository interface.

Frontend direction is UI -> `frontend/src/api/client.ts` -> API only. It has no Manager, Simulator, or database client. Simulator has its own settings/logging/lifecycle and never imports backend packages. No unapproved business DTO, repository method, JWT format, or simulation result contract is introduced here.

## Environment configuration

| Variable | Consumer | Default/example and use |
| --- | --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | PostgreSQL container | Local demo database/user/password from `.env.example`; never use the example password in a shared environment |
| `GPU_MARKETPLACE_DATABASE_URL` | API, Manager, Alembic | `postgresql+psycopg://...@postgres:5432/gpu_marketplace` in Compose; replace `postgres` with `localhost` for native processes |
| `GPU_MARKETPLACE_API_HOST`, `GPU_MARKETPLACE_API_PORT` | Native API | `0.0.0.0`, `8000`; leave container ports at their defaults for Docker health checks |
| `GPU_MARKETPLACE_CORS_ORIGINS` | API | JSON array such as `["http://localhost:5173"]`; align with the browser's frontend origin |
| `GPU_MARKETPLACE_LOG_LEVEL` | API, Manager | `INFO` |
| `SIMULATOR_HOST`, `SIMULATOR_PORT`, `SIMULATOR_LOG_LEVEL` | Simulator | `0.0.0.0`, `8080`, `INFO`; Compose sets only the log level and uses internal port 8080 |
| `VITE_API_BASE_URL` | Frontend Vite process/build | `http://localhost:8000`; public browser configuration only; never put secrets in `VITE_*` variables |
| `API_HOST_PORT`, `FRONTEND_HOST_PORT`, `POSTGRES_HOST_PORT` | Compose published ports | `8000`, `5173`, `5432`; all bind to loopback. Changing the frontend port also requires adjusting CORS |

Root `.env` is loaded explicitly by Compose and by native backend settings from the root working directory. Frontend configuration is supplied by its process environment (Compose derives its URL from `API_HOST_PORT`). API and Manager receive only their explicit Compose environment; Simulator receives no database values. No `.env` is committed.

## Run services independently

From the repository root, after installing the locked dependencies as described in README:

```powershell
# Start only the local database. Use the same .env for all Compose commands.
docker compose --env-file .env up -d postgres

# Native API and Manager connect through PostgreSQL's loopback-published port.
$env:GPU_MARKETPLACE_DATABASE_URL = 'postgresql+psycopg://gpu_marketplace:local-dev-only-change-me@localhost:5432/gpu_marketplace'
uv run --project backend --locked python -m gpu_marketplace.api
# In a second terminal, set the same DB URL and run:
uv run --project backend --locked python -m gpu_marketplace.manager

# Simulator requires no database environment variable.
uv run --project simulator --locked python -m gpu_marketplace_simulator

# In a separate terminal:
$env:VITE_API_BASE_URL = 'http://localhost:8000'
npm --prefix frontend run dev
```

The example native DB URL must match your local `.env` password/port. Native Simulator health is `http://localhost:8080/health/live`; its Compose service has no published host port. Stop native processes with Ctrl+C. Uvicorn runs the API/Simulator startup/shutdown lifecycle, and Manager handles SIGINT/SIGTERM on Linux plus Ctrl+C on Windows.

Alembic is initialized with an empty metadata root and an empty versions directory. To inspect that bootstrap without creating business tables, run `uv run --project backend --locked alembic -c backend/alembic.ini heads`. Do not create or apply business revisions as part of GPU-001.

## Verification coverage

Foundation checks cover NFR-M01..04 and the foundation portions of ADR-008 `STACK-01-BOOT`, `STACK-02-LOCKS`, `STACK-03-DB-BOUNDARY`, and `STACK-08-UI-RBAC` (build only). Full business workflows, RBAC, 18-table migrations, performance, signing, and fault recovery cases remain outside this slice and are not claimed PASS. The PR records exact commands and actual local/CI results; authoritative design documents remain unchanged.

Initial local verification used Windows, Python 3.12.15, uv 0.13.4, Node 24.19.0, and npm 10.9.2. Container/CI pins use Node 24.22.0. The host npm shim was broken, so frontend commands were invoked through npm's CLI using the bundled Node 24 executable.

| Check actually run | Local result |
| --- | --- |
| Both `uv sync --locked --offline --group dev` installs after the initial online dependency resolution | PASS; generated locks accepted and cached installs reproducible |
| Backend pytest plus cross-service topology checks | PASS; 18 tests |
| Simulator pytest | PASS; 2 tests |
| `npm ci --offline`, using the cache populated by the initial install | PASS; 112 packages installed |
| `npm test` | PASS; 3 tests in 2 files |
| `npm run typecheck` and `npm run build` | PASS |
| `alembic -c backend/alembic.ini heads` | PASS; no schema revisions, as intended |
| Compose/workflow YAML parse and smoke script syntax check | PASS |
| Local `docker compose config`, service bring-up, PostgreSQL connectivity, and live network-isolation smoke | NOT_RUN; Docker/Compose are unavailable on the host. The PR's Compose CI job runs these checks on Linux |

Both Python suites emit the upstream Starlette TestClient deprecation warning about `httpx`; tests still pass. No unapproved replacement HTTP client was added to silence that warning. Full image reproducibility across two builds and layer/log secret-injection tests (`STACK-02`/`STACK-09` in full) remain NOT_RUN; the committed lockfiles and digest pins provide the foundation for those later checks.

## Architecture note

The currently approved architecture and ADR set establish Docker Compose for the five-service local foundation and distinguish the Simulator's runtime boundary. One older QA-OPS-01 sentence still describes Compose approval as pending; this implementation follows the later approved decision recorded in ADR-008 and the GPU-001 task scope. Resolve that stale sentence through the normal documentation change process separately.
