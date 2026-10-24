"""Phase 1B Job lifecycle guard ``trg_jobs_guard_update`` (decision D2, schema matrix section 7).

Defense in depth for ``jobs`` that applies to every caller, the owner included:

* a terminal Job (COMPLETED, FAILED, CANCELLED) is never updated again;
* the identity columns never change;
* without a status change no column changes;
* only QUEUED->RUNNING, QUEUED->CANCELLED, RUNNING->COMPLETED and RUNNING->FAILED exist;
* the edge must belong to the caller: the API may only cancel, the Manager may start and finish, a role in both
  groups is refused, and a role in neither group is refused unless it is a superuser or the database owner
  (maintenance), which stays bound by the rules above. These two refusals apply to every UPDATE, a no-op
  included, so the caller is classified before a no-op is accepted.

The trigger function is not executable by PUBLIC (schema matrix 6.2); firing a trigger needs no EXECUTE.

The caller is classified from ``current_user`` by walking ``pg_auth_members`` recursively, never with
``pg_has_role()``, which answers true for a superuser about every role. The function is SECURITY INVOKER, so
``current_user`` is the role running the statement, including after SET ROLE.

Every rejection is SQLSTATE 23000 with CONSTRAINT set to the trigger name and the reason as the message, so the
repository maps it like any other constraint. A superuser can still DISABLE TRIGGER or set
session_replication_role; runtime therefore must never run as the owner (D1).

Revision ID: 0003_phase1b_jobs_guard_update
Revises: 0002_phase1b_grants
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_phase1b_jobs_guard_update"
down_revision: Union[str, None] = "0002_phase1b_grants"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FUNCTION = """
CREATE FUNCTION fn_jobs_guard_update() RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $guard$
DECLARE
    in_api boolean;
    in_manager boolean;
    is_maintenance boolean;
    edge text;
BEGIN
    IF OLD.status IN ('COMPLETED', 'FAILED', 'CANCELLED') THEN
        RAISE EXCEPTION 'job_terminal_immutable'
            USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
    END IF;

    IF ROW(NEW.id, NEW.client_id, NEW.client_role, NEW.listing_id, NEW.worker_id, NEW.requested_gpu_count,
           NEW.duration_seconds, NEW.submitted_at, NEW.enqueue_seq, NEW.idempotency_key, NEW.request_sha256,
           NEW.correlation_id)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.client_id, OLD.client_role, OLD.listing_id, OLD.worker_id, OLD.requested_gpu_count,
           OLD.duration_seconds, OLD.submitted_at, OLD.enqueue_seq, OLD.idempotency_key, OLD.request_sha256,
           OLD.correlation_id) THEN
        RAISE EXCEPTION 'job_identity_immutable'
            USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
    END IF;

    -- Classify the caller before anything is accepted, a no-op UPDATE included: an ambiguous or unknown role is
    -- refused for every UPDATE (schema matrix section 7, caller table).
    WITH RECURSIVE held(oid) AS (
        SELECT r.oid FROM pg_catalog.pg_roles r WHERE r.rolname = current_user
        UNION
        SELECT m.roleid FROM pg_catalog.pg_auth_members m JOIN held ON m.member = held.oid
    )
    SELECT coalesce(bool_or(g.rolname = 'gpm_api_rw'), false),
           coalesce(bool_or(g.rolname = 'gpm_manager_rw'), false)
      INTO in_api, in_manager
      FROM held JOIN pg_catalog.pg_roles g ON g.oid = held.oid;

    IF in_api AND in_manager THEN
        RAISE EXCEPTION 'job_update_role_ambiguous'
            USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
    ELSIF NOT in_api AND NOT in_manager THEN
        SELECT r.rolsuper OR r.oid = d.datdba
          INTO is_maintenance
          FROM pg_catalog.pg_roles r, pg_catalog.pg_database d
         WHERE r.rolname = current_user AND d.datname = current_database();
        IF NOT coalesce(is_maintenance, false) THEN
            RAISE EXCEPTION 'job_update_role_not_permitted'
                USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
        END IF;
    END IF;

    IF NEW.status = OLD.status THEN
        IF NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'job_update_without_transition'
                USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
        END IF;
        RETURN NEW;
    END IF;

    edge = OLD.status || '>' || NEW.status;
    IF edge NOT IN ('QUEUED>RUNNING', 'QUEUED>CANCELLED', 'RUNNING>COMPLETED', 'RUNNING>FAILED') THEN
        RAISE EXCEPTION 'job_illegal_transition'
            USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
    END IF;

    IF in_api AND edge <> 'QUEUED>CANCELLED' THEN
        RAISE EXCEPTION 'job_transition_not_owned_by_api'
            USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
    ELSIF in_manager AND edge NOT IN ('QUEUED>RUNNING', 'RUNNING>COMPLETED', 'RUNNING>FAILED') THEN
        RAISE EXCEPTION 'job_transition_not_owned_by_manager'
            USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_update';
    END IF;

    RETURN NEW;
END;
$guard$
"""


def upgrade() -> None:
    op.execute(FUNCTION)
    # Schema matrix 6.2: trigger functions are not executable by PUBLIC. Firing the trigger needs no EXECUTE.
    op.execute("REVOKE EXECUTE ON FUNCTION fn_jobs_guard_update() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_jobs_guard_update BEFORE UPDATE ON jobs "
        "FOR EACH ROW EXECUTE FUNCTION fn_jobs_guard_update()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_jobs_guard_update ON jobs")
    op.execute("DROP FUNCTION fn_jobs_guard_update()")
