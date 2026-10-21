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
Copy-Item .env.example .env
docker compose --env-file .env up --build
```

The local UI is at `http://localhost:5173`, the operational API at `http://localhost:8000`, and PostgreSQL is bound to `127.0.0.1:5432`. The sample credentials are for local development only. Compose starts five services: `frontend`, `api`, `manager`, `simulator`, and `postgres`.

The API exposes only `/health/live` and `/health/ready` at this stage. Readiness checks PostgreSQL with `SELECT 1`. The Manager checks its database connection and shuts down on SIGINT/SIGTERM. The Simulator is an independent runtime with health endpoints only. It has no database package, credentials, host port, or database-network attachment.

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
docker compose --env-file .env.example config --quiet
python tools/compose_smoke.py
```

The smoke check starts a uniquely named Compose project, waits for all services to become healthy, verifies that the Simulator cannot reach PostgreSQL, then removes only that temporary project's containers, network, and volume.

## Repository map

- `backend/` contains the shared Python package and the API and Manager entry points. Domain packages are placeholders for later approved work.
- `simulator/` is a separate Python project and container boundary.
- `frontend/` contains the React/TypeScript/Vite client.
- `compose.yaml` defines the five local services and their isolated networks.
- `docs/architecture/` and `docs/design/` hold the approved architecture and design decisions.
- `docs/development/foundation-handoff.md` records the implementation boundaries and next-step ownership.
- `tests/` contains cross-service architecture and configuration checks.

No authentication, GPU listings, jobs, scheduling, business schemas, or business migrations are included. Authentication details still marked for owner decision remain outside this foundation task.
