"""Phase 1B guarded delete ``trg_jobs_guard_delete`` (decision D3, schema matrix section 8).

Second layer behind the grants: no runtime role holds DELETE or TRUNCATE on ``jobs`` (D1), and this
row-level trigger refuses, for every caller including the owner, the deletion of a Job that is not
terminal, has no ``terminal_at``, or became terminal less than 23 x 24 elapsed hours ago (NFR BL-02). The
cutoff is half-open: deletion is allowed from ``terminal_at + interval '552 hours'`` onwards, measured with
``clock_timestamp()`` (D6). It is written in hours, not ``'23 days'``: adding days to a ``timestamptz`` follows the
session time zone, so across a daylight saving change the window would be one hour short or long.
The cascade to ``simulation_references`` only happens when the trigger lets the row go.

The OPEN Dispute condition cannot exist yet because Phase 1B has no ``disputes`` table; a Phase 3
revision extends this function (``DBP-09`` stays BLOCKED until then).

A rejection is SQLSTATE 23000 with CONSTRAINT set to the trigger name and ``job_delete_not_eligible``
as the message (D10). TRUNCATE does not fire row-level DELETE triggers; only the owner may use it,
on test databases (schema matrix section 9).

The trigger function is not executable by PUBLIC (schema matrix 6.2); firing a trigger needs no EXECUTE.

Revision ID: 0004_phase1b_jobs_guard_delete
Revises: 0003_phase1b_jobs_guard_update
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004_phase1b_jobs_guard_delete"
down_revision: Union[str, None] = "0003_phase1b_jobs_guard_update"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FUNCTION = """
CREATE FUNCTION fn_jobs_guard_delete() RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $guard$
BEGIN
    IF OLD.status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')
       OR OLD.terminal_at IS NULL
       OR clock_timestamp() < OLD.terminal_at + interval '552 hours' THEN
        RAISE EXCEPTION 'job_delete_not_eligible'
            USING ERRCODE = 'integrity_constraint_violation', CONSTRAINT = 'trg_jobs_guard_delete';
    END IF;
    RETURN OLD;
END;
$guard$
"""


def upgrade() -> None:
    op.execute(FUNCTION)
    # Schema matrix 6.2: trigger functions are not executable by PUBLIC. Firing the trigger needs no EXECUTE.
    op.execute("REVOKE EXECUTE ON FUNCTION fn_jobs_guard_delete() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_jobs_guard_delete BEFORE DELETE ON jobs "
        "FOR EACH ROW EXECUTE FUNCTION fn_jobs_guard_delete()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_jobs_guard_delete ON jobs")
    op.execute("DROP FUNCTION fn_jobs_guard_delete()")
