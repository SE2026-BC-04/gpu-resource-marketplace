# HANDOFF TV4 — Phase 2D: Strict FIFO Scheduling, Capacity Allocation & Concurrency

**Owner:** TV4 `@VietNguyen865` — Listing/FIFO **policy owner**, phối hợp tích hợp Manager Scheduler.  
**Version:** `v1.2-docs-review`, updated 2026-11-19; giữ tên file để không phá đường dẫn tham chiếu.

**Trạng thái:** TV1 đã review #48 @ `b399118` với `ACK_WITH_ACTIONS / HOLD DOCS GATE`; revision này ghi nhận các action nhưng vẫn `EXACT_HEAD_CROSS_REVIEW_PENDING / NO_CODE_AUTHORIZATION`. Tự review/Codex không phải ACK độc lập; chưa code kể cả policy thuần trước khi docs được merge và có coding gate riêng.

**Thiết kế chuẩn:** [Phase 2D](../../../architecture/phases/phase2/Phase_2D_v0.9.md), bản rà soát `0.9-docs-review-20261119`; giữ `P2D-GATE-01=APPROVED_DESIGN_CONDITIONAL`, đối chiếu #47 `001619d`, #46 `0ca059c`, #49 `62bded7`, #50 `edb247f8`. D-18/E-C3, G1 và Worker-first lock là `APPROVED_DESIGN_DIRECTION_CONDITIONAL`; D-19, TTL/replay/restart, provisioning/compromise và numeric budgets còn OPEN.

