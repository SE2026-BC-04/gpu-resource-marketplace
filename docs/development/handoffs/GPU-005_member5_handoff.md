# GPU-005 - Member 5 Handoff (Jobs and Queue Commands)

> Phase: 1E / GPU-005
> Owner: Member 5
> Approved architecture: ../../architecture/phases/phase1e_job_submission_queue.md
> Approval date: 2026-10-21
> Status: APPROVED DESIGN / IMPLEMENTATION NOT STARTED
> Source checked: main@c90f540b385c8d11789f994748e4f5441bcb7e1b
> Cross-phase policy: ../interphase-change-control.md

## 0. Mandatory Reading & Working Rules — BẮT BUỘC

**Điều kiện trước khi bắt đầu:** người phụ trách phải đọc các tài liệu dưới đây **trên baseline Git mới nhất**, ghi phiên bản/commit SHA đã đọc, kiểm tra sự khác biệt với baseline ghi ở đầu handoff và xác nhận các dependency thực sự sẵn sàng. Việc chủ dự án duyệt thiết kế **không tự cho phép** bắt đầu code hoặc merge.

**A. Quy tắc làm việc của nhóm (đọc đủ 3 tài liệu):**

1. [Team Contribution Rules](../team-contribution-rules.md) — ownership, branch/commit, PR, independent human reviewer và điều kiện merge.
2. [Change Control](../change-control.md) — cấp độ L0–L3, quyền ra quyết định, thay đổi Requirements/ADR/API/DB contracts.
3. [Inter-Phase Change Control](../interphase-change-control.md) — phân loại tác động, cảnh báo, hai phía xác nhận và `BLOCKED_INTERPHASE`.

**B. Kiến trúc & mẫu xác nhận:**

- [Kiến trúc GPU-005 đã phê duyệt](../../architecture/phases/phase1e_job_submission_queue.md) — phạm vi, invariants, status, acceptance gates của Phase này.
- [Inter-Phase Review Template](../../architecture/phases/_interphase_review_template.md) — mẫu bắt buộc dùng khi có thay đổi thực chất ảnh hưởng Phase khác.

**C. Thiết kế / dependency phải đối chiếu theo nhiệm vụ:**

- [API Contract §8: 4 Jobs endpoints và idempotency](../../design/api-contract.md)
- [Database Design §§9,11: jobs, simulation_references, TX-SUBMIT/TX-CANCEL](../../design/database-design.md)
- [Module Design: Jobs/Manager ownership boundaries](../../design/module-design.md)
- [Test Design: API-JOB-01..16, DBTX](../../design/test-design.md)
- [Phase 1B: DB/Repository prerequisites](../../architecture/phases/phase1b_database_persistence.md)
- [Phase 1C: Auth/RBAC prerequisites](../../architecture/phases/phase1c_authentication_rbac.md)
- [Phase 1D: Listing admission/PAUSED semantics](../../architecture/phases/phase1d_gpu_listings.md)
- [ADR-004: Signed Result trust boundary (Phase 2 compatibility)](../../architecture/decisions/ADR-004-signed-result.md)

**D. Quy tắc thực hiện và phối hợp:**

