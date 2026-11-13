# BT3 — VT-089 Job Search

**Sinh viên:** Nguyễn Đức Thăng — 23001937
**Nhóm / môn:** SE2026-T23 / BC-04
**Vai trò:** TV5 — GPU-005 Jobs
**Task:** VT-089 — tìm kiếm có lọc, phân trang và thứ tự ổn định
**Trạng thái:** L2 DESIGN APPROVED — implementation review and merge gates remain open
**Branch:** `bt3/23001937-vt089-job-search`
**Baseline:** `origin/main` at `bee832eaf5463df20f6c6815174322871eb6685a`
**API Contract baseline:** v0.10 at `bee832e`; VT-089 v0.11 amendment is in this PR and remains unmerged.
**Decision:** `DEC-VT089-L2-01`, approved by TV1 on 2026-11-13 for implementation in this same PR; TV2 `ACK_WITH_ACTIONS` is for the proposed reader/query direction, not implementation review or merge approval.

> “Tôi chịu trách nhiệm về toàn bộ code, test và nội dung bài làm; tôi đã khai báo việc sử dụng AI.”

## 1. Problem statement

Job list hiện hỗ trợ `scope`, `status`, `limit`, và `cursor`. Người dùng cần tìm Jobs thuộc một Listing cụ thể, tùy chọn kết hợp status, trong khi authorization, keyset order và response hiện hành được giữ nguyên. Đây là phần mở rộng query contract cho `GET /api/v1/jobs`; TV1 đã phê duyệt thiết kế L2 để triển khai atomic trong PR #52, nhưng amendment chưa được merge.

**Thiết kế được phê duyệt:** thêm query parameter tùy chọn `listing_id` canonical lowercase UUIDv4. Chuỗi rỗng, sai định dạng, uppercase, noncanonical, UUID không phải v4 hoặc query key trùng lặp trả `400 INVALID_FILTER`; khi bỏ qua thì không thêm predicate. Ví dụ:

```http
GET /api/v1/jobs?listing_id=22222222-2222-4222-8222-222222222222&status=QUEUED&limit=20
```

Không thêm field vào Job response, không thêm bảng hay dependency. Filter được áp dụng trong SQL cùng predicate visibility/status/cursor và trước `LIMIT`. Thứ tự vẫn `submitted_at DESC, id DESC`.

### Approved design / acceptance criteria

1. `listing_id` và `status` khi cùng có mặt được kết hợp bằng AND; UUID hợp lệ nhưng không có Job nhìn thấy được trả `200` với `items=[]` và `next_cursor=null`.
2. Các trang tuân theo `submitted_at DESC, id DESC`; timestamp bằng nhau vẫn được phân trang bằng Job UUID tie-break, không lặp/mất Job trong fixture bất biến.
3. Request cũ không có `listing_id` giữ nguyên request/response và có thể tiếp tục dùng cursor tạo từ baseline.
4. Thêm filter không nới tập dữ liệu được phép xem: CLIENT vẫn chỉ thấy `client_id` của mình, WORKER chỉ Jobs của Worker đã gán, ADMIN chỉ đọc; cùng điều kiện visibility được thực thi trong SQL trước LIMIT.
5. Filter sai, rỗng, không canonical UUIDv4, hoặc cursor ký cho filter khác bị từ chối bằng `400 INVALID_FILTER` / `400 INVALID_CURSOR` tương ứng và error envelope an toàn; không trả SQL/exception detail.

### Non-functional constraints

- Với workload 120 tác vụ đồng thời được mô tả rõ, p95 phải `<= 3.5s`; không suy ra concurrency thực tế từ số worker cấu hình.
- Patch nhỏ nhất; giữ Python/FastAPI/SQLAlchemy/PostgreSQL và React/Vite hiện có; không thêm dependency hoặc migration nếu chưa có bằng chứng và phê duyệt.
- Không hứa snapshot xuyên nhiều HTTP requests; cursor giữ keyset semantics hiện tại.