**Baseline hiện tại:** `main@bee832eaf5463df20f6c6815174322871eb6685a` sau docs intake [#44](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/44). [#39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) đã merge bởi TV1, merge SHA `aff538f79997c6e2bfcf359b176a82f2cd9ecc53`, source head `3482bce3cc9726543b9345a5224d8db1b9fc6454`; #42 đã nằm trong baseline qua #39. #17/#31 đã merged. Read-only Alembic graph có một head `0005_listing_d7`; chưa kết nối DB để xác nhận installed revision/native role trong lần review này.

**Phạm vi cập nhật:** chỉ hai file thiết kế/handoff TV4; không sửa application/test code, SQL, migration hay database. Nhánh `docs/phase2d-design-review`; [#45 giữ Draft/HOLD](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/45#issuecomment-6721101443) vì prototype được làm trước khi quy trình docs-first được làm rõ. CI/unit test của prototype không mở coding gate và không phải chứng cứ runtime allocation.

## 1. Mục tiêu tổng quát và điều kiện thành công

TV4 phải định nghĩa và (chỉ sau khi được cho phép) triển khai/kiểm chứng **chính sách chọn Job để cấp phát GPU mô phỏng theo FIFO nghiêm ngặt trên từng Listing**, tương thích với Listing ACTIVE/PAUSED và Job QUEUED/RUNNING/CANCELLED của Phase 1, đồng thời bảo đảm tiến độ xét các Listing độc lập, không làm sai capacity dưới cạnh tranh đồng thời.

**Sáu kết quả phải đạt sau khi triển khai và kiểm thử:**

1. **FIFO đúng:** trong một Listing, Job `QUEUED` có `enqueue_seq` nhỏ nhất luôn được xét trước; không dùng `submitted_at`, UUID, khả năng vừa GPU, hay `SKIP LOCKED` ở Job để chọn Job đứng sau. Không đặt FIFO toàn cục giữa các Listing.
2. **Không cấp phát quá khả năng:** chỉ cấp phát nếu Listing còn `ACTIVE`, Job thật sự `QUEUED` và `requested_gpu_count <= total_gpu_count - allocated_gpu_count` **sau khi giữ Listing lock**. Invariant bền vững: `0 <= allocated_gpu_count <= total_gpu_count` và `allocated_gpu_count == SUM(gpu_count của Allocation ACTIVE cùng Listing)`.
3. **Một commit nguyên tử:** mỗi `TX-ALLOCATE` có **một Listing, tối đa một FIFO-head Job, một transaction**; Job `RUNNING`, counter GPU, một Allocation, một Attempt và một Outbox event được ghi cùng commit. TV2 sở hữu SQL/UoW; TV4 sở hữu luật chọn, outcome oracle và kiểm chứng; TV1 quản lý vòng lặp thực thi.
4. **Đúng khi cạnh tranh:** Pause, Resume, capacity/hardware PATCH, Cancel và hai Manager đồng thời đều cho ra một trạng thái hợp lệ theo thứ tự commit; không có partial RUNNING, double reservation, head bypass, duplicate Attempt/Outbox.
5. **Liveness có giới hạn tài nguyên:** Scheduler quét **mặc định 2 giây, cấu hình được**, duyệt Listing theo cursor/quay vòng và budget hữu hạn. Listing có head quá lớn chỉ chặn chính Listing đó, không làm các Listing khác bị bỏ đói. Không suy diễn từ 2 giây thành SLA bắt đầu Job.
6. **Khôi phục và phối hợp đúng:** Manager restart hoặc mất COMMIT ACK không được cấp phát lần hai; PAUSED **không cản retry dispatch của Attempt RUNNING đã tồn tại**; khóa ký Worker có trạng thái đủ điều kiện mới cho phép allocation theo hợp đồng được duyệt (đang `PENDING_ACK`).

**Definition of Done:** Code policy và integration được review theo nguồn/consumer SHA; PostgreSQL deterministic concurrency (hai commit orders), rollback/commit-unknown, fairness bounded, replay/rotation tests chạy và có chứng cứ; CI/human review trên exact head. Không dùng test/mock Phase 1 thay cho kiểm thử Phase 2.

## 2. Ownership — TV4 làm gì, KHÔNG làm gì?

| Công đoạn | TV4 chịu trách nhiệm | TV khác chịu trách nhiệm, không giao trùng |
|---|---|---|
| FIFO/head-of-line | Pure policy nhận immutable scalar snapshot do TV2 tạo dưới khóa và trả `ELIGIBLE/EMPTY/HEAD_DOES_NOT_FIT/LISTING_NOT_ACTIVE`; không cầm ORM/Session, không tuyên bố COMMIT | **TV2** chọn head thật bằng `enqueue_seq`, viết SELECT/LOCK/UPDATE và map assessment sang `B-IF-06`; TV4 review theo luật FIFO |
| Manager Scheduler | Đề xuất stable rotating cursor, fairness oracle và test tiến độ/liveness | **TV1** giữ Supervisor/vòng lặp, bounded scan, proof-call orchestration, executor, shutdown, config và metrics integration |
| `TX-ALLOCATE` | Invariant, test oracle, contract với UoW, chỉ tích hợp bằng interface được ACK | **TV2** sở hữu một DB Session, transaction, lock, DB time, role/grants, atomic commit, error mapping |
| Listing/Cancel/Resume | Xác nhận tương thích Listing Phase1, race policy và regression test; không mở rộng HTTP API | API Listing và `TX-CANCEL` Phase 1 giữ sở hữu hiện tại; **TV5** xác nhận lifecycle Job/Attempt/Outbox |
| `RUNNING` dispatch retry | Chứng minh PAUSED không làm đổi Attempt và không allocate lần hai; chỉ `ACK_COMPATIBLE` với boundary D-19 | **TV1** Dispatch/HTTP, **TV2** normal Outbox và repair SQL/fence, **TV5** Simulator/Finalizer; D-19 vẫn cần L2 approval |
| Key readiness/rotation | Ranh giới tạm PAUSE/quiescence đối với Listing và race với allocation; đề xuất fail closed | **TV3** security/key policy, **TV5** private signing key/Simulator, **TV2** key registry SQL; incident compromise cần quyết định riêng |
| Finalization/release | Đối chiếu conservation sau khi Job terminal, kiểm tra không over/under-release | **TV5** business Finalizer/Reputation, **TV2** atomic release SQL, **TV1** điều phối |

**TV4 không tự:** tạo Scheduler service thứ sáu, bảng mới, migration/GRANT, SQL `TX-ALLOCATE` song song với TV2, đổi API Submit/Cancel, đổi Signed Result V1, sửa token/JWT, xây Finalizer/Reputation, cho Simulator dùng DB, hoặc giữ HTTP call dưới PostgreSQL domain lock. **Thứ tự:** tự review/sửa docs → PR docs/review chéo → nhóm trưởng chốt và merge docs → code. Sau đó **một task = một nhánh = một PR** từ `main` mới nhất; không dùng một nhánh cho toàn Phase và không phải đợi cả Phase xong mới merge một task đủ cổng.

## 3. Nguồn bắt buộc phải đọc — chính xác phiên bản

### 3.1. Năm file thiết kế baseline đã được nhóm trưởng chốt có điều kiện

| Thứ tự | File | TV4 phải rút ra điều gì? | SHA256 Git blob tại `main@bee832e`, trước bản sửa này |
|---|---|---|---|
| 1 | `Phase_2D_v0.9.md` | `P2D-OPEN-01..03`; FIFO strict; `D-IF-01..09`; `P2D-TX/RACE/SCHED/DRT`; cảnh báo `reserved_gpu_count` | `fdb7f79a1b89b9ed911fddce67da1763ea88a5417ab946a3121f8701f8758c60` |
| 2 | `Phase_2B_v1.3.md` | Native Manager UoW, 6 Phase2 tables, `allocated_gpu_count`, single-commit, `COMMIT_OUTCOME_UNKNOWN`, lock/grant | `27c59f3e2eddc2584fc9c904aacfc7d45aa323b8745ec77eb5775d59b1af3371` |
| 3 | `Phase_2A_v0.9.md` | Manager Scheduling loop; 2s cadence vs Dispatch/Finalizer loops, cursor/queue/executor/DB pool | `2168e036203c1370b56c2ffe7e5633d398266f72423a370254df33273f7162a2` |
| 4 | `Phase_2E_v1.8.md` | one Attempt/Outbox, Simulator dispatch identity, PAUSED RUNNING retry, single terminal/release | `90af557a46a0f7bcb663eb9d17de3a2db866c4c0b2f1e5006a9160eed2d6609f` |
| 5 | `Phase_2C_v0.9.md` | signing-key readiness, planned K1→K2 rotation, key compromise incident chưa chốt | `d92901a412aaaaa3a2e601781b3991019de9eeee1f45b891564a64d3fbd33902` |

**Lưu ý:** Các hash trên là dấu mốc `main@bee832e`, không phải SHA của các revision đang cross-review. Nguồn producer hiện hành để ACK là #47 `001619d`, #46 `0ca059c`, #49 `62bded7`, #50 `edb247f8`; review trên SHA cũ không tự chuyển sang SHA mới. Mốc `44579ed` và trạng thái #39/#42 cũ trong tài liệu các Phase khác không thay baseline hiện tại. Revision này chỉ sửa hai file TV4; thay đổi ảnh hưởng Phase khác cần owner nguồn và consumer xác nhận. Conditional approval hoặc merge #44 không hoàn tất review chéo.

### 3.2. Files GitHub phải đọc trên baseline thực tế

- `docs/architecture/phases/phase1d_gpu_listings.md` — Listing lifecycle, `PATCH` hardware, capacity floor, PAUSED, role ownership.
- `docs/design/database-design.md` §§5/9/11 — `jobs.enqueue_seq`, `gpu_listings.allocated_gpu_count`, `allocations`, `execution_attempts`, `execution_outbox`, lock order, constraints.
- `docs/design/api-contract.md` §§7,8,13 — Listing/CANCEL, Submit idempotency, internal dispatch (không thêm endpoint mới cho FIFO).
- `docs/design/test-design.md` — real DB barrier/two-order acceptance; `ADR-002`, `ADR-003`, `ADR-005` — API/Manager DB boundary, durable Outbox, retry/deadline.
- `backend/src/gpu_marketplace/listings/{service,policy,ports}.py`; `backend/src/gpu_marketplace/repositories/listings.py` — Listing row lock, hardware edit khi có QUEUED/RUNNING, downsize dưới `allocated`/`MAX(QUEUED)`.
- `backend/src/gpu_marketplace/jobs/{submit,cancel}.py`, `backend/src/gpu_marketplace/repositories/{job_submit,jobs,commit_outcome}.py` — TX-SUBMIT idempotency, CANCEL serialize với Allocation tương lai, commit-unknown classification.
- `backend/src/gpu_marketplace/manager/service.py` — **hiện còn** `_foundation_idle_runner`, chưa có Phase2 Manager Scheduler.
- `backend/tests/{test_phase1_runtime_http_postgres_e2e,test_listing_repository_postgres,test_listing_d7_postgres,test_jobs_submit_adapter_postgres,test_jobs_cancel_adapter_postgres}.py` — chỉ có baseline Phase1, không phải TV4 Phase2 PASS.
- `backend/migrations/versions/0001_phase1b_baseline.py` đến `0005_listing_d7.py` — migration graph hiện tại trên main; TV2 phải xác nhận actual installed revision, native roles/grants và migration cha Phase 2 trước khi triển khai DB. Một head trong source không phải bằng chứng DB đã migrate.

**Bằng chứng Phase1:** #17/#31/#39 merged, #42 đã vào main qua #39. Bốn test Submit ↔ Pause/Resize đã được bổ sung và PASS tại [CI head `3482bce`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533), ghi trong [TV4 re-review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#pullrequestreview-5813339600); không tiếp tục ghi đây là gap còn thiếu. [Audit khi role bị từ chối sớm](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#discussion_r4502535120) vẫn là follow-up riêng cần lead ghi disposition. Không suy từ việc merge sang finding đã sửa, hoặc từ CI Phase1 sang Phase2 `P2D-*` PASS.

## 4. Các quy tắc đã duyệt — KHÔNG được mở lại khi code

### 4.1. FIFO nghiêm ngặt **trên mỗi Listing**, không có backfill

Ví dụ Listing L1 có `total=4`, `allocated=2`, còn `free=2`: `J_A` là QUEUED head (`enqueue_seq=10`) cần 3 GPU; `J_B` đứng sau (`enqueue_seq=11`) cần 1 GPU. **Cả J_A và J_B vẫn QUEUED**. Không được cấp phát J_B. Có thể tiếp tục xét FIFO head của Listing L2 độc lập.

- `enqueue_seq` là nguồn xác định accepted order, không dùng `submitted_at`, UUID, Job ID hoặc thời điểm trình duyệt.
- Chọn `QUEUED` head trong **Listing đang khóa**; một Job bị lock hoặc thiếu tài nguyên không được coi là lý do bỏ qua nó để chọn Job sau.
- Contract TV1/TV2 hiện tại không dùng `SKIP LOCKED` cho Listing hay Job; lock bận dùng timeout hữu hạn và `Noop(LOCK_BUSY)`, sau đó quay lại Listing ở lượt sau. Không nhảy qua Job đầu hàng.
- Nếu head đã `CANCELLED`, nó không còn thuộc tập `QUEUED`; lần xét sau có thể chọn Job QUEUED tiếp theo.
- `total_gpu_count` không được giảm dưới `allocated_gpu_count` hoặc `MAX(requested_gpu_count)` của Jobs đang QUEUED; CPU/GPU được quan sát từ DB sau Listing lock, không từ UI.

### 4.2. Một Listing/một head/một transaction — `P2D-OPEN-01=APPROVED`

Một Scheduler tick có thể xét nhiều Listing nhưng **mỗi `TX-ALLOCATE` chỉ giữ một Listing và tối đa một head**; commit/rollback độc lập. TV2 phải bảo đảm trong **cùng transaction**: Listing `allocated_gpu_count += demand`, Job `QUEUED → RUNNING`, tạo duy nhất `Allocation`, `ExecutionAttempt`, `ExecutionOutbox` cùng IDs ổn định. Thời điểm `started_at` từ `clock_timestamp()` sau lock; deadline `finish_due_at = started_at + duration_seconds`, `hard_deadline_at = finish_due_at + 120s`. **Không gửi HTTP** khi còn giữ Listing/Job lock.

> **Erratum X-01 được đề xuất sửa trong PR docs này:** §7.3 thiết kế trước đó dùng nhầm `reserved_gpu_count`; đã căn lại thành **`gpu_listings.allocated_gpu_count`** theo schema và Database Design §11.3 A. Không thêm/đổi tên cột. TV4 đưa sửa lỗi ra review; còn cần TV2 và nhóm trưởng xác nhận, chưa tự ghi ACK thay họ.

### 4.3. Scheduler 2 giây **cấu hình được**, không phải SLA — `P2D-OPEN-03=APPROVED`

- Định kỳ quét Listing mặc định 2s; đây là **Scheduler cadence**, riêng với dispatch/inbox/deadline cadence của ADR-005.
- Đặt giới hạn tối đa Listing per cycle, thời gian/worker executor và DB pool; **các số cụ thể đang `PENDING_PARAMS`** với TV1+TV2+TV4, không giả định tick nào cũng duyệt hết hệ thống.
- Scan ID theo thứ tự ổn định và rotating cursor/wrap-around qua các tick; ghi cursor của **Listing được kiểm tra**, không dựa trên Listing vừa allocate; blocked/PAUSED/lock-skipped Listing vẫn được xem lại về sau.
- Không tạo bảng mới lưu scheduler cursor; cursor trong RAM chỉ là tối ưu. Sau restart tìm eligible Listing bằng DB và quét lại an toàn, không allocate trùng.
- Khi Listing đầu scan có head quá lớn, vẫn dành budget cho các Listing khác. Đảm bảo Dispatch/Finalization không bị Scheduler chiếm hết executor/pool; phải đo khi có tải thực tế.

### 4.4. PAUSED và các quy tắc Phase1/Phase2 khác nhau

- **PAUSED cấm** Job Submit mới (key mới) và `TX-ALLOCATE` mới; **không** hủy các Job RUNNING; QUEUED vẫn chờ; Client vẫn có thể Cancel chính Job QUEUED.
- **Same-key retained Submit replay**: nếu cùng Client, key và normalized body, trả lại Job cũ `HTTP 200` kể cả Listing PAUSED. Body khác → 409; new key vào PAUSED → 409. Đây là **quyết định Phase1 đã được owner phê duyệt trên PR39**, không mở lại.
- **`P2D-OPEN-02=APPROVED`:** đã RUNNING thì Dispatch Loop có thể resend **cùng Attempt, Outbox event và immutable payload** theo ADR-005, dù Listing PAUSED. Không tạo Reservation/Attempt/Outbox mới, không kéo dài hard deadline, không đánh đồng `202` dispatch với Job Completed.
- **RESUME** chỉ bật chấp nhận Job/allocation sau khi Scheduler tới lượt và có GPU, không tự cấp phát tức thì hoặc ưu tiên Job mới.

### 4.5. Khóa ký Worker và biến cố chưa chốt

Theo quyết định có điều kiện D-18/E-C3 của TV1, allocation lấy Worker advisory shared trước Listing→Job; đăng ký/kích hoạt key lấy exclusive. Hai key active là hàng rào chặn allocation khi drain RUNNING; kích hoạt kiểm tra đúng {K1,K2}, K2 sẵn sàng và không còn RUNNING; nếu lỗi phải khôi phục signer K1 trước khi bỏ hàng rào. Manager lấy G1 proof ngoài UoW và truyền `SignerReadiness`; TV2 recheck worker/key/fingerprint/expiry dưới khóa, sai trả `Blocked(SIGNER_NOT_READY)` không thay đổi hàng đợi/capacity. Đây là hướng thiết kế có điều kiện, còn source L2, exact-SHA ACK, TTL/replay/restart và incident policy; tests `NOT_RUN`, chưa được code.

## 5. Sáu nhiệm vụ chuẩn bị trước khi nhóm trưởng cho phép code

| ID | Nhiệm vụ / chủ trì | Việc cần làm cụ thể | Bàn giao / tiêu chí chốt |
|---|---|---|---|
| `TV4-P2D-01` | **Freeze Phase1 baseline** | Ghi main/source/merge SHA ở đầu file, một head `0005_listing_d7`, evidence bốn Submit-Pause/Resize barriers; TV2 xác nhận installed DB revision/native roles; lead ghi disposition audit còn mở. | Baseline source đã cập nhật; DB runtime identity/audit disposition còn chờ. Không gộp gap đã sửa với follow-up chưa xử lý. |
| `TV4-P2D-02` | **Chốt FIFO và capacity oracle** | Đọc `Phase_2D_v0.9`, so thực schema `jobs.enqueue_seq`, phép chọn QUEUED head; xác nhận một Listing/transaction, bảng kết quả QUEUED/PAUSED/Blocked. Báo erratum `reserved_gpu_count → allocated_gpu_count` cho TV2+lead. | Policy spec/decision table và erratum ACK; không đổi FIFO hoặc thêm column. |
| `TV4-P2D-03` | **Freeze `allocate_one_listing` port** | TV4 policy + TV2 UoW + TV1 caller + TV5 Job semantics: input/outcome/IDs, native role, lock order/timeout, `LOCK_BUSY`, COMMIT unknown; giữ EMPTY/BLOCKED COMMIT no-op theo DB Design, chốt cleanup kết quả khác và reconciliation. | ACK cho `D-IF-01/02/05/06/08`, interface snapshot theo source & consumer SHA; không code trước khi chốt tác động. |
| `TV4-P2D-04` | **Chốt Listing scan/fairness/resource budget** | Cùng TV1+TV2 chốt stable order/cursor, lock timeout và quay lại Listing sau, per-tick budget, executor/DB pool, startup/shutdown và metrics; contract hiện tại không dùng Listing `SKIP LOCKED`. | `D-IF-03/04` ACK, thông số chọn qua review/đo, không tự gán mặc định ngoài tick 2s. |
| `TV4-P2D-05` | **Chốt race/key readiness** | Lập 2 commit orders cho Pause/Resume/Capacity PATCH/Hardware PATCH/Cancel/Allocate; TV3/TV5 chốt signer readiness, K1→K2, no HTTP under DB lock; phản hồi `X-01/X-04`. | Race truth table, `D-IF-06/07` ACK; companion owner decision về compromised key nếu cần. Test phụ thuộc `BLOCKED` tới khi được phép. |
| `TV4-P2D-06` | **Chuẩn bị deterministic test & code gate** | Chốt fixtures > cycle budget, FIFO head quá lớn, 2 native PostgreSQL sessions + barriers, schema/role safety, expected row snapshots, test IDs, review responsibilities; thu thập quyền code riêng. | Ma trận `P2D-TX/RACE/SCHED/DRT`, kế hoạch test, reviewer + gate; không chạy migration/test phá dữ liệu trên persistent DB. |

**Trước code:** mọi thay đổi giao diện ảnh hưởng người khác cần ACK của owner nguồn và từng consumer. Owner decision về code Phase2 phải ghi phạm vi, branch, dependency; sự đồng ý với handoff chỉ cho phép giao việc ở mức tài liệu.

## 6. Mười một nhiệm vụ triển khai kỹ thuật SAU coding gate

| ID | Nhiệm vụ TV4 | Công việc kỹ thuật cụ thể của TV4 (không lấn ownership) | Đầu ra / điều kiện PASS |
|---|---|---|---|
| `TV4-P2D-07` | **FIFO policy thuần** | Viết/hoàn thiện logic chính sách: thứ tự `enqueue_seq`, chọn first QUEUED, từ chối head over free/INACTIVE, không backfill; quy tắc next Job khi head Cancelled. Không đọc UI snapshot để quyết định. | Tests unit: tie timestamps/UUID vẫn theo seq; head không fit→BLOCKED; Listing khác được xét. |
| `TV4-P2D-08` | **Tích hợp port TV2 `TX-ALLOCATE`** | Cùng TV2 kiểm Worker advisory shared→Listing→Job, proof/key, conditional status/capacity/identity, một UoW; TV4 chỉ implement policy/adapter sau docs gate. | Một head, một Allocation/Attempt/Outbox và counter delta nguyên tử; DB conservation đúng. |
| `TV4-P2D-09` | **Kết quả typed và lỗi** | Chốt một vocabulary: policy thuần `ELIGIBLE/EMPTY/HEAD_DOES_NOT_FIT/LISTING_NOT_ACTIVE`; UoW `Allocated/Blocked/Noop/CommitOutcomeUnknown`; exception `DependencyUnavailable`. Diễn giải `LOCK_BUSY`; chỉ cho TV1 retry theo ACK, không blind retry khi lost ACK. | TV1/TV2/TV5 signoff theo exact SHA; unknown COMMIT reconcile từ DB trước quyết định, không duplicate. |
| `TV4-P2D-10` | **Listing scan policy và fairness** | Thiết lập policy stable order, cursor wrap, per-cycle bounded scan và starvation regression; tích hợp với Scheduler loop của TV1 và UoW TV2, không tự tạo supervisor độc lập. | `P2D-SCHED-01..05`, DRT-09/10 PASS khi thực chạy; số scan và DB calls có giới hạn. |
| `TV4-P2D-11` | **Listing PAUSE/RESUME/PATCH vs Allocate** | Kiểm chứng/rà guard của Listing Phase1 cùng `TX-ALLOCATE`: PAUSE-first vs alloc-first, capacity downsize vs alloc, hardware edit khi nonterminal, RESUME only permits later schedule. Không sửa API Listing nếu không qua change control. | Barriers cho cả hai commit orders; no overcommit, no forbidden edit/alloc when PAUSED. |
| `TV4-P2D-12` | **Cancel/Submit/two-Managers races** | Cùng TV2/TV5 test Cancel-first và Allocate-first, hai Manager chọn cùng head; replay key cũ/body cũ trên PAUSED vs key mới; không cho `SKIP LOCKED` ở Job. | Job trạng thái hợp lệ; đúng 1 Allocation/Attempt/Outbox; Cancel QUEUED-only; retained replay 200. |
| `TV4-P2D-13` | **PAUSED retry / outbox integration** | Cùng TV1/TV2/TV5 xác nhận resend same Attempt/event/payload, lease fencing, probe+hard deadline, không reserve lần hai; chỉ test/ACK contract, **TV4 không code HTTP client/Outbox SQL**. | Lost ACK khi PAUSED không phát sinh Allocation mới, stale owner không ACK lease mới. |
| `TV4-P2D-14` | **Planned key-rotation readiness** | Thiết kế test hai thứ tự Worker advisory, quiesce hai key, drain RUNNING, stale K1 proof sau K2 và restore K1 khi rollback; TV3/TV5 cung cấp policy, TV2 khóa/read. | Không bypass FIFO hoặc đổi counter khi signer chưa sẵn sàng; runtime `NOT_RUN`; TTL/restart/compromise còn mở. |
| `TV4-P2D-15` | **Unit/property tests** | Test chính sách thuần: FIFO/head oversized, gap trong seq, PAUSED vs ACTIVE, cancellation, scan wrap, cursor restart, idempotent retry view; fake test chỉ chứng minh policy. | `P2D-TX/SCHED` liên quan PASS theo test riêng; không gán fake unit PASS cho PG concurrency. |
| `TV4-P2D-16` | **PG & E2E concurrency acceptance** | Trên disposable PostgreSQL16 có role native: 2+ sessions, deterministic barriers cả hai commit orders, snapshot Job/Listing/Allocation/Attempt/Outbox; rollback injection, commit lost-ACK, Manager restart, 2 Manager, resource saturation. | `P2D-DRT-01..15` + `P2D-RACE-01..08` + DBTX/API-LIST liên quan đạt PASS/ghi BLOCKED đúng nguyên nhân; CI exact SHA. |
| `TV4-P2D-17` | **Bàn giao PR và review** | Sau docs gate, mỗi task dùng nhánh/PR riêng; cung cấp policy files, interface port SHA, config/metrics đã ACK, SQL/race evidence theo đúng phạm vi, test manifest và known findings; re-review độc lập khi đổi head. | Mỗi task được xét merge khi đủ cổng; full integration cần đủ acceptance toàn phần. Không tự approve/merge. |

**Cảnh báo giao việc:** `TV4-P2D-08` là **phối hợp tích hợp và test** giao dịch của TV2, không phải lệnh TV4 cùng viết một implementation SQL khác. `TV4-P2D-10` là policy quét; runtime scheduling loop của TV1. `TV4-P2D-13` là acceptance contract, không chuyển ownership Dispatch. Không code những task phụ thuộc chưa được ACK.

## 7. Thuật toán chuẩn phải bàn giao cho TV1/TV2 — pseudocode

> Chỉ là đặc tả được duyệt ở mức ý tưởng, **chưa phải signature Python/SQL**. Cần ACK typed port, database role, error/retry, budgets và signer-readiness trước khi hiện thực.

```text
Scheduler loop do TV1 sở hữu:
  mỗi tick (default configurable 2s):
    take <= agreed_max_listings/time budget from stable rotating Listing-ID hint scan
    for listing_id in inspected scan:
       advance volatile cursor after this Listing regardless of EMPTY/BLOCKED/PAUSED/LOCK_BUSY
       wrap at end; after restart start a conservative fresh DB scan
       use queued-work hint only to avoid unnecessary G1 calls, never as authorization
       readiness = bounded_G1_proof_per_worker(timeout, concurrency_budget, TTL_cache)
       invalidate cache on expiry/Manager restart/active-key or approved lifecycle change
       if missing/expired/key-mismatched readiness:
          report Blocked(SIGNER_NOT_READY); continue; revisit after wrap/later cycle
       result = await bounded_executor_call(TV2.allocate_one_listing, listing_id, readiness)
       log only safe typed result; continue other Listings
    ensure Dispatch & Finalization workers/DB pool are not starved

TX-ALLOCATE do TV2 viết (1 Listing, 1 UoW, READ COMMITTED):
  begin with one native gpm_manager_app Session
  LOCK Worker advisory shared; LOCK/recheck Listing; SELECT+LOCK true enqueue_seq head
       (NEVER SKIP LOCKED Job head)
  build immutable scalar PolicySnapshot; no ORM/Session escapes
  assessment = TV4 pure policy:
       ELIGIBLE | EMPTY | HEAD_DOES_NOT_FIT | LISTING_NOT_ACTIVE
  EMPTY -> COMMIT no-op -> Noop(NO_QUEUED_HEAD)
  LISTING_NOT_ACTIVE -> COMMIT no-op -> Blocked(LISTING_NOT_ACTIVE)
  HEAD_DOES_NOT_FIT -> COMMIT no-op -> Blocked(HEAD_DOES_NOT_FIT)
  missing Listing / bounded lock timeout -> ROLLBACK -> Noop(LISTING_NOT_FOUND | LOCK_BUSY)
  recheck sole active key + worker/key/fingerprint + DB-time expiry under locks
  mismatch -> COMMIT no-op -> Blocked(SIGNER_NOT_READY)
  // ELIGIBLE does not mean committed and cannot authorize dispatch
  t = PostgreSQL clock_timestamp() after locks
  guarded UPDATE gpu_listings.allocated_gpu_count and exact Job QUEUED -> RUNNING
  INSERT one active Allocation; one immutable Attempt; one Outbox event
  finish_due_at = t + duration_seconds
  hard_deadline_at = finish_due_at + 120 seconds
  COMMIT ALL; output Allocated(job_id, attempt_id, event_id)
  if exception BEFORE definite rollback: rollback whole UoW
  if CommitOutcomeUnknown(listing_id,job_id,attempt_id,event_id): stop and call
      reconcile_allocation(expected=(listing_id,job_id,attempt_id,event_id))
      complete exact graph -> AllocationCommitted (even terminal/released)
      absent graph + Job QUEUED -> AllocationNotCommitted
      partial/contradictory/wrong ID -> AllocationUnknown; alert; no blind retry
  // no proof/HTTP and no second DB Session inside locks/UoW
```

**Lưu ý về return/no-op:** chỉ dùng một bộ UoW outcomes của `B-IF-06`; các tên `ALLOCATED/EMPTY_QUEUE/BLOCKED_CAPACITY/INACTIVE_LISTING` không phải boundary thứ hai. EMPTY/head không fit/inactive/signer-not-ready COMMIT no-op; missing Listing/LOCK_BUSY rollback. `DependencyUnavailable` là exception đã sanitize. Không kéo live SQLAlchemy Session/locked ORM qua thread/coroutine. Xem [Phase 2D §7.3/7.8](../../../architecture/phases/phase2/Phase_2D_v0.9.md#73-single-uow-tx-allocate-and-proposed-result-port); pseudocode chưa phải signature Python/SQL được duyệt.

## 8. Truth table cạnh tranh — mỗi race phải kiểm tra cả hai thứ tự commit

| Race/test | Nếu A commit trước | Nếu B commit trước | Bằng chứng bắt buộc |
|---|---|---|---|
| `PAUSE ↔ ALLOCATE` | PAUSE trước: Listing PAUSED, Job giữ QUEUED, không Allocation | ALLOCATE trước: Job RUNNING + one reservation, PAUSE không hủy RUNNING | Listing+Job+Allocation+Attempt+Outbox snapshots |
| `CANCEL ↔ ALLOCATE` | CANCEL trước: CANCELLED, không reserve/Attempt/Outbox | ALLOCATE trước: RUNNING, Cancel QUEUED-only trả conflict | Two session barriers + exact status/error |
| `CAPACITY PATCH ↔ ALLOCATE` | PATCH trước: scheduler recheck capacity/queued max | ALLOCATE trước: PATCH không thể giảm dưới allocated hoặc max QUEUED | Counter và `MAX(QUEUED)` sau locks |
| `HARDWARE PATCH ↔ ALLOCATE` | Nếu có QUEUED/RUNNING, hardware thay thực sự bị từ chối | Sau allocate vẫn RUNNING nên edit vẫn bị từ chối | No-op cùng hardware hợp lệ, changed bị 409 |
| `RESUME ↔ ALLOCATE` | RESUME commit trước: scheduler xét FIFO/capacity vào tick phù hợp | ALLOCATE lock trước trên PAUSED: no-op, RESUME sau không làm backdated allocation | Không tạo Job hay Outbox lúc PAUSED |
| `2 MANAGERS ↔ SAME HEAD` | Một claim/commit hợp lệ | Manager đến sau re-read latest FIFO/state | Exactly one per Job, counter matches ACTIVE sum |
| `CANCEL HEAD ↔ NEXT FIFO` | Cancel xóa head khỏi QUEUED, next QUEUED trở thành head | Allocate đã thắng -> không được Cancel RUNNING | Không skip head chỉ vì lock/capacity |
| `K1→K2 ROTATE ↔ ALLOCATE` | Exclusive key lock thắng: hai key chặn allocation; K2 activation làm stale K1 proof bị từ chối | Shared allocation thắng: rotation chờ commit và drain RUNNING trước activation | Cả hai thứ tự, stale proof/fingerprint/expiry; `NOT_RUN`, exact ACK pending |
| `PAUSED ↔ DISPATCH RETRY` | Đã RUNNING: retry cùng Attempt/outbox/payload hợp lệ | New allocation trên PAUSED: bị chặn | No duplicate allocation; hard deadline không dời |
| `COMMIT ACK LOST ↔ RETRY` | Durable exact graph: `AllocationCommitted`, kể cả terminal/released | Absent+QUEUED: `AllocationNotCommitted`; partial/wrong Event ID: `AllocationUnknown` | expected 4 IDs, fresh Session, không blind retry/double count |

## 9. Interface/ACK matrix — còn phải đóng trước triển khai

| Mã chuẩn | Nội dung cần chốt và producer → consumer | Người phải ACK | Tình trạng hiện tại |
|---|---|---|---|
| `D-IF-01` | TV4 pure snapshot assessment → TV2 mapping/TV1 Scheduler; #46 `0ca059c`, #47 `001619d` | TV1+TV2+TV4+TV5 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-02` | TV2 one-UoW/native role/Worker→Listing→Job/cleanup/reconcile → TV1+TV4 | TV1+TV2+TV4 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-03` | TV4+TV1 stable rotating cursor/advance/wrap/revisit → TV2 integration | TV1+TV2+TV4 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-04` | TV1 2s config + proof/scan/time/executor/DB budgets → TV2+TV4 | TV1+TV2+TV4 | `PENDING_PARAMS / MEASUREMENT` |
| `D-IF-05` | TV1/TV2/TV5 same-Attempt retry + proposed separate `B-IF-06R` → TV4 PAUSED boundary | TV1+TV2+TV4+TV5 | `TV4_ACK_COMPATIBLE / D-19 OPEN` |
| `D-IF-06` | TV2+TV4 Cancel/Pause/Resize vs allocate mapping → TV5 lifecycle | TV2+TV4+TV5 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-07` | TV3 G1/key + TV2 locked recheck + TV1 bounded calls → TV4/TV5 | TV1+TV2+TV3+TV4+TV5 | `APPROVED_DESIGN_DIRECTION_CONDITIONAL / EXACT_SHA_ACK_PENDING` |
| `D-IF-08` | TV2/TV5 release/finalizer/reconciliation → TV1/TV4; #46 `0ca059c`, #50 `edb247f8` | TV1+TV2+TV4+TV5 | `PENDING_EXACT_HEAD_ACK` |
| `D-IF-09` | TV1/TV2 baseline/native roles/audit disposition → TV4/TV5 | TV1+TV2+TV4+TV5 | `BASELINE_RECORDED / AUDIT_DISPOSITION_PENDING` |

**ACK mẫu:** `producer SHA + consumer SHA + interface fields + typed errors + reviewer account + scenario IDs + disposition (ACK_COMPATIBLE / ACK_WITH_ACTIONS / BLOCKED)`. `PENDING` không được thay bằng PASS dựa vào cùng một người tự xác nhận PR mình viết. Không dùng ACK của TV1 thay thế người consumer bị ảnh hưởng.

**D-19 boundary:** TV4 ghi `ACK_COMPATIBLE` cho semantics PAUSED/same Attempt-event-payload và việc tách repair khỏi allocation, **không** approve D-19. Normal Outbox claim/ACK/retry là Outbox-only. `B-IF-06R` là port đề xuất riêng với Listing → Job → Outbox, repair fence/lease riêng và HTTP sau COMMIT; không tạo Allocation/Attempt/Event, không kéo dài deadline. TV4 không sở hữu repair SQL, columns/grants/guards, HTTP client hoặc Finalizer. TV1/TV2/TV5 và lead vẫn phải phê duyệt L2 trước code.

## 10. Bài kiểm thử và tiêu chí nghiệm thu (tất cả `NOT_RUN`)

### 10.1. Existing accepted test families

| Nhóm | Ý nghĩa | Trạng thái |
|---|---|---|
| `P2D-TX-01..12` | FIFO order, capacity, multi-table atomic rollback, no head bypass, reservation/recovery | `NOT_RUN` |
| `P2D-RACE-01..08` | PAUSE/CANCEL/ALLOCATE cả hai thứ tự, two Managers, oversized head, rotation, PAUSED replay | `NOT_RUN`; rotation-dependent case `BLOCKED` nếu key contract chưa ACK |
| `P2D-SCHED-01..05` | Default 2s/configurable, bounded scan, fairness, no loop-starvation, restart | `NOT_RUN`; numeric budget `PENDING_PARAMS` |
| `DBTX-02..06`, `API-LIST-13..15` | DB guard, existing Listing Submit/Pause/Resize regressions và Phase2 Allocate races | Ghi kết quả **từng nhánh**, không gộp mock PASS |

### 10.2. 15 deep-review acceptance tests không được bỏ sót

| ID | Stimulus cụ thể | PASS oracle (mới là thiết kế, chưa test) |
|---|---|---|
| `P2D-DRT-01` | Cùng `submitted_at`, khác `enqueue_seq` | Xét đúng Job có seq thấp hơn dù UUID đảo thứ tự |
| `P2D-DRT-02` | Listing lock bận và queue có nhiều Job | Timeout -> `LOCK_BUSY`, rollback, xét Listing khác rồi quay lại; không `SKIP LOCKED` Listing/Job |
| `P2D-DRT-03` | Head cần 4/free 2, Job sau cần 1, Listing khác đủ | Cả hai Job ở Listing bị block vẫn QUEUED; Listing khác tiến được |
| `P2D-DRT-04` | Cancel true head trước tick | Tiếp theo dùng QUEUED head còn lại, không allocation cũ |
| `P2D-DRT-05` | Inject DB lỗi giữa counter/job/child inserts | Rollback toàn bộ, không partial GPU/Attempt/Outbox |
| `P2D-DRT-06` | COMMIT thành công nhưng mất ACK; reconcile expected 4 IDs và biến thể Event ID sai | Exact graph `Committed`; sai Event ID `Unknown`; không reserve/Attempt/Event thêm |
| `P2D-DRT-07` | Allocate→PAUSE, mất dispatch ACK | Retry same Attempt/event/payload; không tăng counter/lùi deadline |
| `P2D-DRT-08` | Resize và Allocate cả hai commit orders | `allocated<=total`, queued max guard đúng, không 409 sai ưu tiên |
| `P2D-DRT-09` | Listings > budget, một Listing lock liên tục, oversized head, thêm Listing hai phía cursor, wrap/restart | Cursor tiến sau mọi outcome, wrap/discover rows mới, Listing hợp lệ không bị đói |
| `P2D-DRT-10` | SQL + G1 proof chậm khi Dispatch/Finalizer due | Timeout/concurrency budget giữ; Scheduler không monopolize HTTP/executor/DB pool |
| `P2D-DRT-11` | Hai Manager claim cùng Listing/head | Không overcommit, một Attempt/Allocation/Outbox cho Job |
| `P2D-DRT-12` | Planned K1→K2 rotation có Job RUNNING/QUEUED | Quiescent policy đúng; `BLOCKED` nếu contract chưa ACK |
| `P2D-DRT-13` | Crash trước/sau COMMIT; complete/absent/partial/wrong-ID graph | `NotCommitted/Committed/Unknown` đúng contract, không blind retry |
| `P2D-DRT-14` | Native `gpm_api_app` thử Manager UPDATE; Manager role thử legal allocation | API không có quyền allocate; Manager theo least privilege và SQL emitted |
| `P2D-DRT-15` | Lease Outbox cũ hết hạn rồi bị worker mới claim | Fencing không cho stale worker ghi đè; không duplicate business effect |

### 10.3. Bằng chứng bắt buộc mỗi test

- PostgreSQL **16 disposable safety-marked**, fixture cách ly, `current_user/session_user` native **gpm_api_app/gpm_manager_app**, không dùng owner superuser DSN cho positive tests.
- Hai hoặc nhiều connection thật; barrier kiểm soát ai giữ Listing/Job lock và **cả hai commit orders**. Không dựa vào timing may rủi.
- Lưu before/after committed rows: Listing `(status,total,allocated)`, QUEUED head `(job_id,enqueue_seq,status,requested)`, `allocations`, `execution_attempts`, `execution_outbox`; khi test release bổ sung signed/result/effect rows.
- Bằng chứng về cấu hình: scan interval, max Listings/cycle, time budget, executor workers, DB pool/statement+lock timeout, test database revision và exact Git SHA. Không đặt số để giả lập thành công khi chưa được ACK.
- Phân loại `PASS / FAIL / BLOCKED / ERROR / NOT_RUN` đúng nội dung **đã thật chạy**. Test rotation/signer readiness chưa có chính sách được phê duyệt phải `BLOCKED`, không được xóa test để CI xanh.
- Test riêng one-shot isolated PostgreSQL cluster hoặc fixture bảo đảm khôi phục credential cluster-wide. Dùng schema teardown đơn thuần không hoàn nguyên mật khẩu role do các test cũ có thể thay đổi.
- Test Manager + Dispatch + Finalize integration do TV1 chủ trì, TV4 góp test oracle; **không bắt buộc TV4 tự viết toàn bộ integration runtime**.

## 11. Gates và thứ tự công việc để tránh xung đột

**G0 — Freeze baseline:** #39 đã merge, #42 đã vào main qua #39; source SHA/migration graph và Phase1 barrier evidence ở đầu file/§3.2. Lead/TV2 còn xác nhận audit disposition, actual installed DB revision và native roles/triggers. Không ghi lại #39 là Draft hoặc barrier đã có là chưa có.

**G1 — Hoàn thiện và merge docs trước code:** TV4 tự review/sửa hai file trên nhánh `docs/phase2d-design-review`; TV2 review chéo FIFO/TX-ALLOCATE, TV1 điều phối và review tương thích, TV3/TV5 ACK phần bị ảnh hưởng. Chốt câu hỏi ở Phase 2D §7.8 (`D-IF-01..09`, erratum, no-op, resource budget, signer). Chỉ khi không còn vấn đề chặn, đủ review độc lập và nhóm trưởng chốt mới merge PR docs. Tự review/Codex không thay review chéo; design tests `NOT_RUN` không bị báo thành PASS.

**G2 — Code theo từng task, sau G1:** lấy main mới nhất đã merge docs, xác nhận phụ thuộc của task và tạo một nhánh/PR riêng cho task đó. Policy thuần cũng phải chờ G1; không code trước rồi dùng CI để hợp thức hóa. TV4 không viết SQL TX-ALLOCATE thay TV2. PR #45 giữ Draft/HOLD; sẽ được phân loại lại theo một task sau docs gate, không tự động dùng làm nhánh triển khai cả Phase.

**G3 — Test đúng phạm vi task:** policy-only có unit evidence; integration sau khi TV2/TV1 sẵn sàng phải có PostgreSQL/native-role/barrier tests tương ứng. Full Phase2D acceptance vẫn cần các `P2D-TX/RACE/SCHED/DRT`, restart/pressure và Phase1 regression được giao. Không lấy policy unit PASS thay PG, hoặc bắt một task chờ test không thuộc phạm vi của nó. Critical skipped/blocked không được coi là PASS.

**G4 — Review/merge từng task:** source+consumer ACK đúng SHAs, review độc lập theo L1/L2 và CI/test đúng head/phạm vi; task đủ cổng có thể merge, không cần chờ toàn Phase. Không tự merge PR mình viết. Sau đó tạo task tiếp theo từ main mới; TV1 điều phối full integration và lead chốt các vấn đề thiết kế còn mở.

## 12. File bàn giao và biểu mẫu báo cáo tiến độ

**TV4 bàn giao khi xong:** policy spec/diagrams, source (sau code gate) và tests, typed port/ACK matrix, code SHA, per-run DB evidence, `P2D-*` manifest, metrics, limitations, review disposition. Tập trung vào ranh giới TV4 thay vì báo cáo code thuộc TV2/TV1 là do mình viết.

```text
[TV4-P2D-HANDOFF v1.2-docs-review]
Docs PR/reviewed SHA / cross-owner ACK / lead decision / merge SHA:
Code task ID (only after docs gate) / source branch/HEAD SHA:
Accepted main SHA / Alembic heads + version / native role identities:
Phase2D FINAL SHA / erratum disposition (allocated_gpu_count):
D-IF-01..09 producer/consumer ACK + source SHA:
Allocation port typed output/error, source TV2 PR:
FIFO ordering proof: listing_id, queue job_id/enqueue_seq, available/blocked:
Scan cadence=2s default; actual approved max_listings/time/executor/DB pool:
Two PG sessions, barrier steps and both commit orders:
DB before/after rows; capacity sum invariant; rollback/unknown COMMIT:
PAUSED RUNNING resend / key readiness dependency:
Test IDs and statuses (PASS/FAIL/BLOCKED/NOT_RUN), CI URLs:
Independent reviewer and remaining findings / merge recommendation:
```

**Kết luận tự review:** đồng bộ hướng D-18/G1 đã duyệt có điều kiện với #46 @ `0ca059c`, #47 @ `001619d`, #49 @ `62bded7`, #50 @ `edb247f`; đây không thay source L2 hay human approval. Còn exact-SHA cross-owner ACK, D-19 repair, numeric proof/scan/resource budgets, TTL/replay/restart, provisioning, incident policy và audit disposition. Toàn bộ runtime Phase2 `NOT_RUN`; docs gate và coding authorization là các quyết định riêng.

## 13. Bàn giao revision theo review TV1 ngày 2026-11-19

| Request | Section/file đã cập nhật | Trạng thái |
|---|---|---|
| `P1-01` pure policy ↔ TX-ALLOCATE | Handoff §2, §7, §9; Phase 2D §2.1, §7.3 | vocabulary/ownership đã freeze ở mức proposal; chờ exact-head ACK |
| `P1-02` bound G1 calls | Handoff §7; Phase 2D §7.2/§7.4 | timeout/cache/concurrency/invalidation đã nêu; số cụ thể `PENDING_PARAMS` |
| `P2-03` scan/fairness | Handoff §7, §10.2; Phase 2D §7.2/§7.5 | cursor advance/wrap/restart/new Listing/locked Listing test đã thêm |
| `P2-04` commit unknown | Handoff §7–§10; Phase 2D §7.3/§7.5 | expected 4 IDs + three outcomes + wrong Event ID test đã thêm |
| `P2-05` D-19 boundary | Handoff §9; Phase 2D §7.4 | TV4 `ACK_COMPATIBLE` only; D-19 vẫn OPEN/không code |
| `P2-06` docs/source state | Header, §3, §9, §11–§12; Phase 2D header/§2.1/§7.1/§7.6–§7.9 | SHAs/conditional labels/open decisions cập nhật |
| `P2-07` tests/handoff | §10 và bảng này; Phase 2D §7.5/§7.9 | giữ toàn bộ test families; Phase2 runtime/PG/concurrency/performance `NOT_RUN` |

**Exact-head ACK cần lấy sau commit:** TV1 cho Scheduler/resource/integration và toàn bộ `D-IF-01..09`; TV2 cho pure-policy mapping, UoW/cleanup/reconcile, races và baseline; TV3 cho `D-IF-07`; TV5 cho `D-IF-01/05/06/07/08`; lead cho independent L2/docs-gate closure. Các mục còn OPEN: numeric budgets, G1 TTL/nonce/replay/restart/unavailable recovery, provisioning identity, compromise response, D-19, D-09 index và audit disposition. Không sửa application/test code, migration/config hoặc PR #45 trong revision này.
