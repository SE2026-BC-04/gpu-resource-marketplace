# Alembic migration boundary

Alembic is configured for the shared Backend API/Manager package.

- `versions/0001_phase1b_baseline.py` is the hand-written Phase 1B baseline: the ten approved tables and the three fixed role codes (`INSERT ... ON CONFLICT DO NOTHING`, safe to rerun). It contains no demo data.
- `versions/0002_phase1b_grants.py` (team-lead decision D1) grants least-privilege access to the `gpm_api_rw` and `gpm_manager_rw` groups. It never creates, alters or drops a role and stops with a clear message when the groups are missing.

## Order of operations

1. **Role bootstrap, as the database owner, before migration** (create-only by default; existing roles are verified, never altered):

   ```
   python -m gpu_marketplace.common.db_roles
   ```

   It reads the owner URL from `GPU_MARKETPLACE_MIGRATION_DATABASE_URL` and the two login passwords from `GPU_MARKETPLACE_API_DB_PASSWORD` / `GPU_MARKETPLACE_MANAGER_DB_PASSWORD`. Values come from the environment only; pass variable names, never values, on a command line. A role that differs from the approved definition stops the run with a non-zero exit code for an operator to fix by hand. Replacing a password requires the explicit `--rotate-password` flag, which no migration or test uses.
2. `alembic upgrade head`.

Downgrade only revokes what revision 0002 granted; it never drops roles because roles are cluster-wide, and it does not hand database privileges back to `PUBLIC` because it cannot know the state before the upgrade.

The bootstrap also refuses (non-zero exit, nothing altered) when an unexpected role is a direct or indirect member of either group. Migration `0002` stops if the runtime groups could `CREATE` in schema `public` (for example `PUBLIC` on a cluster upgraded from PostgreSQL 14 or older); the operator fixes that explicitly. Role passwords are sent to the server as SCRAM verifiers computed by libpq, never as plaintext.

Wiring the bootstrap into `compose.yaml`, `.env.example` and CI is shared infrastructure and is not part of this change. Lifecycle triggers (D2) and guarded delete (D3) are separate revisions.

## Tests

The PostgreSQL tests refuse to run unless they are pointed at a disposable cluster that passes the guards in `backend/tests/db_safety.py`; otherwise they are reported `NOT_RUN`. They create the runtime roles on that cluster with create-only bootstrap and use `SET ROLE` instead of passwords.