## 2. Contract and implementation evidence at baseline

- API Contract §8.2 định nghĩa `scope`, `status`, `limit`, `cursor`, order, limit range, cursor binding và role projections; không có `listing_id` tại baseline (`docs/design/api-contract.md:559-567`).
- Jobs router hiện nhận `scope/status/limit/cursor` (`backend/src/gpu_marketplace/jobs/router.py:166-187`).
- `JobsReadService` đưa scope/status vào `CursorContext`, decode cursor, rồi gọi reader (`backend/src/gpu_marketplace/jobs/service.py:36-80`).
- Cursor context hiện gồm user, role, scope, status (`backend/src/gpu_marketplace/jobs/ports.py:47-53`); codec ký context với canonical JSON/HMAC (`backend/src/gpu_marketplace/jobs/cursor.py:113-129`).
- `PostgresJobReader.list_visible` đưa visibility, status, keyset predicate vào `WHERE`, sau đó `ORDER BY submitted_at DESC, id DESC LIMIT limit+1` (`backend/src/gpu_marketplace/repositories/jobs.py:104-147`).
- DB design đã có `jobs.listing_id`; ORM có partial FIFO index cho QUEUED và client history index, nhưng chưa thấy index tổng quát cho listing + history order (`docs/design/database-design.md:286-305`; `backend/src/gpu_marketplace/domain/jobs.py:74-78`). Index mới không được thêm nếu chưa có benchmark/EXPLAIN và owner review.
- Frontend query type hiện chỉ gồm scope/status/limit/cursor (`frontend/src/api/jobs.ts:37-42`); UI/job API behavior cần được khảo sát để quyết định phạm vi filter control nhỏ nhất.

## 3. Initial plan — written before application changes

### Intended smallest file set

**Application/test candidate (chưa tạo trước khi design gate được giải quyết):**

- `backend/src/gpu_marketplace/jobs/router.py`
- `backend/src/gpu_marketplace/jobs/service.py`
- `backend/src/gpu_marketplace/jobs/ports.py`
- `backend/src/gpu_marketplace/jobs/cursor.py`
- `backend/src/gpu_marketplace/repositories/jobs.py`
- `backend/tests/test_jobs_foundation.py`
- `backend/tests/test_jobs_read_adapter_postgres.py`
- `frontend/src/api/jobs.ts` và tests
- `frontend/src/ui/jobs/JobsPage.tsx` và tests, only if the client/UI needs the filter for acceptance.
- Playwright E2E chỉ nếu runtime stack có thể chạy an toàn.

**Normative/design evidence:** TV1 decision `DEC-VT089-L2-01` and the approved VT-089 amendment in `docs/design/api-contract.md` within PR #52; both remain unmerged. Do not change `api/app.py`, Auth, Listings, migration, Database Design or unrelated modules.

### Test-first sequence

1. Lưu spec/plan và bản ghi quyết định/blocker trước patch.
2. Chạy baseline Jobs unit/API tests và lưu command, exit code, log, SHA.
3. Sau normative contract update and recorded DEC, create HTTP tests using the existing public endpoint; prove RED because the route does not apply listing filter (not due to import/fixture/environment failure).
4. Capture response/cursor fixture baseline từ codec ở SHA trên với fixed public test key; không dựng “legacy cursor” bằng code đã sửa.
5. Implement một vertical slice nhỏ: router → service/port → SQL reader, rồi filter frontend nếu acceptance/E2E cần.
6. Review diff/query/authorization/cursor compatibility, chạy GREEN, regression, static checks.
7. Thực hiện authorization mutation trên detached worktree/temporary commit riêng; không push mutant.
8. Coverage/flaky review; PostgreSQL disposable-only integration; load harness và đo API+PostgreSQL nếu môi trường an toàn.
9. Hoàn thiện traceability, AI usage log, báo cáo/PDF, CI evidence.

### Plan review — choices rejected or deferred with repository evidence