- Không tự sửa code/tài liệu ngoài module ownership, không tự đổi quyết định đã duyệt; gặp mâu thuẫn giữa hai nguồn chuẩn thì **dừng phần bị ảnh hưởng và báo nhóm trưởng/chủ dự án**, không tự chọn một phiên bản.
- Trước mỗi thay đổi Markdown **hoặc** code, so sánh trước/sau và phân loại `NO_IMPACT | POTENTIAL_IMPACT | CONFIRMED_IMPACT`. `NO_IMPACT` chỉ dành cho thay đổi không đổi nghĩa kỹ thuật và phải có lý do; hai mức còn lại phải cảnh báo source owner, **từng** affected owner và nhóm trưởng.
- Với `POTENTIAL_IMPACT`/`CONFIRMED_IMPACT`, lập record bằng template; nhận ACK của **source owner + từng consumer owner** (cùng evidence link), xử lý các action/test cần thiết. Thiếu ACK hoặc còn xung đột → `BLOCKED_INTERPHASE`, **không được merge hoặc dùng làm baseline tích hợp**.
- **Quy tắc phối hợp riêng:** Không triển khai deterministic reference generator khi còn `SPEC_REQUIRED`; phải có thuật toán và test vectors được chủ dự án duyệt. Không tự hoà giải điểm bất đồng replay Idempotency-Key khi Listing PAUSED. TV5 phải phối hợp TV4 về PAUSED/admission, TV2 về DB/transaction/oracle storage, TV3 về Client principal và nhóm trưởng về tích hợp. Không tự xác nhận thay owner Phase 2 khi chưa được phân công.
- Trước PR/merge: chạy các tests áp dụng được, công bố `PASS | FAIL | BLOCKED | NOT_RUN` trung thực, cung cấp Git SHA/DB revision/commands/evidence; tuân thủ human review độc lập theo cấp độ, không self-approve/self-merge.
- **Trong mô tả PR bắt buộc ghi:** `Mandatory Reading ACK` (đã đọc những file nào, tại commit/revision nào), `Inter-Phase Impact` (kể cả `NO_IMPACT` có lý do), liên kết ACK thật nếu cần và `Test Evidence`. Không coi checklist tự đánh dấu là xác nhận thay người phụ trách khác.

**Business outcome:** Worker Login -> Listing -> Client Login -> Browse -> Submit Job -> QUEUED -> View/Cancel Job. No Manager scheduling, Simulator execution, allocations or signed results in this slice.

**Important:** two unresolved items remain BEFORE implementing and accepting the full TX-SUBMIT flow: (1) owner-approved exact deterministic reference algorithm/version/test vectors are missing, and (2) replay with an existing Idempotency-Key after Listing changes to PAUSED needs TV4 <-> TV5 source/consumer clarification under change control. Neither is implicitly approved by architecture sign-off.

### 2.2. Bốn endpoint cố định

| Method | Endpoint | Caller và success | Thao tác |
|---|---|---|---|
| `POST` | `/api/v1/jobs` | `CLIENT` → `201` mới; `200` replay idempotent cùng body | `TX-SUBMIT` tạo Job QUEUED + reference cùng commit |
| `GET` | `/api/v1/jobs` | `CLIENT`, `WORKER`, `ADMIN` → `200` | Query theo role/scope, pagination, safe projections |
| `GET` | `/api/v1/jobs/{job_id}` | Owner Client, assigned Worker, Admin → `200` | Read-only; non-visible object → `404` |
| `POST` | `/api/v1/jobs/{job_id}/cancel` | Owner `CLIENT` → `200` nếu đang QUEUED | `TX-CANCEL` sang CANCELLED + trusted `terminal_at` |

### 2.3. `TX-SUBMIT`: transaction bắt buộc

PostgreSQL `READ COMMITTED`, SQLAlchemy UoW, row lock Listing đầu tiên:

1. Parse/validate body và authenticated `CLIENT`; resolve `client_id` chỉ từ server-side `AuthenticatedPrincipal`.
2. Xác định Listing ID; `SELECT gpu_listings FOR UPDATE` trước khi chấp nhận Job; kiểm tra dưới lock trạng thái `ACTIVE` và `gpu_count <= total_gpu_count`; copy `worker_id` đúng Listing owner.
3. Trong boundary đã lock, xử lý idempotency `(client_id,idempotency_key)` với normalized request fingerprint (đúng **ba trường logical**). Same key+same body giữ **một Job gốc**; same key+changed body → `409 IDEMPOTENCY_KEY_REUSED`, không sửa bản ghi cũ.
4. Lấy trusted DB `submitted_at = clock_timestamp()` **sau khi giữ Listing lock**; INSERT Job với `QUEUED`, `enqueue_seq GENERATED ALWAYS AS IDENTITY`, immutable client/listing/worker identity và correlation data.
5. Tạo protected `simulation_references` **đúng đặc tả generator đã được duyệt**: `seed_value`, `algorithm_version`, `expected_outcome`, `expected_failure_reason`, `expected_digest`; INSERT cùng UoW/transaction với Job.
6. Chỉ COMMIT khi **cả Job và reference** hợp lệ; nếu generator/migration/constraint/DB thao tác lỗi, rollback **cả hai**. Không trả `201` khi reference thiếu hoặc chưa commit.
7. Concurrent duplicate same key trên **khác Listing** có thể gặp UNIQUE collision: rollback transaction lỗi rồi mở transaction mới đọc original key+fingerprint và trả replay hoặc conflict; không tự sinh Job thứ hai.

