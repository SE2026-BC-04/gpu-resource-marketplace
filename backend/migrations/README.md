# Alembic migration boundary

Alembic is configured for the shared Backend API/Manager package.

- `versions/0001_phase1b_baseline.py` is the hand-written Phase 1B baseline: the ten approved tables and the three fixed role codes (`INSERT ... ON CONFLICT DO NOTHING`, safe to rerun). It contains no demo data.
- `versions/0002_phase1b_grants.py` (team-lead decision D1) grants least-privilege access to the `gpm_api_rw` and `gpm_manager_rw` groups. It never creates, alters or drops a role and stops with a clear message when the groups are missing.
- `versions/0003_phase1b_jobs_guard_update.py` (team-lead decision D2) adds the row-level `BEFORE UPDATE` trigger `trg_jobs_guard_update` on `jobs`: terminal Jobs and identity columns are immutable for every caller including the owner, only the four lifecycle edges exist, and each edge belongs to one caller class (API: `QUEUED->CANCELLED`; Manager: `QUEUED->RUNNING`, `RUNNING->COMPLETED/FAILED`). Callers are classified from `current_user` through a recursive walk of `pg_auth_members`; a role in both groups or in neither (and not a superuser or the database owner) is refused. Rejections are SQLSTATE 23000 with the trigger name as constraint. A superuser can still `DISABLE TRIGGER`, so runtime must never use the owner. Downgrade drops the trigger and function only.
- `versions/0004_phase1b_jobs_guard_delete.py` (team-lead decision D3, approved 2026-10-25 with a Phase 1B boundary) adds the row-level `BEFORE DELETE` trigger `trg_jobs_guard_delete` on `jobs`: for every caller including the owner, a Job may be deleted only when it is terminal and `clock_timestamp() >= terminal_at + interval '552 hours'` (23 x 24 elapsed hours, NFR BL-02, half-open cutoff; hours rather than days so a session time zone with daylight saving cannot shorten it); the cascade to `simulation_references` happens only then. No runtime role holds `DELETE` or `TRUNCATE` on `jobs` (D1). The OPEN Dispute condition is added by a Phase 3 revision because Phase 1B has no `disputes` table (`DBP-09` stays BLOCKED). Rejections are SQLSTATE 23000 with the trigger name as constraint and `job_delete_not_eligible` as message. `TRUNCATE` does not fire the trigger and is only for the owner on test databases. Downgrade drops the trigger and function only.

## Order of operations

1. **Role bootstrap, as the database owner, before migration** (create-only by default; existing roles are verified, never altered):

   ```
   python -m gpu_marketplace.common.db_roles
   ```

   It reads the owner URL from `GPU_MARKETPLACE_MIGRATION_DATABASE_URL` and the two login passwords from `GPU_MARKETPLACE_API_DB_PASSWORD` / `GPU_MARKETPLACE_MANAGER_DB_PASSWORD`. Values come from the environment only; pass variable names, never values, on a command line. A role that differs from the approved definition stops the run with a non-zero exit code for an operator to fix by hand. Replacing a password requires the explicit `--rotate-password` flag, which no migration or test uses.
2. `alembic upgrade head`.

Downgrade only revokes what revision 0002 granted; it never drops roles because roles are cluster-wide, and it does not hand database privileges back to `PUBLIC` because it cannot know the state before the upgrade.

The bootstrap also refuses (non-zero exit, nothing altered) when an unexpected role is a direct or indirect member of either group. Before granting, migration `0002` also requires all four runtime roles: both groups, and both login roles as `LOGIN` roles that are direct members of their group; otherwise it stops and asks for the bootstrap, so groups created by hand cannot let it complete without the login roles. Migration `0002` first re-runs the same read-only role check as the bootstrap (restricted attributes, LOGIN/NOLOGIN, INHERIT, exact memberships with the options ADMIN FALSE / INHERIT TRUE / SET TRUE, and no unexpected direct or indirect member of a group or login role) and stops before granting anything if a role has drifted. It then checks the effective privileges of all four runtime roles (both groups and both login roles) and stops with an error naming the role, privilege and object if any of them holds more than the approved matrix. The excess may be a direct grant to a login role, a grant to a group, or a privilege inherited from `PUBLIC` (for example `CREATE` on schema `public` on a cluster upgraded from PostgreSQL 14 or older, or `SELECT` on `simulation_references`). The migration never revokes anything itself: the operator reviews and revokes the privilege explicitly as the owner, then retries, and a refused upgrade leaves the database as it was. Role passwords are sent to the server as SCRAM verifiers computed by libpq, never as plaintext.

Wiring the bootstrap into `compose.yaml`, `.env.example` and CI is shared infrastructure and is not part of this change.

## Tests

The PostgreSQL tests refuse to run unless they are pointed at a disposable cluster that passes the guards in `backend/tests/db_safety.py`; otherwise they are reported `NOT_RUN`. They create the runtime roles on that cluster with create-only bootstrap and use `SET ROLE` instead of passwords.
