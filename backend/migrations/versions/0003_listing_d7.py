"""Listing-only immutable identity and DB-clock updated_at (CR-GPU-004-D7-01).

Owner approved with conditions: PR #31, issuecomment-6396753378.
Error profile was recorded before DDL at b1e1008 / issuecomment-6500093853.
No table/column/role or D1 grant changes. Re-parent and retest if the accepted
migration head changes before merge; pending D2/D3 are not dependencies.

Revision ID: 0003_listing_d7
Revises: 0002_phase1b_grants
Create Date: 2026-10-29
"""

from alembic import op

revision = "0003_listing_d7"
down_revision = "0002_phase1b_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION public.fn_gpu_listings_guard_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY INVOKER
        SET search_path = pg_catalog
        AS $d7$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.worker_id IS DISTINCT FROM OLD.worker_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION USING
                    ERRCODE = '23514',
                    CONSTRAINT = 'ck_gpu_listings_identity_immutable',
                    SCHEMA = 'public',
                    TABLE = 'gpu_listings',
                    MESSAGE = 'Listing identity is immutable.';
            END IF;
            NEW.updated_at := pg_catalog.clock_timestamp();
            RETURN NEW;
        END;
        $d7$
    """)
    op.execute(
        "REVOKE ALL ON FUNCTION public.fn_gpu_listings_guard_update() FROM PUBLIC"
    )
    op.execute("""
        CREATE TRIGGER trg_gpu_listings_guard_update
        BEFORE UPDATE ON public.gpu_listings
        FOR EACH ROW EXECUTE FUNCTION public.fn_gpu_listings_guard_update()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_gpu_listings_guard_update ON public.gpu_listings")
    op.execute("DROP FUNCTION public.fn_gpu_listings_guard_update()")