**FIFO:** `enqueue_seq` toàn cục có thể có gaps nhưng thứ tự Job trên cùng Listing được tuần tự hóa bởi Listing lock. Không dùng `submitted_at`/UUID client làm FIFO ordering chính. `submitted_at` authoritative và clock đáng tin phải do DB cấp sau lock.

**Guard:** DB PK của `simulation_references.job_id` bảo đảm *at most one reference*, còn *exactly one cho mỗi accepted Job* phải được bảo đảm bởi `TX-SUBMIT` cùng commit, authorized writer/DB permissions và tests; không tuyên bố FK một chiều tự bảo đảm existence. Protected reference không có route public, không nhập frontend DTO/Simulator payload/audit.

**Điểm cần review contract trước code:** API Contract §8 mô tả replay cùng key+body trả `200` với Job ban đầu, kể cả khi trạng thái Listing có thể thay đổi. DB Design §11.3 pseudocode lại **check Listing ACTIVE/capacity trước resolve replay**; replay sau khi Listing PAUSED có thể trả `409` thay vì `200`. Đây là **ambiguity thực tế** giữa hai tài liệu đã duyệt. TV4 (Listing owner) ↔ TV5 (Job owner) phải trình nhóm trưởng/owner quyết định thứ tự ưu tiên/replay semantics, cập nhật tài liệu/test oracles theo change control nếu cần, trước khi triển khai. **Không tự âm thầm chọn một cách hiểu.**

### 2.4. `DEC-P1-04` — protected deterministic reference

**Đã được chủ dự án phê duyệt về nguyên tắc:**
- Một record `simulation_references` bất biến cho mỗi Job được chấp nhận; tạo cùng atomic `TX-SUBMIT`.
- Reference deterministic và versioned; `job_id` PK+FK, `seed_value bigint`, `algorithm_version varchar(32)`, `expected_outcome=SUCCESS|FAILED`, `expected_failure_reason` theo thiết kế và `expected_digest="sha256:" + 64 hex lowercase`.
- Chỉ trusted backend/Manager được đọc; Client/Worker/Simulator không được thấy. Signed result ở Phase 2 là một **claim**, không thể coi đương nhiên là ground truth.

**Chưa có đặc tả trong repository: `SPEC_REQUIRED`**, bao gồm:
1. Nguồn và cách derive `seed_value` đúng kiểu bigint, inputs/tính ổn định qua restart/replay.
2. Exact generator/algorithm version và các input/configuration bất biến; các yếu tố làm thay đổi reference.
3. Cách sinh expected simulated output byte-for-byte; mapping `SUCCESS` / `FAILED` và `WORKER_FAULT` / `JOB_FAULT`.
4. Cách hash expected output thành `sha256:<64 lowercase hex>`; test vectors cố định `(input → seed/version/outcome/failure/digest)`.
5. Bảo vệ dữ liệu/salt/secret nếu spec cần, quyền đọc DB/serializer, và tương thích Simulator wire allowlist `{ "workload_profile": "demo-v1" }` + ADR-004 Signed Result/Dispute về sau.