1. **Bác bỏ filter sau LIMIT.** Reader đang lấy `limit+1` sau SQL `WHERE` (`repositories/jobs.py:124-147`); lọc ở Python sau LIMIT sẽ trả trang thiếu, có thể bỏ kết quả ở trang kế tiếp và làm cursor sai. Filter phải là bound SQL predicate trước LIMIT.
2. **Giữ keyset; không đổi sang OFFSET.** API contract đã yêu cầu `submitted_at DESC, id DESC` và cursor context-bound (§8.2); reader đang dùng tuple tie-break `(submitted_at,id)` (`repositories/jobs.py:117-130`). OFFSET sẽ thay đổi cơ chế đã duyệt và dễ dịch vị trí khi collection thay đổi giữa request.
3. **Không thêm bảng/migration/dependency ở bước đầu.** `jobs.listing_id` đã tồn tại; bộ lọc có thể biểu diễn bằng điều kiện parameterized. Chưa có đo đạc chứng minh index mới bắt buộc; index chỉ được đề xuất riêng nếu EXPLAIN/load evidence cho thấy thiếu.
4. **Không đổi response DTO.** Search là điều kiện chọn collection; các field response/role projections đã định nghĩa ở API Contract §8.2. Không có yêu cầu cần thêm trường vào mỗi Job.
5. **Cursor cũ là compatibility gate.** Context baseline có các keys user/role/scope/status (`cursor.py:113-129`). Khi filter vắng mặt, canonical bytes/context tag phải giữ nguyên để cursor baseline còn decode được; chỉ đưa `listing_id` vào signed context khi filter được cung cấp. Filter khác phải làm context tag khác.

## 4. Risk-based test strategy and initial case matrix

Unit tests tập trung strict query validation, context binding, default behavior và service/port delegation. HTTP tests xác nhận response/error/auth qua router thật với dependencies thật ở mức có sẵn. PostgreSQL tests kiểm tra SQL filter trước LIMIT, visibility và tie-break trên database disposable. E2E chỉ xác minh user filter → query → rendered page nếu runtime runbook hoạt động; không lặp toàn bộ auth/submit/cancel E2E nếu contract/implementation đó không đổi. Không bỏ PostgreSQL query test nếu chỉ unit mocks xanh.

