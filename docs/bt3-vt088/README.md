# BT3 VT-088 — Bulk account import (individual coursework)

> Coursework experiment by Nông Gia Khánh (23001892). **Not** the project's provisioning tool and **not for merge** without team review. Account provisioning belongs to GPU-002 + GPU-003 and is not designed yet.

> **AI assistance disclosure:** the implementation plan was produced by Claude Code in an isolated session that saw only the identity module; code, tests, harness and documentation were written with Claude Code and reviewed against the repository. Details: AI Usage Log in the report and `evidence/ai_plan_*`.

**Change request:** import accounts in bulk; an invalid record must never lose a valid record.
**Invariant:** a record is reported `created` if and only if its account was committed.
**Baseline:** `main` @ `1d8b1b2`.

## What is in this branch

| File | Purpose |
|---|---|
| `backend/src/gpu_marketplace/identity/account_import.py` | `import_accounts(records, writer, hasher) -> ImportReport` and the `AccountWriter` port. Pure logic, no HTTP route. |
| `backend/tests/test_bt3_account_import.py` | Unit tests (TC01–TC11) and Hypothesis property tests (P1–P6). No database. |
| `backend/tests/test_bt3_account_import_postgres.py` | Integration tests IT01–IT05 on real PostgreSQL. |
| `backend/tests/bt3_account_writer.py` | Test harness: PostgreSQL `AccountWriter` (owner connection, one transaction per account). |
| `backend/tests/bench_bt3_import_load.py` | Load check: 40 concurrent tasks, p95 target 1.5 s. Not collected by the normal suite. |

Existing identity files (`normalization.py`, `passwords.py`, `ports.py`, `service.py`, `router.py`) are unchanged.

## How to run

Prerequisites: Python via `uv`, and for the PostgreSQL tests a **disposable**, safety-marked test cluster (see `backend/tests/db_safety.py`). The PostgreSQL tests are skipped without it.

```bash
# Unit + property tests (no database)
uv run --project backend --locked --group dev pytest backend/tests/test_bt3_account_import.py

# Integration tests (needs GPU_MARKETPLACE_TEST_DATABASE_URL, GPU_MARKETPLACE_TEST_CLUSTER_TOKEN,
# GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS=1 for the disposable cluster)
uv run --project backend --locked --group dev pytest backend/tests/test_bt3_account_import_postgres.py

# Coverage of the new module (line + branch)
uv run --project backend --locked --group dev pytest backend/tests/test_bt3_account_import.py \
  backend/tests/test_bt3_account_import_postgres.py \
  --cov=gpu_marketplace.identity.account_import --cov-branch --cov-report=term-missing

# Reproduce a property-test run
uv run --project backend --locked --group dev pytest backend/tests/test_bt3_account_import.py --hypothesis-seed=42

# Load check (explicit path; prints BT3_LOAD_RESULT JSON)
uv run --project backend --locked --group dev pytest backend/tests/bench_bt3_import_load.py -s

# Regression (AC-5): the whole backend suite
uv run --project backend --locked --group dev pytest backend/tests tests
```

## Evidence

`docs/bt3-vt088/evidence/` holds the raw outputs of the local runs (disposable PostgreSQL 16.15 cluster, Windows): `run1` red before the patch, `run2` green, `run3` full regression, `run4`/`run5` mutations, `run6`/`run7` coverage, `run8`/`run9` flaky checks, `run10` + `load_result.json` load check, `run11` static check (ruff), and the AI plan (`ai_plan_raw.md`, `ai_plan_run.json`) with its review (`ai_plan_review.md`).

## Mutation experiment

The required deliberate bug ("return success although persistence failed") lives only on local temporary branches, never on this branch:

- `bt3/tmp-mutation-M1`: a writer exception other than name-taken / store-unavailable is reported as `created`. Killed by TC06, P3 and IT03.
- `bt3/tmp-mutation-M2`: every writer exception is ignored and reported as `created`. Killed by 9 tests.