**Gate bắt buộc:** TV5 soạn một **technical specification riêng để chủ dự án review/approve** trước khi implement generator. TV2 xác nhận schema/permission compatibility; nhóm trưởng rà ảnh hưởng Phase 2; nếu khác approved design thì change control L2/L3. **Không hardcode oracle “minh họa” hoặc chọn hash/seed formula mà không có approval.** Có thể code độc lập Jobs DTO/read/guards/UI với mocks trước, nhưng **không thể nghiệm thu full `TX-SUBMIT` hoặc tuyên bố GPU-005 DONE** khi generator spec chưa được duyệt.

**Vấn đề phụ cần chốt trong implementation review:** canonical byte representation của fingerprint `request_sha256` trên ba logical fields; phải tái lập byte-identical qua HTTP retries, không sửa ngữ nghĩa idempotency đã duyệt.

## 3. NHIỆM VỤ CHO THÀNH VIÊN 5

| ID | Deliverable | Gate/phụ thuộc |
|---|---|---|
| `GPU-005-A` | Đối chiếu `jobs`, reference, auth/listing/repo interfaces; lập impact matrix | TV2/TV3/TV4 + nhóm trưởng; xem conflict replay-on-PAUSED |
| `GPU-005-B` | Viết deterministic reference **spec + approved test vectors** (không tự code trước) | Owner approval, TV2 schema check, Phase 2 compatibility review |
| `GPU-005-C` | Implement Job DTO/router, role-safe query, pagination, typed errors | GPU-002/003/004 đã integrate |
| `GPU-005-D` | Implement `TX-SUBMIT`, idempotency, atomic reference + `TX-CANCEL` | Spec đã duyệt; Listing-first locking; real PostgreSQL |
| `GPU-005-E` | React Jobs UI, integrate Listing detail + Auth | TV3/TV4 frontend contract + shared app shell |
| `GPU-005-F` | Pytest PostgreSQL, HTTP/API tests, Vitest, E2E Phase 1 user journey | TV2/3/4 real integration; no fake green tests |
| `GPU-005-G` | Impact ACK, docs/handoff/CI evidence, independent PR review | No open blockers; nhóm trưởng integration |

## 4. KIỂM THỬ VÀ NGHIỆM THU

### 4.1. API/transaction traceability

| Test design | Có thể nghiệm thu ở 1E? | Ghi chú |
|---|---|---|
| `API-JOB-01..09` | **Đầy đủ khi spec/reference và upstream code sẵn sàng** | Valid submit/replay/conflict/input/paused/oversize/RBAC/read/cancel |
| `API-JOB-10` | **Có thể dùng seeded state fixtures** | Không đồng nghĩa Manager transitions đã implement |
| `API-JOB-11..13` | **BLOCKED phần Manager thực thi** | Cancel-vs-allocation / scheduler FIFO cần Phase 2 |
| `API-JOB-14` | **BLOCKED phần retention cleanup** | 23-day purge thuộc Phase 2–3, không giả runtime retention |
| `API-JOB-15..16` | **Có thể chạy ở 1E** | Pagination/role-safe Worker + Client projections |
| `DBTX-01`, `DBTX-02` | **Có thể chạy phần Submit / PAUSE serialization** | PostgreSQL concurrency barriers, fresh transactions |
| `DBTX-05`, `DBTX-03/04` | **BLOCKED phần Manager allocation** | Không hạ oracle hoặc mock Scheduler và gọi đó là PASS |

### 4.2. Acceptance gates GPU-005

