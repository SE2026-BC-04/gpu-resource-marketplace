# HANDOFF TV4 — Phase 2D: Strict FIFO Scheduling, Capacity Allocation & Concurrency

**Owner:** TV4 `@VietNguyen865` — Listing/FIFO **policy owner**, phối hợp tích hợp Manager Scheduler.  
**Version:** `v1.1 — FINAL-DESIGN-ALIGNED / REVIEWED_FOR_OWNER_APPROVAL`, 2026-11-07.  
**Trạng thái:** `ACK_WITH_ACTIONS / AWAITING_LEAD_APPROVAL`; sau khi nhóm trưởng chốt sẽ là `APPROVED_HANDOFF_CONDITIONAL`, **không cấp quyền code**.  
**Thiết kế chuẩn:** `Phase_2D_v0.9.md`, `P2D-GATE-01=APPROVED_DESIGN_CONDITIONAL`; so với 2A v0.9, 2B v1.3, 2C v0.9, 2E v1.8. Nội dung `PENDING_ACK`, `PENDING_PARAMS`, `NEEDS_OWNER_DECISION` vẫn chưa được duyệt tự động.  
**GitHub snapshot đã kiểm tra:** [PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) `open / draft / unmerged`, HEAD `6788505cbb68e09ad08ea2b96728bc6c69e8a32e`, base `main@1d8b1b2c52b759d99a072c3d0d889b375083a8c4`. PR [#42](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/42) **đã merge vào nhánh PR #39**, không phải `main`. PR [#17](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17) và [#31](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/31) đã merged.  
**Phạm vi cập nhật:** chỉ tài liệu handoff/báo cáo, không sửa code, SQL, GitHub/PR hay database; test **Phase 2D `NOT_RUN`**.

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
| FIFO/head-of-line | Quy tắc chọn Job có `enqueue_seq` nhỏ nhất, không skip, classification `EMPTY/BLOCKED/ELIGIBLE`, business oracle | **TV2** viết SELECT/LOCK/UPDATE PostgreSQL đúng thứ tự; TV4 review SQL theo luật FIFO |
| Manager Scheduler | Đề xuất policy quét Listing/cursor, kiểm thử tiến độ/liveness với budget | **TV1** giữ Supervisor, vòng lặp Scheduler, executor, shutdown, config và metrics integration |
| `TX-ALLOCATE` | Invariant, test oracle, contract với UoW, chỉ tích hợp bằng interface được ACK | **TV2** sở hữu một DB Session, transaction, lock, DB time, role/grants, atomic commit, error mapping |
| Listing/Cancel/Resume | Xác nhận tương thích Listing Phase1, race policy và regression test; không mở rộng HTTP API | API Listing và `TX-CANCEL` Phase 1 giữ sở hữu hiện tại; **TV5** xác nhận lifecycle Job/Attempt/Outbox |
| `RUNNING` dispatch retry | Chứng minh PAUSED không làm đổi Attempt và không allocate lần hai | **TV1** Dispatch Loop, **TV2** Outbox lease/fencing, **TV5** Simulator idempotency |
| Key readiness/rotation | Ranh giới tạm PAUSE/quiescence đối với Listing và race với allocation; đề xuất fail closed | **TV3** security/key policy, **TV5** private signing key/Simulator, **TV2** key registry SQL; incident compromise cần quyết định riêng |
| Finalization/release | Đối chiếu conservation sau khi Job terminal, kiểm tra không over/under-release | **TV5** business Finalizer/Reputation, **TV2** atomic release SQL, **TV1** điều phối |

**TV4 không tự:** tạo Scheduler service thứ sáu, bảng mới, migration/GRANT, SQL `TX-ALLOCATE` song song với TV2, đổi API Submit/Cancel, đổi Signed Result V1, sửa token/JWT, xây Finalizer/Reputation, cho Simulator dùng DB, hoặc giữ HTTP call dưới PostgreSQL domain lock. Khi code, dùng **một nhánh/PR cho gói nhiệm vụ TV4** theo quy tắc nhóm; không phân nhánh nhỏ cho từng bài race.

## 3. Nguồn bắt buộc phải đọc — chính xác phiên bản

### 3.1. Năm file FINAL đã được nhóm trưởng chốt có điều kiện

| Thứ tự | File | TV4 phải rút ra điều gì? | SHA256 của file tại thời điểm review |
|---|---|---|---|
| 1 | `Phase_2D_v0.9.md` | `P2D-OPEN-01..03`; FIFO strict; `D-IF-01..09`; `P2D-TX/RACE/SCHED/DRT`; cảnh báo `reserved_gpu_count` | `fdb7f79a1b89b9ed911fddce67da1763ea88a5417ab946a3121f8701f8758c60` |
| 2 | `Phase_2B_v1.3.md` | Native Manager UoW, 6 Phase2 tables, `allocated_gpu_count`, single-commit, `COMMIT_OUTCOME_UNKNOWN`, lock/grant | `27c59f3e2eddc2584fc9c904aacfc7d45aa323b8745ec77eb5775d59b1af3371` |
| 3 | `Phase_2A_v0.9.md` | Manager Scheduling loop; 2s cadence vs Dispatch/Finalizer loops, cursor/queue/executor/DB pool | `2168e036203c1370b56c2ffe7e5633d398266f72423a370254df33273f7162a2` |
| 4 | `Phase_2E_v1.8.md` | one Attempt/Outbox, Simulator dispatch identity, PAUSED RUNNING retry, single terminal/release | `90af557a46a0f7bcb663eb9d17de3a2db866c4c0b2f1e5006a9160eed2d6609f` |
| 5 | `Phase_2C_v0.9.md` | signing-key readiness, planned K1→K2 rotation, key compromise incident chưa chốt | `d92901a412aaaaa3a2e601781b3991019de9eeee1f45b891564a64d3fbd33902` |

**Lưu ý:** Mốc HEAD `44579ed` và thông tin #42 chưa merge ở một số phần lịch sử của các thiết kế là **snapshot cũ**. Sử dụng quyết định nghiệp vụ đã chốt và HEAD quan sát mới của PR #39; không hiểu `APPROVED_DESIGN_CONDITIONAL` là phê duyệt giao diện/API/code mới. Không tự sửa năm file FINAL trong lần handoff này.

### 3.2. Files GitHub phải đọc trên baseline thực tế

- `docs/architecture/phases/phase1d_gpu_listings.md` — Listing lifecycle, `PATCH` hardware, capacity floor, PAUSED, role ownership.
- `docs/design/database-design.md` §§5/9/11 — `jobs.enqueue_seq`, `gpu_listings.allocated_gpu_count`, `allocations`, `execution_attempts`, `execution_outbox`, lock order, constraints.
- `docs/design/api-contract.md` §§7,8,13 — Listing/CANCEL, Submit idempotency, internal dispatch (không thêm endpoint mới cho FIFO).
- `docs/design/test-design.md` — real DB barrier/two-order acceptance; `ADR-002`, `ADR-003`, `ADR-005` — API/Manager DB boundary, durable Outbox, retry/deadline.
- `backend/src/gpu_marketplace/listings/{service,policy,ports}.py`; `backend/src/gpu_marketplace/repositories/listings.py` — Listing row lock, hardware edit khi có QUEUED/RUNNING, downsize dưới `allocated`/`MAX(QUEUED)`.
- `backend/src/gpu_marketplace/jobs/{submit,cancel}.py`, `backend/src/gpu_marketplace/repositories/{job_submit,jobs,commit_outcome}.py` — TX-SUBMIT idempotency, CANCEL serialize với Allocation tương lai, commit-unknown classification.
- `backend/src/gpu_marketplace/manager/service.py` — **hiện còn** `_foundation_idle_runner`, chưa có Phase2 Manager Scheduler.
- `backend/tests/{test_phase1_runtime_http_postgres_e2e,test_listing_repository_postgres,test_listing_d7_postgres,test_jobs_submit_adapter_postgres,test_jobs_cancel_adapter_postgres}.py` — chỉ có baseline Phase1, không phải TV4 Phase2 PASS.
- `backend/migrations/versions/0001_phase1b_baseline.py` đến `0005_listing_d7.py` — snapshot migrations quan sát trên PR39, **không đoán** Phase 2 migration cha cho đến khi #39 được chấp nhận trên `main` và `alembic heads/version` được xác nhận.

**Đã kiểm tra PR:** #17 và #31 merged; #39 Draft/open; #42 merged vào nhánh #39. Không có bằng chứng scheduler `TX-ALLOCATE` đã được triển khai ở HEAD đang xét. CI Phase1 trên #39 không đồng nghĩa các test `P2D-*` PASS.

## 4. Các quy tắc đã duyệt — KHÔNG được mở lại khi code

### 4.1. FIFO nghiêm ngặt **trên mỗi Listing**, không có backfill

Ví dụ Listing L1 có `total=4`, `allocated=2`, còn `free=2`: `J_A` là QUEUED head (`enqueue_seq=10`) cần 3 GPU; `J_B` đứng sau (`enqueue_seq=11`) cần 1 GPU. **Cả J_A và J_B vẫn QUEUED**. Không được cấp phát J_B. Có thể tiếp tục xét FIFO head của Listing L2 độc lập.

- `enqueue_seq` là nguồn xác định accepted order, không dùng `submitted_at`, UUID, Job ID hoặc thời điểm trình duyệt.
- Chọn `QUEUED` head trong **Listing đang khóa**; một Job bị lock hoặc thiếu tài nguyên không được coi là lý do bỏ qua nó để chọn Job sau.
- `FOR UPDATE SKIP LOCKED` **chỉ có thể** dùng cho việc chia các **Listing claims** khi đã được TV1/TV2/TV4 duyệt; **cấm** dùng để nhảy qua Job đầu hàng đợi.
- Nếu head đã `CANCELLED`, nó không còn thuộc tập `QUEUED`; lần xét sau có thể chọn Job QUEUED tiếp theo.
- `total_gpu_count` không được giảm dưới `allocated_gpu_count` hoặc `MAX(requested_gpu_count)` của Jobs đang QUEUED; CPU/GPU được quan sát từ DB sau Listing lock, không từ UI.

### 4.2. Một Listing/một head/một transaction — `P2D-OPEN-01=APPROVED`

Một Scheduler tick có thể xét nhiều Listing nhưng **mỗi `TX-ALLOCATE` chỉ giữ một Listing và tối đa một head**; commit/rollback độc lập. TV2 phải bảo đảm trong **cùng transaction**: Listing `allocated_gpu_count += demand`, Job `QUEUED → RUNNING`, tạo duy nhất `Allocation`, `ExecutionAttempt`, `ExecutionOutbox` cùng IDs ổn định. Thời điểm `started_at` từ `clock_timestamp()` sau lock; deadline `finish_due_at = started_at + duration_seconds`, `hard_deadline_at = finish_due_at + 120s`. **Không gửi HTTP** khi còn giữ Listing/Job lock.

> **Erratum cần đóng bằng ACK TV2+TV4:** thiết kế Phase2D v0.9 có một dòng pseudocode dùng nhầm `reserved_gpu_count`; cột PostgreSQL thực tế và đúng là **`gpu_listings.allocated_gpu_count`**. Handoff này sử dụng tên cột đúng. Không tạo cột `reserved_gpu_count` và không im lặng sửa lại bản thiết kế FINAL đã chốt.

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

Planned K1→K2 rotation theo thiết kế **quiescent**: tạm PAUSE tất cả Listing liên quan, chờ mọi RUNNING Attempt kết thúc, TV2/TV3/TV5 kiểm tra và thay key theo giao thức an toàn, sau đó mới RESUME phù hợp. TV4 cần ngăn **new allocation với key chưa sẵn sàng** theo hợp đồng đã ACK. **Cách xác minh signer-readiness nguyên tử, khóa nhiều Listing và chính sách xử lý khi key bị lộ còn `PENDING_ACK / NEEDS_OWNER_DECISION`; không tự thêm API, bảng, HTTP gọi trong lock hay đọc private key.** Test phụ thuộc chưa chốt giữ `BLOCKED`.

## 5. Sáu nhiệm vụ chuẩn bị trước khi nhóm trưởng cho phép code

| ID | Nhiệm vụ / chủ trì | Việc cần làm cụ thể | Bàn giao / tiêu chí chốt |
|---|---|---|---|
| `TV4-P2D-01` | **Freeze Phase1 baseline** | Kiểm tra trạng thái #17/#31/#39/#42, source SHA đã vào `main`, `alembic heads/version`, Listing ownership/ACTIVE/PAUSED/Capacity, Submit/Cancel replay; ghi open P2 audit/race của #39. | Bảng baseline Git SHA/migration/role & danh sách `PENDING_PHASE1_GATE`; chưa dùng PR39 Draft làm approved main. |
| `TV4-P2D-02` | **Chốt FIFO và capacity oracle** | Đọc `Phase_2D_v0.9`, so thực schema `jobs.enqueue_seq`, phép chọn QUEUED head; xác nhận một Listing/transaction, bảng kết quả QUEUED/PAUSED/Blocked. Báo erratum `reserved_gpu_count → allocated_gpu_count` cho TV2+lead. | Policy spec/decision table và erratum ACK; không đổi FIFO hoặc thêm column. |
| `TV4-P2D-03` | **Freeze `allocate_one_listing` port** | TV4 policy + TV2 UoW + TV1 caller + TV5 Job semantics: input, typed outcome, stable IDs, native role, lock order, timeout, `LOCK_BUSY`, COMMIT unknown, no-op commit/rollback và cách đối chiếu DB sau unknown. | ACK cho `D-IF-01/02/05/06/08`, interface snapshot theo source & consumer SHA; không code trước khi chốt tác động. |
| `TV4-P2D-04` | **Chốt Listing scan/fairness/resource budget** | Cùng TV1+TV2 quyết định stable Listing order, rotating cursor, skip Listing lock, per-tick max Listing/time budget, executor/DB pool/statement timeout, startup/shutdown và metrics. | `D-IF-03/04` ACK, có bộ tham số **được chọn qua review/đo**, không tự gán mặc định ngoài tick 2s. |
| `TV4-P2D-05` | **Chốt race/key readiness** | Lập 2 commit orders cho Pause/Resume/Capacity PATCH/Hardware PATCH/Cancel/Allocate; TV3/TV5 chốt signer readiness, K1→K2, no HTTP under DB lock; phản hồi `X-01/X-04`. | Race truth table, `D-IF-06/07` ACK; companion owner decision về compromised key nếu cần. Test phụ thuộc `BLOCKED` tới khi được phép. |
| `TV4-P2D-06` | **Chuẩn bị deterministic test & code gate** | Chốt fixtures > cycle budget, FIFO head quá lớn, 2 native PostgreSQL sessions + barriers, schema/role safety, expected row snapshots, test IDs, review responsibilities; thu thập quyền code riêng. | Ma trận `P2D-TX/RACE/SCHED/DRT`, kế hoạch test, reviewer + gate; không chạy migration/test phá dữ liệu trên persistent DB. |

**Trước code:** mọi thay đổi giao diện ảnh hưởng người khác cần ACK của owner nguồn và từng consumer. Owner decision về code Phase2 phải ghi phạm vi, branch, dependency; sự đồng ý với handoff chỉ cho phép giao việc ở mức tài liệu.

## 6. Mười một nhiệm vụ triển khai kỹ thuật SAU coding gate

| ID | Nhiệm vụ TV4 | Công việc kỹ thuật cụ thể của TV4 (không lấn ownership) | Đầu ra / điều kiện PASS |
|---|---|---|---|
| `TV4-P2D-07` | **FIFO policy thuần** | Viết/hoàn thiện logic chính sách: thứ tự `enqueue_seq`, chọn first QUEUED, từ chối head over free/INACTIVE, không backfill; quy tắc next Job khi head Cancelled. Không đọc UI snapshot để quyết định. | Tests unit: tie timestamps/UUID vẫn theo seq; head không fit→BLOCKED; Listing khác được xét. |
| `TV4-P2D-08` | **Tích hợp port TV2 `TX-ALLOCATE`** | Cùng TV2 kiểm SQL lock Listing→Job, conditional status/capacity/identity, một UoW; TV4 chỉ implement policy/adapter theo giao diện thống nhất, không tự thêm DB transaction writer. | Một head, một Allocation/Attempt/Outbox và counter delta nguyên tử; DB conservation đúng. |
| `TV4-P2D-09` | **Kết quả typed và lỗi** | Xác định kết quả `ALLOCATED/EMPTY_QUEUE/BLOCKED_CAPACITY/INACTIVE_LISTING/...` (tên chỉ proposal), diễn giải `LOCK_BUSY`, `DEPENDENCY_UNAVAILABLE`, `COMMIT_OUTCOME_UNKNOWN`; chỉ cho TV1 retry theo ACK, không blind retry khi lost ACK. | TV1/TV2/TV5 signoff; unknown COMMIT reconcile từ DB trước quyết định, không duplicate. |
| `TV4-P2D-10` | **Listing scan policy và fairness** | Thiết lập policy stable order, cursor wrap, per-cycle bounded scan và starvation regression; tích hợp với Scheduler loop của TV1 và UoW TV2, không tự tạo supervisor độc lập. | `P2D-SCHED-01..05`, DRT-09/10 PASS khi thực chạy; số scan và DB calls có giới hạn. |
| `TV4-P2D-11` | **Listing PAUSE/RESUME/PATCH vs Allocate** | Kiểm chứng/rà guard của Listing Phase1 cùng `TX-ALLOCATE`: PAUSE-first vs alloc-first, capacity downsize vs alloc, hardware edit khi nonterminal, RESUME only permits later schedule. Không sửa API Listing nếu không qua change control. | Barriers cho cả hai commit orders; no overcommit, no forbidden edit/alloc when PAUSED. |
| `TV4-P2D-12` | **Cancel/Submit/two-Managers races** | Cùng TV2/TV5 test Cancel-first và Allocate-first, hai Manager chọn cùng head; replay key cũ/body cũ trên PAUSED vs key mới; không cho `SKIP LOCKED` ở Job. | Job trạng thái hợp lệ; đúng 1 Allocation/Attempt/Outbox; Cancel QUEUED-only; retained replay 200. |
| `TV4-P2D-13` | **PAUSED retry / outbox integration** | Cùng TV1/TV2/TV5 xác nhận resend same Attempt/event/payload, lease fencing, probe+hard deadline, không reserve lần hai; chỉ test/ACK contract, **TV4 không code HTTP client/Outbox SQL**. | Lost ACK khi PAUSED không phát sinh Allocation mới, stale owner không ACK lease mới. |
| `TV4-P2D-14` | **Planned key-rotation readiness** | Xây dựng test cho PAUSE-all Listings, drain RUNNING, quiescent K1→K2, reopen hợp lệ; TV3/TV5 cung cấp policy/keys, TV2 khóa/read. Chưa có ACK thì làm test design và đánh `BLOCKED`. | Không allocate với signer unavailable, không deadlock/không lộ khóa; không tự kết luận xử lý compromised key. |
| `TV4-P2D-15` | **Unit/property tests** | Test chính sách thuần: FIFO/head oversized, gap trong seq, PAUSED vs ACTIVE, cancellation, scan wrap, cursor restart, idempotent retry view; fake test chỉ chứng minh policy. | `P2D-TX/SCHED` liên quan PASS theo test riêng; không gán fake unit PASS cho PG concurrency. |
| `TV4-P2D-16` | **PG & E2E concurrency acceptance** | Trên disposable PostgreSQL16 có role native: 2+ sessions, deterministic barriers cả hai commit orders, snapshot Job/Listing/Allocation/Attempt/Outbox; rollback injection, commit lost-ACK, Manager restart, 2 Manager, resource saturation. | `P2D-DRT-01..15` + `P2D-RACE-01..08` + DBTX/API-LIST liên quan đạt PASS/ghi BLOCKED đúng nguyên nhân; CI exact SHA. |
| `TV4-P2D-17` | **Bàn giao PR và review** | Một nhánh/PR TV4; cung cấp policy files, interface port SHA, config/metrics đã ACK, SQL/race evidence TV2 cùng kiểm, test manifest, đỏ/green logs và known findings, re-review độc lập. | Lead TV1 xét merge khi dependencies/CI/ACK đủ, không tự approve PR của chính mình. |

**Cảnh báo giao việc:** `TV4-P2D-08` là **phối hợp tích hợp và test** giao dịch của TV2, không phải lệnh TV4 cùng viết một implementation SQL khác. `TV4-P2D-10` là policy quét; runtime scheduling loop của TV1. `TV4-P2D-13` là acceptance contract, không chuyển ownership Dispatch. Không code những task phụ thuộc chưa được ACK.

## 7. Thuật toán chuẩn phải bàn giao cho TV1/TV2 — pseudocode

> Chỉ là đặc tả được duyệt ở mức ý tưởng, **chưa phải signature Python/SQL**. Cần ACK typed port, database role, error/retry, budgets và signer-readiness trước khi hiện thực.

```text
Scheduler loop do TV1 sở hữu:
  mỗi tick (default configurable 2s):
    take <= agreed_max_listings from stable rotating Listing-ID scan
    for listing_id in eligible scan:
       await bounded_executor_call(TV2.allocate_one_listing, listing_id)
       log typed result, advance cursor after inspected Listing
    ensure Dispatch & Finalization workers/DB pool are not starved

TX-ALLOCATE do TV2 viết (1 Listing, 1 UoW, READ COMMITTED):
  begin with native gpm_manager_app session;
  LOCK Listing[list_id] FIRST; recheck ACTIVE + total + allocated
  if INACTIVE: return INACTIVE_LISTING (no mutation)
  SELECT exact earliest still-QUEUED Job by enqueue_seq ASC
       FOR UPDATE (NEVER SKIP LOCKED Job head)
  if none: return EMPTY_QUEUE (no mutation)
  if head.requested_gpu_count > total_gpu_count - allocated_gpu_count:
       return BLOCKED_CAPACITY(head_id) (no mutation, do not try next)
  // signer readiness guard ONLY according to separately ACKed contract
  t = PostgreSQL clock_timestamp() after locks
  UPDATE gpu_listings.allocated_gpu_count += head.requested_gpu_count
        using approved conditional capacity guard
  UPDATE exact Job QUEUED -> RUNNING, set started_at=t
  INSERT one active Allocation; one immutable Attempt; one Outbox event
  finish_due_at = t + duration_seconds
  hard_deadline_at = finish_due_at + 120 seconds
  COMMIT ALL; output ALLOCATED(job_id, attempt_id, outbox_event_id)
  if exception BEFORE definite rollback: rollback whole UoW
  if COMMIT_OUTCOME_UNKNOWN: stop; reconcile stored rows via new trusted session,
      never blindly allocate/reserve again
  // no HTTP, no second DB Session inside domain lock
```

**Lưu ý về return/no-op:** Cách xử lý `commit` hay `rollback` cho các kết quả không ghi dữ liệu, kiểu outcome/exceptions và chiến lược `LOCK_BUSY` vẫn `PENDING_ACK`; pseudocode không tự phê duyệt interface. Không kéo một live SQLAlchemy Session từ thread/executor sang coroutine khác.

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
| `K1→K2 ROTATE ↔ ALLOCATE` | Quiescent pause/drain/key ready trước khi resume | Allocation thắng trước pause thì phải drain RUNNING trước rotation | `BLOCKED` tới khi TV3/TV5/TV2/TV4 ACK recipe |
| `PAUSED ↔ DISPATCH RETRY` | Đã RUNNING: retry cùng Attempt/outbox/payload hợp lệ | New allocation trên PAUSED: bị chặn | No duplicate allocation; hard deadline không dời |
| `COMMIT ACK LOST ↔ RETRY` | Nếu COMMIT đã durable: reconcile and no-op | Nếu definite rollback: retry có kiểm soát theo TV2/TV1 | không double count; evidence ở session mới |

## 9. Interface/ACK matrix — còn phải đóng trước triển khai

| Mã chuẩn | Nội dung cần chốt và producer → consumer | Người phải ACK | Tình trạng hiện tại |
|---|---|---|---|
| `D-IF-01` | FIFO business policy, typed `AllocationDecision`, output head IDs: TV4 → TV2/TV1/TV5 | TV1+TV2+TV4+TV5 | `PENDING_ACK` |
| `D-IF-02` | One UoW sync, native `gpm_manager_app`, Listing→Job lock, commit uncertainty: TV2 → TV4/TV1 | TV1+TV2+TV4 | `PENDING_ACK` |
| `D-IF-03` | Stable Listing cursor, Listing-only `SKIP LOCKED`/progress: TV4+TV2 → TV1 | TV1+TV2+TV4 | `PENDING_ACK` |
| `D-IF-04` | 2s scan config, bounded Listing/time/executor/DB pool: TV1+TV2+TV4 | TV1+TV2+TV4 | `PENDING_PARAMS` |
| `D-IF-05` | PAUSED RUNNING retry same Attempt/event, no reserve: TV1+TV2 → TV5/TV4 | TV1+TV2+TV4+TV5 | `PENDING_ACK` |
| `D-IF-06` | Cancel/Pause/Resize vs allocate error/race, phase1 guard: TV2+TV4+TV5 | TV2+TV4+TV5 | `PENDING_ACK` |
| `D-IF-07` | Signer readiness and planned rotation K1→K2; separate compromise response: TV3+TV5/TV2 → TV4/TV1 | TV2+TV3+TV4+TV5; lead for incident | `PENDING_ACK / OWNER_DECISION_REQUIRED` |
| `D-IF-08` | Release, deadline/finalizer counter reconciliation: TV5+TV2 → TV4/TV1 | TV1+TV2+TV4+TV5 | `PENDING_ACK` |
| `D-IF-09` | Phase1 PR39 baseline audit and R3 Submit-Pause/Resize barrier | TV1+TV2+TV4+TV5 | `PENDING_PHASE1_GATE` |

**ACK mẫu:** `producer SHA + consumer SHA + interface fields + typed errors + reviewer account + scenario IDs + disposition (ACK_COMPATIBLE / ACK_WITH_ACTIONS / BLOCKED)`. `PENDING` không được thay bằng PASS dựa vào cùng một người tự xác nhận PR mình viết. Không dùng ACK của TV1 thay thế người consumer bị ảnh hưởng.

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
| `P2D-DRT-02` | Listing lock bận và queue có nhiều Job | Chỉ skip Listing claim nếu policy cho phép; không skip FIFO head Job |
| `P2D-DRT-03` | Head cần 4/free 2, Job sau cần 1, Listing khác đủ | Cả hai Job ở Listing bị block vẫn QUEUED; Listing khác tiến được |
| `P2D-DRT-04` | Cancel true head trước tick | Tiếp theo dùng QUEUED head còn lại, không allocation cũ |
| `P2D-DRT-05` | Inject DB lỗi giữa counter/job/child inserts | Rollback toàn bộ, không partial GPU/Attempt/Outbox |
| `P2D-DRT-06` | COMMIT thành công nhưng mất ACK | Re-read thấy child rows, không reserve thêm |
| `P2D-DRT-07` | Allocate→PAUSE, mất dispatch ACK | Retry same Attempt/event/payload; không tăng counter/lùi deadline |
| `P2D-DRT-08` | Resize và Allocate cả hai commit orders | `allocated<=total`, queued max guard đúng, không 409 sai ưu tiên |
| `P2D-DRT-09` | Listings > cycle budget, blocked head, Manager restart | Bounded scan và các Listing sau vẫn được xét qua các vòng |
| `P2D-DRT-10` | SQL chậm + Dispatch/Finalizer due | Scheduler không monopolize executor/DB pool; budget/metrics đúng |
| `P2D-DRT-11` | Hai Manager claim cùng Listing/head | Không overcommit, một Attempt/Allocation/Outbox cho Job |
| `P2D-DRT-12` | Planned K1→K2 rotation có Job RUNNING/QUEUED | Quiescent policy đúng; `BLOCKED` nếu contract chưa ACK |
| `P2D-DRT-13` | Crash trước và sau TX commit | Trước không partial; sau giữ một durable allocation/Outbox để recover |
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

**G0 — Phase1 accepted baseline (chưa đạt theo snapshot #39):** PR39 review đầy đủ, xử lý/deferral P2 audit và Submit-vs-Pause/Resize barriers, vào `main`; freeze SHA, Alembic head, roles/triggers. PR42 merge vào PR39 không tự giải quyết gate này.

**G1 — Handoff/Interface review:** nhóm trưởng chốt handoff có điều kiện; TV1/TV2/TV4/TV5 ACK `D-IF-01..09` theo phạm vi, `D-IF-04` có resource budget cụ thể, TV3/TV5 đủ signer/key readiness và owner quyết định incident khi cần. `reserved_gpu_count` erratum phải ghi nhận chính thức để tránh triển khai sai.

**G2 — Coding authorization riêng:** nhóm trưởng cho phép code Phase2 với phạm vi và sequence phù hợp. TV4 không triển khai SQL `TX-ALLOCATE` thay TV2 trước khi TV2 interface ổn định; TV1 Scheduler có thể dùng stub ở unit level để chuẩn bị nhưng không được claim E2E PASS.

**G3 — PostgreSQL acceptance:** triển khai xong TV2 UoW/schema/grants; chạy toàn bộ `P2D-TX/RACE/SCHED/DRT`, native roles, both commit orders, restart, pressure, no-regression Listing/Submit/Cancel Phase1. Không tự merge chỉ vì `pytest` tổng xanh khi test critical skipped.

**G4 — Merge/Integration:** source+consumer ACK đúng SHAs, independent human reviewer theo mức L1/L2, CI exact head, integration with TV1/TV5 proof, no unresolved P0/P1/P2 blockers; lead mới có quyền chốt merge khi các dependency sẵn.

## 12. File bàn giao và biểu mẫu báo cáo tiến độ

**TV4 bàn giao khi xong:** policy spec/diagrams, source (sau code gate) và tests, typed port/ACK matrix, code SHA, per-run DB evidence, `P2D-*` manifest, metrics, limitations, review disposition. Tập trung vào ranh giới TV4 thay vì báo cáo code thuộc TV2/TV1 là do mình viết.

```text
[TV4-P2D-HANDOFF v1.1]
Source branch/HEAD SHA:
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

**Kết luận handoff v1.1:** đủ chi tiết để nhóm trưởng giao chuẩn bị, yêu cầu các cặp owner/consumer ACK và cho thành viên biết chính xác mình phải code/test **sau coding gate**. Những điểm còn chờ không bị tự coi là đã hoàn tất bởi tài liệu: `D-IF-*`, numeric budget, signer readiness, compromised-key policy, erratum nguồn, Phase1 PR39 accepted SHA và toàn bộ test Phase2 `NOT_RUN`.
