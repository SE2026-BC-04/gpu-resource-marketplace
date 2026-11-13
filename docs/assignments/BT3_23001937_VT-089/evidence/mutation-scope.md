# VT-089 authorization mutation

- Correct implementation SHA: `e90627a1913550a5ea9ea224eff70b04ab99455c`.
- Detached mutant commit SHA: `bac2ea4b76ae2d02d0485a8e6fe0769ad193efa5` (not pushed; detached worktree removed after the run).
- Mutation: remove only the `if requested is not expected: raise Forbidden()` guard in `JobsReadService._scope`.
- HTTP test ID/function: role-scope authorization / `test_router_rejects_cross_role_scope` (CLIENT `assigned`, WORKER `mine`, ADMIN `mine`).
- Attempt 1: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py::test_router_rejects_cross_role_scope -q` could not build the local project because the sandbox could not resolve PyPI while preparing a new environment; this was an environment error, not a test result.
- Actual mutation run, using the repository's already installed locked backend environment:

  ```bash
  PYTHONPATH=/tmp/vt089-mutant/backend/src:/tmp/vt089-mutant/backend/tests /home/nguyenducthang/gpu-marketplace-vt089/backend/.venv/bin/python -m pytest backend/tests/test_jobs_foundation.py::test_router_rejects_cross_role_scope -q
  ```

- Actual result: exit `1`, **3 failed**. All three requests returned `200` instead of the required `403`, and each failure points to the HTTP assertion in the named regression test.
- Full output: [`pytest-mutation-scope.log`](pytest-mutation-scope.log); one-guard patch: [`mutation-scope.patch`](mutation-scope.patch).
- The submitted branch remains at the correct implementation SHA and retains the guard. This experiment demonstrates detection of this specific scope-guard mutation only; it does not prove all authorization paths.