| Gate | Binary PASS oracle | Hiện trạng |
|---|---|---|
| `P1E-AC-01` | 4 endpoints HTTP đúng routes, status/error DTO và `X-Request-ID`, private no-store; JWT verified từ DB | `NOT_RUN` |
| `P1E-AC-02` | Submit ACTIVE + gpu<=total tạo đúng **1 QUEUED + 1 protected reference**, cùng commit; error rollback 0 orphan rows | `BLOCKED: SPEC_REQUIRED` |
| `P1E-AC-03` | Idempotency same key/body (kể cả concurrent) 200 original ID, different body 409, 0 extra Job/reference | `NOT_RUN`; giải quyết replay-vs-PAUSED ambiguity |
| `P1E-AC-04` | `enqueue_seq` cùng Listing theo lock admission, kể cả DB timestamp trùng; không claim Manager FIFO PASS | `NOT_RUN` |
| `P1E-AC-05` | PAUSED/oversized/invalid/unauthorized submit chặn đúng, không mutate DB, không dựa UI available count | `NOT_RUN` |
| `P1E-AC-06` | Owner QUEUED cancel 200 + terminal time; replay 409; wrong owner 404; RUNNING/terminal 409; 0 GPU/reputation effect | `NOT_RUN` |
| `P1E-AC-07` | GET `mine/assigned/all` role-scoped và pagination/cursor; zero protected oracle/Client secrets leakage | `NOT_RUN` |
| `P1E-AC-08` | Frontend real end-to-end **Worker Login → Listing → Client Login → Browse → Submit → QUEUED → View/Cancel** | `BLOCKED: GPU-002/003/004 code chưa merge` |
| `P1E-AC-09` | pytest/real PostgreSQL, fixture + concurrency tests, Vitest, build, Compose/CI regression có SHA và logs | `NOT_RUN` |
| `P1E-AC-10` | Mọi confirmed cross-phase impacts được source + mỗi affected owner ACK; human PR review hợp lệ | `NOT_RUN` |

Mỗi test evidence ghi commit SHA, Alembic head, PostgreSQL 16/runtime, fixture, trusted/fake clock, HTTP request/response đã redact, SQL rows before/after, command, actual result và `PASS|FAIL|BLOCKED|NOT_RUN`. Approval design không tương đương test `PASS`.

## 5. INTER-PHASE IMPACT & DUAL ACKNOWLEDGEMENT — BẮT BUỘC

Theo [Inter-Phase Change Control](../interphase-change-control.md), thay đổi **nội dung Markdown có ảnh hưởng thật** cũng phải cảnh báo hai chiều; không đợi code. Không dùng PR human review thay cho việc source owner + affected owner xác nhận.

| Nguồn ↔ Consumer cần xác nhận | Trigger thực tế |
|---|---|
| TV2 ↔ TV5 | Job/reference schema, `enqueue_seq`, idempotency uniqueness, Listing lock/UoW, DB grants/triggers, seed fixture thay đổi |
| TV3 ↔ TV5 | `CLIENT`/`WORKER` role, authenticated principal, JWT/client headers, scope/responses thay đổi |
| TV4 ↔ TV5 | Listing ACTIVE/PAUSED, owner binding, capacity admission, Listing DTO/URL, pause vs submit behavior thay đổi |
| Nhóm trưởng ↔ TV5 | Shared FastAPI/router/error handling, frontend shell/API client, Compose, CI hoặc phase integration thay đổi |
| TV5 ↔ owner Phase 2 **sau khi phân công** | Job state/FIFO/idempotency/protected oracle/Manager handoff hoặc Signed Result compatibility thay đổi |

**Trạng thái tại thời điểm thiết kế:**
- `POTENTIAL_IMPACT — REVIEW REQUIRED`: mâu thuẫn diễn giải **idempotent replay trên Listing vừa PAUSED** giữa API Contract §8 và DB Design §11.3. Chưa có quyết định hóa giải, cần **TV4 ↔ TV5** đối chiếu cùng nhóm trưởng/owner trước coding.
- `SPEC_REQUIRED`: deterministic reference algorithm/test vectors chưa được phê duyệt; **TV5 và owner** cần review, TV2 xác nhận schema, Phase 2 compatibility phải được ghi nhận khi có owner.
- Các nội dung khác: `NO_CHANGE_ASSESSED` (chưa có source diff mới). **Chưa có ACK của bất kỳ thành viên nào** và không được tự điền.

**Khi có diff:** điền record `XPH-GPU-005-nn` (file/old SHA→new SHA, before→after, impacted contracts, classification `NO_IMPACT|POTENTIAL_IMPACT|CONFIRMED_IMPACT`, owner source ACK, từng owner nhận `ACK_COMPATIBLE|ACK_WITH_ACTIONS|REJECTED`, test evidence, gate). Nếu `POTENTIAL/CONFIRMED` chưa có dual ACK hoặc còn test/contract conflict → `BLOCKED_INTERPHASE`; chưa được merge/dùng baseline. `NO_IMPACT` thuần diễn đạt có lý do thì không buộc hai ACK.