| ID | AC/risk | Level | Preconditions/input | Expected result | Priority |
|---|---|---|---|---|---|
| VT089-01 | AC3/client compatibility | HTTP | GET cũ, không listing_id, cursor baseline | status/body shape/order như trước; cursor baseline dùng được | P1 |
| VT089-02 | AC1/filter correctness | API+PG | listing L1 có Jobs; `listing_id=L1` | đúng chính xác IDs thuộc L1 và caller-visible | P1 |
| VT089-03 | AC1/AND | API+PG | L1 có QUEUED và RUNNING; listing+QUEUED | chỉ QUEUED thuộc L1 | P1 |
| VT089-04 | AC1/empty | HTTP | hợp lệ UUIDv4 không có visible Job | 200, empty collection, null cursor | P2 |
| VT089-05 | AC5/validation | HTTP | listing_id empty, UUIDv1, uppercase, noncanonical | 400 INVALID_FILTER; no internal detail | P1 |
| VT089-21 | AC5/fail closed | HTTP | repeated listing_id keys, including identical values | 400 INVALID_FILTER; reader not called | P1 |
| VT089-06 | BVA limit lower invalid | HTTP | limit 0 | 422 per existing range behavior | P1 |
| VT089-07 | BVA lower boundary | HTTP | limit 1 | accepted; at most one item | P1 |
| VT089-08 | BVA near lower | HTTP | limit 2 | accepted; at most two items | P2 |
| VT089-09 | BVA near upper | HTTP | limit 99 | accepted | P2 |
| VT089-10 | BVA max boundary | HTTP | limit 100 | accepted; at most 100 items | P1 |
| VT089-11 | BVA upper invalid | HTTP | limit 101 | 422; reader not called | P1 |
| VT089-12 | Pagination boundary | API+PG | 19/20/21 visible rows, limit 20 | 19 one page; 20 one page; 21 two pages (20+1) | P1 |
| VT089-13 | Stable tie order | API+PG | fixed timestamp ties, fixed UUIDs, multiple pages | exact `submitted_at DESC,id DESC`, no duplicate/missing IDs on unchanged fixture | P1 |
| VT089-14 | Cursor compatibility | Unit+HTTP | token generated by baseline codec, no new filter | accepts and continues baseline query | P1 |
| VT089-15 | Cursor binding | Unit+HTTP | token for L1 reused with L2 | 400 INVALID_CURSOR; reader not called | P1 |
| VT089-16 | Authorization mutation | HTTP | CLIENT requests scope=all with listing filter | 403 FORBIDDEN, no unauthorized reader query | P1 |
| VT089-17 | Auth boundary | HTTP | missing/invalid bearer | 401 UNAUTHENTICATED, reader not called | P1 |
| VT089-18 | Failure path/client compatibility | HTTP+PG | read DB unavailable on filtered query | 503 DEPENDENCY_UNAVAILABLE safe envelope; no SQL detail | P1 |
| VT089-19 | UI stale response | Frontend | change filter while prior page request is pending | history/cursor reset; old response cannot replace new filter result | P2 |
| VT089-20 | Filter without status / with status | API+PG | listing filter alone; listing+status | optional status behavior preserved; conjunction correct | P1 |
| VT089-22 | AC4/filter before LIMIT | PostgreSQL | newest page rows do not match; matching rows follow them | matching Jobs are returned in first filtered page | P1 |

**BVA rationale:** `limit` has explicit inclusive range `[1,100]`, so test invalid immediately below/above (`0`,`101`), both endpoints (`1`,`100`), and interior controls (`2`,`99`). Page-count data uses 19/20/21 around page size 20 to exercise below/equal/one-over. Include at least two negative cases (`VT089-05`, `VT089-16`) and failure-path (`VT089-18`) tied to old-client/API safety risk.

## 5. Decision and change record

### DEC-VT089-L2-01

