# Alembic migration boundary

Alembic is configured for the shared Backend API/Manager package.

- `versions/0001_phase1b_baseline.py` is the hand-written Phase 1B baseline: the ten approved tables and the three fixed role codes (`INSERT ... ON CONFLICT DO NOTHING`, safe to rerun). It contains no demo data.
- `versions/0002_phase1b_grants.py` (team-lead decision D1) grants least-privilege access to the `gpm_api_rw` and `gpm_manager_rw` groups. It never creates, alters or drops a role and stops with a clear message when the groups are missing.
- `versions/0003_listing_d7.py` follows the current accepted head 0002 and implements the [conditionally approved Listing-only D7 design](../../docs/development/change-requests/CR-GPU-004-D7-01.md). It creates `trg_gpu_listings_guard_update` and its SECURITY INVOKER function, rejects identity/owner/created_at changes with SQLSTATE `23514` / `ck_gpu_listings_identity_immutable`, and sets updated_at from the DB clock on every SQL UPDATE. It changes no table/column/role or D1 grants. Pending D2/D3 are separate; re-parent/retest D7 if the accepted main head changes before merge.

## Order of operations

1. **Role bootstrap, as the database owner, before migration** (create-only by default; existing roles are verified, never altered):

   ```
   python -m gpu_marketplace.common.db_roles
   ```

   It reads the owner URL from `GPU_MARKETPLACE_MIGRATION_DATABASE_URL` and the two login passwords from `GPU_MARKETPLACE_API_DB_PASSWORD` / `GPU_MARKETPLACE_MANAGER_DB_PASSWORD`. Values come from the environment only; pass variable names, never values, on a command line. A role that differs from the approved definition stops the run with a non-zero exit code for an operator to fix by hand. Replacing a password requires the explicit `--rotate-password` flag, which no migration or test uses.
2. `alembic upgrade head`.

D1 downgrade only revokes what revision 0002 granted; it never drops roles because roles are cluster-wide, and it does not hand database privileges back to `PUBLIC` because it cannot know the state before the upgrade. D7 downgrade drops only its trigger/function and preserves all rows, timestamps and D1 ACLs. The Listing adapter rejects effective updates when the enabled D7 mechanism is absent; coordinate feature/migration rollout with the integrator rather than enabling incomplete writes or automatically downgrading production.

The bootstrap also refuses (non-zero exit, nothing altered) when an unexpected role is a direct or indirect member of either group. Before granting, migration `0002` also requires all four runtime roles: both groups, and both login roles as `LOGIN` roles that are direct members of their group; otherwise it stops and asks for the bootstrap, so groups created by hand cannot let it complete without the login roles. Migration `0002` first re-runs the same read-only role check as the bootstrap (restricted attributes, LOGIN/NOLOGIN, INHERIT, exact memberships with the options ADMIN FALSE / INHERIT TRUE / SET TRUE, and no unexpected direct or indirect member of a group or login role) and stops before granting anything if a role has drifted. It then checks the effective privileges of all four runtime roles (both groups and both login roles) and stops with an error naming the role, privilege and object if any of them holds more than the approved matrix. The excess may be a direct grant to a login role, a grant to a group, or a privilege inherited from `PUBLIC` (for example `CREATE` on schema `public` on a cluster upgraded from PostgreSQL 14 or older, or `SELECT` on `simulation_references`). The migration never revokes anything itself: the operator reviews and revokes the privilege explicitly as the owner, then retries, and a refused upgrade leaves the database as it was. Role passwords are sent to the server as SCRAM verifiers computed by libpq, never as plaintext.

Wiring the bootstrap into `compose.yaml`, `.env.example` and CI is shared infrastructure and is not part of this change. Lifecycle triggers (D2) and guarded delete (D3) are separate revisions.

## Tests

The PostgreSQL tests refuse to run unless they are pointed at a disposable cluster that passes the guards in `backend/tests/db_safety.py`; otherwise they are reported `NOT_RUN`. They create the runtime roles on that cluster with create-only bootstrap and use `SET ROLE` instead of passwords.

The D7 suite additionally verifies a real TCP `gpm_api_app` login without SET ROLE. Its guarded, disposable-only credential fixture temporarily installs a random password as a libpq-computed SCRAM verifier, opens a restricted engine, closes it, then restores the original verifier. Passwords/verifiers/DSNs are not printed. No bootstrap default, role attribute/membership/grant or production configuration is changed. These tests do not mount the production Auth/Listings application or establish browser E2E acceptance.