**Git governance:** L0/L1 requires >=1 independent human reviewer, L2/L3 requires >=2; authors cannot self-approve or self-merge. Phase 1E DESIGN was approved 2026-10-21, but this approval does not replace technical specification approval, impact ACKs, tests or PR review.

**Owner approval record (2026-10-21):** APPROVED DESIGN for GPU-005 scope and task decomposition only. No approval of invented oracle algorithm, resolution of replay conflict, cross-phase ACK, or code implementation is implied.

## Delivery and review protocol

1. Confirm GPU-002/003/004 real implementation revision, DB migrations and compatible interfaces. Approved designs alone are not substitutes.
2. Record a separate technical specification and owner decision for reference seed, algorithm version, expected outcome/digest and fixed test vectors; TV2 must check schema, the future Phase 2 owner when assigned must be warned of compatibility implications.
3. For a contract-impacting Markdown or code diff, record old/new, affected owner(s), source ACK and each consumer ACK; unresolved impact is BLOCKED_INTERPHASE, not PASS.
4. Execute applicable PostgreSQL/HTTP/frontend tests and record SHA, revision, commands and observed outputs. Phase 2-only tests remain BLOCKED/NOT_RUN, not PASS.
5. Use the approved team PR workflow: L0/L1 at least one independent human reviewer; L2/L3 at least two, plus owner decision. Never self-approve or self-merge.
6. After the PR is merged and evidence is verified, change GPU-005 from PLANNED to IMPLEMENTED and record the actual references in the phase document.

**Current evidence:** No GPU-005 application code, test PASS, new PR or source/consumer ACK is claimed by this handoff.

## Pre-PR Checklist — GPU-005 (chưa xác nhận)

> Checklist phải được chính thành viên phụ trách hoàn thành **trước khi yêu cầu merge** và gắn vào PR. Các ô bên dưới mặc định chưa đánh dấu; tài liệu được duyệt không đồng nghĩa đã hoàn thành các bước.

- [ ] Đã đọc `team-contribution-rules.md`, `change-control.md`, `interphase-change-control.md` và ghi `Mandatory Reading ACK` kèm commit SHA/revision.
- [ ] Đã đọc kiến trúc GPU-005, `docs/design/`/ADR liên quan, và kiểm tra baseline/contract của các Phase phụ thuộc.
- [ ] Đã kiểm tra ownership: chỉ sửa các file đúng trách nhiệm hoặc có xác nhận từ owner của shared file.
- [ ] Đã đánh giá diff Markdown/code: `NO_IMPACT` có lý do hoặc `POTENTIAL_IMPACT` / `CONFIRMED_IMPACT` với Impact Report theo template.
- [ ] Nếu có ảnh hưởng liên Phase, đã thông báo source owner, **từng** affected owner và nhóm trưởng; đã nhận đủ ACK có link thật, xử lý `ACK_WITH_ACTIONS` và không còn `BLOCKED_INTERPHASE`.
- [ ] Nếu thay đổi Requirements/ADR/API Contract/Database Design, đã đi đúng Change Control và nhận quyết định của người có thẩm quyền.
- [ ] Đã chạy các test bắt buộc có thể áp dụng; ghi rõ lệnh, fixture, commit SHA, kết quả và bằng chứng; không ghi PASS cho `NOT_RUN` / `BLOCKED`.
- [ ] Đã cập nhật phase doc, handoff / README cần thiết và kiểm tra Markdown links, bảo đảm status triển khai phản ánh code/PR thật.
- [ ] Đã ghi `Mandatory Reading ACK`, `Inter-Phase Impact`, `Test Evidence` trong PR và yêu cầu **independent human reviewer** theo cấp độ; không tự approve/merge.
