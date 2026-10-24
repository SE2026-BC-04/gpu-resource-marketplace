# Alembic migration boundary

Alembic is configured for the shared Backend API/Manager package. `versions/0001_phase1b_baseline.py` is the hand-written Phase 1B baseline: the ten approved tables from the GPU-002-A schema matrix and the three fixed role codes (`INSERT ... ON CONFLICT DO NOTHING`, safe to rerun). It contains no demo data, grants, triggers or guarded delete; those stay separate proposals until the lead decides them.

Run migrations only against a database you own. The PostgreSQL tests (`backend/tests/test_migration_baseline.py`, `test_schema_constraints.py`) refuse to run unless they are pointed at a disposable cluster that passes the guards in `backend/tests/db_safety.py`; otherwise they are reported `NOT_RUN`.
