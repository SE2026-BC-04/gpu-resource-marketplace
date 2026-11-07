# BT3 — Review AI plan against the real repository (baseline `1d8b1b2`)

Plan: `BT3_ai_plan_raw.md`. Each point below is checked against a file in the repository, not against the AI's statement.

## Rejected / corrected (with evidence)

| # | AI plan says | Evidence in the real repo | Decision |
|---|---|---|---|
| R1 | Write the **whole batch in one transaction** (`INSERT ... ON CONFLICT DO NOTHING RETURNING`), and if commit fails then `saved_count == 0` (property P8). | The change request is "a bad record must not lose valid records". With one batch transaction, one unexpected DB error (or a lost connection at commit) drops every valid record of the batch. The AI's own P8 encodes exactly that loss. The schema has several independent failure points per record (`uq_users_login_name`, `fk_user_roles_role_code`, `ck_users_status`, `domain/identity.py:23-55`). | **Rejected.** One transaction **per record** (`users` + its single `user_roles` row). Only a committed record is `created`. A failure affects only that record (and, by decision 2, stops the batch on `DB_UNAVAILABLE`). |
| R2 | A PostgreSQL `AccountWriter` adapter in the persistence layer, implicitly usable from the application. | The API runtime group has **SELECT only** on `users` and `user_roles` (`0002_phase1b_grants.py:54-60`); INSERT is granted only on `gpu_listings` and `jobs` (`:65-80`). The grant migration fails closed if a role exceeds this matrix (`:13-14`, `test_grants.py`). Also `0 public registration` (P1C-AC-06). | **Corrected.** No adapter in `repositories/` and no use of the runtime role. The PostgreSQL writer lives in the **test harness** and uses the vetted owner connection of the disposable cluster. The import function only depends on a small port. |
| R3 | Change `identity/ports.py` (add `AccountWriter`, rewrite its docstring). | `ports.py:1` states GPU-003 never writes accounts; it is a reviewed contract file. The risk of this VT is "a small change breaks an unrelated old behaviour". | **Rejected.** The port is defined in the new module `identity/account_import.py`; `ports.py`, `normalization.py`, `passwords.py`, `service.py`, `router.py` are not modified (AC-5). |
| R4 | Integration tests under `backend/tests/integration/`, maybe testcontainers / docker-compose (assumption 3). | The repo keeps tests flat in `backend/tests/` and provides guarded disposable-cluster fixtures (`conftest.py`, `db_safety.py`: `db_engine`, `migrated_database_with_teardown`). | **Corrected.** Use the existing fixtures; no new infrastructure. |
| R5 | Assumption 2: "is there a `roles` seed?" | `0001_phase1b_baseline.py:32-36,286` seeds `roles` (CLIENT/WORKER/ADMIN). | **Answered.** No seed needed. |
| R6 | "`hypothesis` maybe already present." | `backend/pyproject.toml` dev group has only `httpx`, `pytest`, `pyyaml`. | **Corrected.** Hypothesis must be added as a **dev-only** dependency (decision recorded: NEED/FIT/RISK/EXIT, Lecture 06 slide 20). |

## Accepted (useful, kept)

- Risk that 40 concurrent tasks miss p95 1.5 s because of scrypt (N=2^15, r=8, p=3) and `max_concurrent=4`, 2 s wait (`passwords.py`). Matches our own measurement (~330 ms/hash locally).
- `PasswordHashingBusy` is an infrastructure failure, not a data error → `failed`, never `created`.
- Surrogates in a password make `hash_password` raise `UnicodeEncodeError` → validate before hashing.
- `repr=False` on password / hash fields; no raw input in errors or logs.
- Several properties (partition of indexes, fixed-point of normalisation, order of duplicates).

## Decisions taken (spec §6)
First duplicate wins; stop on DB unavailable; 1 task = 1 record for the load check; keep a supplied `id` if it is a valid UUID.
