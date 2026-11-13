# BT3 — VT-089 Job Search

**Sinh viên:** Nguyễn Đức Thăng — 23001937
**Nhóm / môn:** SE2026-T23 / BC-04
**Vai trò:** TV5 — GPU-005 Jobs
**Task:** VT-089 — tìm kiếm có lọc, phân trang và thứ tự ổn định
**Trạng thái:** SPEC/PLAN DRAFT — contract extension PROPOSED, chưa được nhóm phê duyệt
**Branch:** `bt3/23001937-vt089-job-search`
**Baseline:** `origin/main` at `bee832eaf5463df20f6c6815174322871eb6685a`
**API Contract baseline:** v0.10, `APPROVED_DESIGN`; test/implementation evidence không được suy ra từ tài liệu thiết kế.

> “Tôi chịu trách nhiệm về toàn bộ code, test và nội dung bài làm; tôi đã khai báo việc sử dụng AI.”

## 1. Problem statement

Job list hiện hỗ trợ `scope`, `status`, `limit`, và `cursor`. Người dùng cần tìm Jobs thuộc một Listing cụ thể, tùy chọn kết hợp status, trong khi authorization, keyset order và response hiện hành được giữ nguyên. Đây là đề xuất mở rộng query contract cho `GET /api/v1/jobs`, không phải contract đã được owner chấp thuận.

**Đề xuất:** thêm query parameter tùy chọn `listing_id` canonical lowercase UUIDv4. Khi được cung cấp, chuỗi rỗng, UUID sai định dạng, uppercase hoặc UUID không phải v4 trả `400 INVALID_FILTER`, giống nhóm lỗi của query filters hiện có; khi bỏ qua thì không thêm predicate. Ví dụ:

```http
GET /api/v1/jobs?listing_id=22222222-2222-4222-8222-222222222222&status=QUEUED&limit=20
```

Không thêm field vào Job response, không thêm bảng hay dependency. Filter được áp dụng trong SQL cùng predicate visibility/status/cursor và trước `LIMIT`. Thứ tự vẫn `submitted_at DESC, id DESC`.

### Acceptance criteria

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
- `frontend/src/ui/jobs/JobsPage.tsx` và tests
- Playwright E2E chỉ nếu runtime stack có thể chạy an toàn.

**Test/design evidence:** thư mục này. Không sửa `api/app.py`, Auth, Listings, migration, Database Design hoặc API Contract đã duyệt trước approval.

### Test-first sequence

1. Lưu spec/plan và bản ghi quyết định/blocker trước patch.
2. Chạy baseline Jobs unit/API tests và lưu command, exit code, log, SHA.
3. Sau khi có approval/design gate, tạo test HTTP dùng endpoint public hiện hữu; chứng minh RED cụ thể vì route chưa áp dụng listing filter (không chấp nhận import/fixture/environment failure là RED).
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
| VT089-05 | AC5/validation | HTTP | listing_id empty, UUIDv1, uppercase, noncanonical | stable validation error; no reader call if validation precedes read | P1 |
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

**BVA rationale:** `limit` has explicit inclusive range `[1,100]`, so test invalid immediately below/above (`0`,`101`), both endpoints (`1`,`100`), and interior controls (`2`,`99`). Page-count data uses 19/20/21 around page size 20 to exercise below/equal/one-over. Include at least two negative cases (`VT089-05`, `VT089-16`) and failure-path (`VT089-18`) tied to old-client/API safety risk.

## 5. Design/change-control gate

Adding `listing_id` changes the public API query contract and `CursorContext`/`JobReader` interface. This is proposed L2. `docs/development/change-control.md` §1 classifies API query-contract changes as L2; §§2–3 require a traceable change record and team-lead decision before implementation. This document is only a proposal, not an approval record. TV2's PostgreSQL reader/query interface is a confirmed ownership boundary; cross-phase acknowledgements have not been obtained. No application patch or executable RED test for the new contract is authorized until the decision/design review gate is satisfied.

**Approval needed:** use this Draft PR as the linked design-change record with problem, baseline, alternatives, impact, backward compatibility, acceptance and rollback; team leader records `APPROVED`/`REJECTED`/`DEFERRED` before implementation. TV2 must review its reader/index impact. TV4 should confirm Listing ID ownership semantics; TV3 auth policy is unchanged but role-scope guard must remain covered. This proposal does not mark any ACK.

## 6. Evidence status

- Specification/plan: drafted on branch before application patch.
- Baseline SHA: `bee832eaf5463df20f6c6815174322871eb6685a` (`origin/main`); branch created directly from this commit.
- Runtime: Python 3.12.3, uv 0.13.5, Node 22.22.2, npm 10.9.7.
- Baseline Jobs command: `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_foundation.py backend/tests/test_jobs_read_adapter_postgres.py backend/tests/test_jobs_auth_integration.py backend/tests/test_api_jobs_mount.py -q` — **PASS: 101 passed, 3 skipped**, exit 0; skips are the three real PostgreSQL reader tests, which require an opted-in disposable cluster. One upstream Starlette/httpx deprecation warning.
- Baseline cursor fixture (generated by unmodified codec at baseline SHA; key is public test-only): context `user_id=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa`, role `CLIENT`, scope `mine`, status `null`; position `submitted_at=2026-10-24T08:30:00.123456Z`, `job_id=33333333-3333-4333-8333-333333333333`; key bytes `VT089-PUBLIC-TEST-KEY-NOT-FOR-PRODUCTION-0001`; token `eyJjb250ZXh0X3RhZyI6Ijg4ZDdiNzUwNDhjMThlY2UwZGNjNWNkYWZhY2UxOTUyNjBmOGRmNTY3MDY0ZDY3NTk2ODE1YzY5YTlhZDhmMzYiLCJqb2JfaWQiOiIzMzMzMzMzMy0zMzMzLTQzMzMtODMzMy0zMzMzMzMzMzMzMzMiLCJzdWJtaXR0ZWRfYXQiOiIyMDI2LTEwLTI0VDA4OjMwOjAwLjEyMzQ1NloiLCJ2IjoxfQ.XSVEDhc9EBrt7iWJZWsK_3v6-FEXxbZ6ut5QVfDKEBA`.
- Frontend dependencies: `npm --prefix frontend ci` — PASS, 117 packages installed from `package-lock.json`, 0 vulnerabilities; lockfile unchanged.
- Frontend baseline: `npm --prefix frontend test -- --reporter=dot` — **PASS: 10 files, 158 tests**, exit 0; `npm --prefix frontend run typecheck` — PASS, exit 0; `npm --prefix frontend run build` — PASS, Vite production build completed, exit 0.
- RED/GREEN: NOT_RUN (application patch held at L2 approval gate).
- PostgreSQL disposable cluster: NOT_CHECKED.
- Mutation: NOT_RUN.
- Coverage/flaky repetition: NOT_RUN.
- 120-task performance / p95: NOT_RUN.
- PDF/DOCX: NOT_RUN.
- Cross-phase ACK: NOT PROVIDED.
- Coding/design approval for `listing_id` query contract: NOT PROVIDED in repository evidence; GitHub issue search for `VT-089` returned no matching issue.

## 7. AI use log (initial)

- Tool: Codex coding agent (model family reported by the active environment as GPT-6); exact model build identifier unavailable.
- Prompt used: the user-provided VT-089 task specification attached to this conversation.
- Output used: repository survey, initial acceptance criteria, plan and test matrix in this document.
- Verification: claims above are tied to source lines at baseline `bee832eaf5463df20f6c6815174322871eb6685a`; no implementation claim is made.
- Human review: not yet performed; do not say the student independently verified this work.