- **Requester:** Nguyễn Đức Thăng (23001937), TV5; **decision date:** 2026-11-13 (UTC); **approver:** @thangSy221105 (TV1/team lead).
- **Decision evidence:** [TV1 L2 decision](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/52#issuecomment-6857910079), reviewed proposal HEAD `ee2fe6fe664552240f70cfb2802277640f2831d1`.
- **Decision:** scoped optional `listing_id` API query extension is APPROVED for implementation. Atomic normative documentation plus tests/implementation is approved in this same PR #52. This is not implementation acceptance, approval to merge, or deployment authorization.
- **No-change alternative:** retain current §8.2 query with `scope/status/limit/cursor`; no Listing filter. This preserves current API but does not satisfy VT-089 search request.
- **Selected change:** add optional canonical lowercase UUIDv4 `listing_id` to GET `/api/v1/jobs` only. Empty, malformed, uppercase, noncanonical, non-v4, or duplicate query keys return `400 INVALID_FILTER`. Valid UUID with zero caller-visible Jobs returns `200`, `items=[]`, `next_cursor=null`; do not look up Listing or expose existence. Filter ANDs with visibility/status/keyset in SQL before LIMIT; response DTO and order stay unchanged.
- **Impact:** CONFIRMED_IMPACT to GPU-005 API and TV2-owned `JobReader`/PostgreSQL list query. TV2 recorded `ACK_WITH_ACTIONS` for the reader/query design direction ([TV2 review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/52#pullrequestreview-5894585707)); the SQL implementation still requires review at its exact HEAD. No migration/index/dependency or Listing API change is approved. TV3 auth semantics remain unchanged; existing role guards must still pass.
- **Compatibility:** when filter is absent, old callers, request/response shape, cursor canonical context bytes/HMAC, SQL statement and params remain baseline-identical; no `listing_id: null` context/param. When present, canonical ID is included in cursor context, so changing/removing filter rejects cursor with `400 INVALID_CURSOR`. Keyset order is `submitted_at DESC, id DESC`.
- **Rollback:** revert the feature and normative amendment together in this PR; no persistent schema/data change is made. If index/performance evidence suggests a schema change, stop and request a separate TV2-owned L2 decision/PR.
- **Acceptance IDs:** `VT089-01..22`, with API and PostgreSQL subcases listed in the matrix. RED must be committed before application code.

### TV2 ACK_WITH_ACTIONS — implementation action tracking

1. Preserve optional keyword-only `listing_id: UUID | None = None` after existing parameters on the protocol and adapter; existing callers and fakes remain valid.
2. Only for non-None, append static `j.listing_id = :listing_id` and bind native UUID. With None, SQL and params must exactly match baseline; no Listing join/read.
3. Keep SQL visibility predicate, status, cursor, order and runtime role checks intact. Do not touch `get_visible`, cancel code, grants or migrations.
4. Cover filter-before-LIMIT, CLIENT/WORKER/ADMIN visibility, unknown/non-visible equivalence, combined status and tied timestamp cursor pages on disposable PostgreSQL. TV2’s review is design-only until the implementation HEAD is reviewed.
5. TV5 will provide the exact implementation HEAD to TV2 for review; no implementation ACK is presumed.

**TV4:** Listing ownership semantics are unchanged (filter is on existing immutable `jobs.listing_id`); cross-phase review should verify this premise. No ACK is inferred. **No owner ACK beyond the recorded TV2 design ACK is claimed.**

## 6. Evidence status

- Specification/plan: drafted on branch before application patch.
- Baseline SHA: `bee832eaf5463df20f6c6815174322871eb6685a` (`origin/main`); branch created directly from this commit.
- Runtime: Python 3.12.3, uv 0.13.5, Node 22.22.2, npm 10.9.7.
- Baseline Jobs command: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py backend/tests/test_jobs_auth_integration.py backend/tests/test_api_jobs_mount.py -q` — **PASS: 101 passed, 3 skipped**, exit 0; skips are the three real PostgreSQL reader tests, which require an opted-in disposable cluster. One upstream Starlette/httpx deprecation warning.
- Baseline cursor fixture (generated by unmodified codec at baseline SHA; key is public test-only): context `user_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`, role `CLIENT`, scope `mine`, status `null`; position `submitted_at=2026-10-24T08:30:00.123456Z`, `job_id=33333333-3333-4333-8333-333333333333`; key bytes `VT089-PUBLIC-TEST-KEY-NOT-FOR-PRODUCTION-0001`; token `eyJjb250ZXh0X3RhZyI6Ijg4ZDdiNzUwNDhjMThlY2UwZGNjNWNkYWZhY2UxOTUyNjBmOGRmNTY3MDY0ZDY3NTk2ODE1YzY5YTlhZDhmMzYiLCJqb2JfaWQiOiIzMzMzMzMzMy0zMzMzLTQzMzMtODMzMy0zMzMzMzMzMzMzMzMiLCJzdWJtaXR0ZWRfYXQiOiIyMDI2LTEwLTI0VDA4OjMwOjAwLjEyMzQ1NloiLCJ2IjoxfQ.XSVEDhc9EBrt7iWJZWsK_3v6-FEXxbZ6ut5QVfDKEBA`.
- Cursor reproduction command (run from repository root at baseline SHA):

  ```bash
  uv run --project backend python -c 'from datetime import datetime, timezone; from uuid import UUID; from gpu_marketplace.jobs.cursor import HmacCursorCodec; from gpu_marketplace.jobs.models import JobRole; from gpu_marketplace.jobs.ports import CursorContext, CursorPosition; key=b"VT089-PUBLIC-TEST-KEY-NOT-FOR-PRODUCTION-0001"; context=CursorContext(user_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),role=JobRole.CLIENT,scope="mine",status=None); position=CursorPosition(submitted_at=datetime(2026,10,24,8,30,0,123456,tzinfo=timezone.utc),job_id=UUID("33333333-3333-4333-8333-333333333333")); print(HmacCursorCodec(key).encode(position,context=context))'
  ```
- Frontend dependencies: `npm --prefix frontend ci` — PASS, 117 packages installed from `package-lock.json`, 0 vulnerabilities; lockfile unchanged.
- Frontend baseline: `npm --prefix frontend test -- --reporter=dot` — **PASS: 10 files, 158 tests**, exit 0; `npm --prefix frontend run typecheck` — PASS, exit 0; `npm --prefix frontend run build` — PASS, Vite production build completed, exit 0.
- Normative decision/contract commit: `6eba257` (`docs(api): record approved VT-089 Jobs filter`); application code was unchanged in that commit.
- RED test commit: `74b5c08` (`test(jobs): capture VT-089 listing filter RED`), based on the pre-feature implementation. Command `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py -k vt089_list_http -q` exited `1` as expected: **7 failed, 88 deselected**. The matching-filter test observed the nonmatching Job in the HTTP collection; all six invalid/duplicate query cases returned `200` instead of `400 INVALID_FILTER`. Full sanitized output: [`pytest-red-01.log`](evidence/pytest-red-01.log); run record: [`red-run-01.md`](evidence/red-run-01.md).
- Extended RED run: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py -k vt089 -q` — exit `1` as expected, **9 failed, 2 passed, 91 deselected**. Failures cover ignored filter/invalid query inputs and the not-yet-added cursor/adapter interface; controls confirm the legacy cursor and baseline unfiltered SQL/params. See [`red-run-02.md`](evidence/red-run-02.md) and [`pytest-red-02.log`](evidence/pytest-red-02.log).
- Expanded RED run: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py -k vt089 -q` — exit `1`, **10 failed, 2 passed, 1 skipped, 91 deselected**. The single PostgreSQL test skipped because disposable-cluster opt-in is absent. See [`red-run-03.md`](evidence/red-run-03.md).
- Implementation: commit `e90627a1913550a5ea9ea224eff70b04ab99455c` (`feat(jobs): filter job lists by Listing`); modified the Jobs route/service/port/cursor/reader, Jobs API/UI, focused backend/frontend tests, runtime E2E scenario, and this assignment's load harness. No migration, dependency, Auth, Listings service, or shared app registration changed.
- Focused GREEN: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py -q` — **109 passed, 5 skipped**, exit 0. The skips are all real PostgreSQL scenarios gated on disposable DB credentials; the result proves the unit/recording-session suite only. Full output: [`pytest-green-focused.log`](evidence/pytest-green-focused.log).
- Frontend GREEN: `npm --prefix frontend test -- --reporter=dot` — **10 files, 160 passed**; `npm --prefix frontend run typecheck` and `npm --prefix frontend run build` — **PASS**. Production build completed. These are local feature-branch results.
- Repeatability: the focused Jobs command was repeated twice more, each **109 passed, 5 skipped**; see [`flaky-review.md`](evidence/flaky-review.md) and the two repeat logs. This is a small repeat sample, not proof of absence of flakiness.
- Runtime HTTP/PostgreSQL E2E: **SKIPPED / NOT_RUN** (1 scenario) because disposable-cluster opt-in is absent; see [`pytest-runtime-e2e.log`](evidence/pytest-runtime-e2e.log). Docker access is denied by the local daemon socket permission, so no disposable cluster was created.
- Mutation: **KILLED** for one targeted authorization guard mutation. Removing the role/scope guard caused 3 cross-role requests to return 200 instead of 403; details and exact mutant evidence: [`mutation-scope.md`](evidence/mutation-scope.md), [`mutation-scope.patch`](evidence/mutation-scope.patch), [`pytest-mutation-scope.log`](evidence/pytest-mutation-scope.log). This does not establish coverage of every mutation.
- Coverage: quantitative line/branch coverage **NOT_RUN**; neither `coverage.py` nor `pytest-cov` is present in the pinned dev environment. Risk-based coverage assessment is in [`evidence/coverage-risk-review.md`](evidence/coverage-risk-review.md); no dependency was added.
- 120-VU performance acceptance: **NOT_RUN**. The harness `--help` was exercised successfully, but no API+PostgreSQL runtime or representative dataset was available. p50/p95/p99, throughput, observed concurrency and error rate therefore have no measured values; p95 `<=3.5s` is **not established**.
- Lint: **NOT_RUN**; `ruff` is unavailable in the pinned dev group. Python `compileall` and `git diff --check` were run locally.
- Remote CI currently attached to GitHub PR head `74b5c084248cbf9cc1689f9e7cf353800da97cd1`: run [43469022825](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/43469022825) is RED evidence, with **7 feature failures and 1223 passed tests**. The captured failure includes duplicate `listing_id` returning 200 instead of the new 400 assertion. That remote SHA predates implementation commit `e90627a`; it is expected pre-GREEN evidence, not CI of implementation.
- Full backend regression: **BLOCKED/INCOMPLETE** in the earlier local attempt at an unrelated TestClient/Auth integration deadlock. Exact-head CI for local SHA `e90627a` (and later evidence SHA) is unavailable because those commits have not reached GitHub; do not infer full-suite success from focused tests.
- PDF/DOCX: **BLOCKED** locally; no Pandoc, LibreOffice, browser PDF renderer, `python-docx`, ReportLab or WeasyPrint is installed. Editable Markdown sources and reflection are supplied; the required rendered PDF (<=8 A4 pages) and DOCX remain outstanding rather than fabricated.
- DEC-VT089-L2-01: APPROVED for the scoped design and atomic same-PR workflow; implementation review/merge approval NOT PROVIDED.
- TV2: ACK_WITH_ACTIONS for reader/query design at proposal HEAD; implementation review pending exact implementation SHA `e90627a1913550a5ea9ea224eff70b04ab99455c`.
- TV4 ACK: NOT PROVIDED. TV3 ACK: not requested/claimed because auth semantics do not change.
- Final delivery remains Draft/HOLD: disposable PostgreSQL, exact-head TV2 SQL review, TV4 cross-phase review, exact-head CI, quantitative coverage where tooling becomes available, real 120-VU run, rendered PDF, and two independent human L2 approvals remain open.

## 7. AI use log

- Tool: Codex coding agent; the exact model build identifier is unavailable. Prompt source: user-provided BT3 VT-089 assignment and subsequent TV1/TV2 decision evidence.
- AI-assisted work used: repository survey, decision/change-record draft, API contract wording, test matrix, test/code suggestions, load-harness draft, evidence summaries and this report. The student remains responsible for the submitted code and claims.
- Verification examples: (1) a cursor regression test initially used a test key with an extra hyphen, which did not match the published fixed key; the failing signature check exposed this and the test was corrected against the exact baseline fixture. (2) a proposed PostgreSQL fixture initially had a role/client identity mismatch; review caught the fixture inconsistency and it was corrected before final evidence. These are examples of generated work requiring independent checking, not claimed production defects.
- The authorization mutation was deliberately run in a detached temporary worktree. Its three failing assertions were inspected; the mutant was not pushed, and the submitted branch retains the original guard.
- Evidence is separated into baseline, RED, local GREEN, skipped PostgreSQL/E2E, mutation and unrun performance. No AI output is treated as owner ACK, runtime evidence, or human approval.
- Student reflection: [`reflection.md`](reflection.md). A required reviewable PDF/DOCX has not been rendered because this environment lacks a renderer; do not treat Markdown as satisfying that artifact requirement.
