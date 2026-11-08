# HANDOFF TV1 — Phase 2A: Manager Runtime & Integration

**Version:** v1.2 — review update after PR #39 merge (2026-11-08; original design snapshot 2026-11-07)
**Owner thực hiện:** TV1 — `@thangSy221105` (Team Lead/Integration Owner)  
**Trạng thái tài liệu:** `REVIEWED_CANDIDATE / NEEDS_OWNER_SIGNOFF`  
**Trạng thái thiết kế tham chiếu:** `P2A-GATE-01 = APPROVED_DESIGN_CONDITIONAL`; 2B/2C/2D/2E cũng `APPROVED_DESIGN_CONDITIONAL`.  
**Trạng thái triển khai:** `NOT_AUTHORIZED_FOR_CODE / PHASE2_RUNTIME_TESTS_NOT_RUN / CROSS_OWNER_ACK_PENDING`.  
**Mục đích:** bàn giao phạm vi, hợp đồng phối hợp, thứ tự thực hiện, kiểm thử và điều kiện nghiệm thu **riêng cho TV1**, không thay thế tài liệu chuẩn hoặc tự mở coding gate.

> **Baseline hiện tại (2026-11-08):** `main@bee832eaf5463df20f6c6815174322871eb6685a` (merge commit PR #44); PR #39 merge commit `aff538f79997c6e2bfcf359b176a82f2cd9ecc53`. [PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) merged; [Actions run #42385995533](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533) trên final head `3482bce3cc9726543b9345a5224d8db1b9fc6454` passed 4/4 jobs. Read-only Alembic graph check found one source head `0005_listing_d7`; this review did not inspect an applied database or run migration. Open [PR #45](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/45) supplies TV4's pure FIFO policy only; open [PR #46](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) proposes TV2 pre-code schema/grants/UoW docs. Neither is merged or an owner ACK for final Phase 2 runtime interfaces. Phase 2 runtime remains `NOT_RUN`.

### Tóm tắt finding của vòng review hiện tại

- **P0/P1:** chưa xác nhận finding tài liệu P0/P1 trên baseline đã đọc; điều này không xác nhận runtime an toàn hay Phase 2 đã chạy.
- **P2:** Phase 2 schema/grants/UoW chưa có trên `main`; TX-ALLOCATE và finalization chưa có DB integration; healthcheck hiện chỉ kiểm tra PostgreSQL; X-01 cần TV2/lead xác nhận; `P2E-CACHE-GAP-01` còn `NEEDS_OWNER_DECISION`; các ACK bên dưới vẫn chờ owner.
- **P3:** sửa đường dẫn target, broken links và các trạng thái PR/baseline đã cũ; báo cáo `REVIEW_CROSS_PHASE_CONSISTENCY_v1.0.md` không có trong repository.

Ma trận đầy đủ input/output, success/error, call order, transaction boundary, owner và status nằm trong [Appendix C Phase 2A](../../../architecture/phases/phase2/Phase_2A_v0.9.md#appendix-c-2026-11-08-cross-owner-interface-review-matrix). Ma trận chỉ là hợp đồng cần review; không đại diện ACK.

## 1. Nguồn bắt buộc đọc — chỉ dùng phiên bản FINAL

Năm file nằm trong gói `Phase2_FINAL_5_FILES_2026-11-07.zip` đã được nhóm trưởng chốt ở mức thiết kế có điều kiện. **Không dùng** 2A v0.8, 2B v1.2, 2C v0.8, 2D v0.8, 2E v1.7 hoặc handoff TV1 v1.1 làm nguồn chuẩn hiện hành.

| Thứ tự | File FINAL | Nội dung TV1 cần nắm và kiểm lại |
|---|---|---|
| 1 | `Phase_2A_v0.9.md` | §2–3: 3 nhóm loop, supervisor/executor; §5–6: deadline và crash; §8–9: integration gate/`P2A-ACC`; Appendix B: 9 interface gates `P2A-IF-01..09` |
| 2 | `Phase_2B_v1.3.md` | 6 bảng Phase 2/1 migration; runtime DB roles/GRANT; một transaction per business operation; Inbox raw-byte/replay, locks và `COMMIT_OUTCOME_UNKNOWN` |
| 3 | `Phase_2C_v0.9.md` | Hai service Bearer độc lập; Signed Result V1; Verifier typed; Worker public/private key provisioning, rotation và compromised-key chưa chốt |
| 4 | `Phase_2D_v0.9.md` | Strict per-Listing FIFO `enqueue_seq`; một Listing/TX; PAUSED; scan mặc định 2 giây; fairness, concurrency và `D-IF` |
| 5 | `Phase_2E_v1.8.md` | Simulator/output `demo-v1-public1`; cache RAM/restart; `VerifiedV1Receipt` → Finalizer; result-ID/candidate, deadline, one-time release/reputation; `P2E-CACHE-GAP-01` |

**Đọc chéo bắt buộc:** `docs/design/{database-design,api-contract,module-design,test-design}.md`, `docs/architecture/decisions/{ADR-002-postgresql-access-boundaries,ADR-003-internal-communication,ADR-004-signed-result,ADR-005-retry-timeout-internal-auth}.md`, `docs/development/{change-control,interphase-change-control}.md`. Dùng đường dẫn có thật trên repo, không đoán file ADR theo tên gọi chung.

**Dấu vết đối chiếu:** báo cáo `REVIEW_CROSS_PHASE_CONSISTENCY_v1.0.md` và sổ phê duyệt được nhắc trong snapshot ban đầu không có trong repository hiện tại; findings/ACK từ các tài liệu vắng mặt đó không thể được xác minh tại đây. Sử dụng các Phase 2 spec, handoff và PR links trong bản cập nhật này. Các đề xuất triển khai chưa được TV2–TV5 ACK vẫn giữ `PENDING_ACK`; không coi một file có chữ `FINAL` là hợp đồng code đã chốt.

## 2. Vai trò và kết quả TV1 chịu trách nhiệm

### 2.1. TV1 **làm**

- Tích hợp một **Manager process** đang có, giám sát **ba nhóm công việc logic**: (1) Scheduler/Allocation, (2) Outbox Dispatch/Retry/Repair, (3) Inbox Verification/Finalization/Deadline.
- Xây dựng (sau coding gate) orchestration, dependency injection, lifecycle, safe shutdown/restart, supervision/fail-fast, executor có giới hạn, backpressure, logging/metrics/Compose wiring.
- Chốt dependency contracts cùng các owner, đo sizing DB/HTTP, cấu hình môi trường và tổ chức kiểm thử liên module (PostgreSQL concurrency, security, restart, full 5-service Compose/E2E).
- Quản lý Phase 1 → Phase 2 baseline, đăng ký rủi ro, điều phối review chéo và nhận human review; không thay chủ sở hữu nghiệp vụ khác.

### 2.2. TV1 **không làm thay**, trừ một thay đổi phạm vi được duyệt riêng

| Miền | Owner thực hiện | TV1 được phép |
|---|---|---|
| Alembic migration, GRANT/REVOKE, SQL/ORM transaction, Outbox/Inbox persistence, lock/commit handling | **TV2** | Gọi interface, review contract, chạy E2E và báo findings |
| Signed V1 parser/JCS/Ed25519 verification, callback service auth/key registry semantics | **TV3** | Wire verifier và auth dependencies; không triển khai verifier riêng |
| FIFO head selection, admission policy, capacity, fairness thuật toán | **TV4** | Trigger scanning, quản lý budget/cursor ở lớp tích hợp theo hợp đồng chung |
| Simulator dispatch semantics, signed output mock, Finalizer/reputation domain policy | **TV5** | HTTP orchestration và gọi Finalizer; không tự tính/rewrite oracle/reputation |
| Public API Login/Listing/Jobs business rule của Phase 1 | Các owner Phase 1 | Chỉ sửa theo change control được cấp quyền và ACK bên bị ảnh hưởng |

**Bất biến kiến trúc:** 5 service đã có (`frontend`, `api`, `manager`, `simulator`, `postgres`); **một** Manager process, không broker, không bảng thứ 19; 10 bảng Phase 1 + 6 bảng Phase 2, hai bảng Dispute/Retention ở Phase 3. Không đưa dispute adjudication/retention purge Phase 3 vào runtime Phase 2. Simulator không kết nối PostgreSQL hay thấy `simulation_references`; không triển khai GPU thật.

## 3. Hiện trạng mã nguồn Phase 1 làm nền — đừng suy diễn code Phase 2 đã có

Các vị trí TV1 bắt buộc đọc trên **HEAD được chốt khi vào coding gate**:

| Đường dẫn repo | Tình trạng/điểm kiểm tra |
|---|---|
| `backend/src/gpu_marketplace/manager/service.py` | Hiện chỉ có `_foundation_idle_runner` và `run_manager`, **chưa chạy scheduling/dispatch/finalization** |
| `backend/src/gpu_marketplace/manager/__main__.py` | Engine + signal handler/stop_event, cần tích hợp lifecycle an toàn và disposal sau khi các DB workers dừng |
| `backend/src/gpu_marketplace/manager/healthcheck.py` | Kiểm tra DB `SELECT 1`, **không phải chứng cứ ba loop còn sống** |
| `backend/src/gpu_marketplace/common/{config,database,logging}.py` | Shared Settings, sync SQLAlchemy/psycopg3, redacted logging; không đổi driver/stack không có quyết định |
| `backend/src/gpu_marketplace/api/app.py` | Một FastAPI app, Auth principal; callback nội bộ tương lai nằm trên API chứ không nằm ở Manager |
| `backend/src/gpu_marketplace/repositories/{jobs,job_submit,commit_outcome}.py` | Tái sử dụng mẫu isolated Session, idempotency/COMMIT-unknown; không sao chép business adapter |
| `backend/src/gpu_marketplace/jobs/reference.py` | `demo-v1-public1` là generator reference Phase 1; **không** phải Simulator signer hoặc signed-result runtime Phase 2 |
| `compose.yaml`, `.github/workflows/foundation.yml` | 5 service, native `gpm_api_app` và `gpm_manager_app` runtime DSN; Phase 2 secret/token/key injection và health semantics cần review |
| `backend/tests/test_phase1_runtime_http_postgres_e2e.py`, `backend/tests/test_auth_session_browser_e2e.py`, `backend/tests/role_credentials.py` | Phase 1 E2E/Auth & role-password test isolation; không gán PASS Phase 2 từ chúng |
| `tools/{compose_smoke,verify_runtime_roles,verify_alembic_head}.py`, `frontend/e2e/phase1-runtime.spec.ts` | Reuse guarded CI/Compose/PostgreSQL/browser harness; kiểm tra quyền test cluster an toàn |

**Nợ Phase 1 cần theo dõi riêng:** owner comment cuối của PR #39 báo cáo đã xử lý `P2-PGROLE`, `P2-LISTING-AUDIT`, `P2-JOBS-AUDIT` và race Submit↔Pause/Resize; run CI trên final PR head xanh 4/4 jobs. Báo cáo này không thay cho independent human re-review. Open PR #45 vẫn ghi nhận role-rejection audit follow-up riêng; nội dung và disposition chưa được xác minh độc lập ở đây. `CR-GPU-INT-01-READY-01` vẫn là L2 proposal chưa có quyết định; Scrypt C1 evidence vẫn là **production gate** riêng. PR #42 đã merge vào #39, do đó phần đó có trong `main`; điều này không tự chứng minh mọi test E2E khác đã dùng helper hay credential drift đã đóng.

## 4. Công việc theo thứ tự — phân biệt trước code và sau code

### A. Chuẩn bị / thiết kế / duyệt phạm vi (`PRE_CODE`; chưa viết Phase 2 code)

| ID | Việc TV1 phải làm | Bàn giao nhị phân/quan sát được | Người xác nhận |
|---|---|---|---|
| `TV1-P2A-01` | Phase 1 baseline đã được ghi nhận: `main@bee832eaf5463df20f6c6815174322871eb6685a`, PR #39 merged, final-head CI run và source graph head `0005_listing_d7`; xác minh applied DB revision/roles theo quy trình TV2 trước DB work | Baseline code/CI evidence đã ghi ở đầu handoff; applied `alembic_version`, role ACL và Phase 2 schema/grants vẫn cần bằng chứng an toàn, không chạy migration trong vòng docs này | TV1 + TV2 + các owner chịu ảnh hưởng |
| `TV1-P2A-02` | Triage các finding #39 trên **HEAD mới**, phân loại fix/waiver/deferral cho audit, race, test credential, readiness; giữ C1 là production gate | Bảng finding ID → actual source/evidence → owner → disposition; không tự đóng bằng CI xanh | TV1, TV2, TV3, TV4, TV5 theo miền |
| `TV1-P2A-03` | Chốt **9 hợp đồng liên thành viên** ở §5; bao gồm typed returns/errors, retry/no-op semantics và owner of transaction | Biên bản `PENDING_ACK → ACK_*` theo file version/SHA của cả producer lẫn consumer; nội dung chưa chốt vẫn `PENDING` | TV2–TV5 + TV1 |
| `TV1-P2A-04` | Đóng các blocker an toàn/hợp đồng `X-01` (sai tên cột), `X-02` (conflict sau cold restart), `X-03` (key compromise), `X-04` (key readiness), `X-05/06` (verifier/Inbox) | Quyết định/errata và cross-owner ACK đúng thẩm quyền; **TV1 không tự sửa schema hay tự chọn chính sách bảo mật** | TV1 điều phối; TV2–TV5 và lead |
| `TV1-P2A-05` | Chốt cấu hình bounded resources và startup/shutdown/health ở §7, lập test oracle trước code | Numeric config register, phạm vi tác động đến DB pool, executor, timeout, lost-ACK & SIGTERM; không thay ADR-005 fixed constants | TV1 + TV2 + TV4 + TV5 (TV3 với security) |
| `TV1-P2A-06` | Quyết định **coding gate riêng**: phạm vi Manager, nhánh/PR, base SHA, dependency, ai review, rollback | Quyết định owner minh thị `AUTHORIZE_PHASE2A_CODE`; không suy ra từ `APPROVED_DESIGN_CONDITIONAL` | Team lead, review theo change-control |

### B. Chỉ thực hiện **sau khi có coding gate riêng** (`IMPLEMENT_AFTER_AUTH`)

| ID | Việc cần triển khai | Kết quả phải chứng minh | Owner thực thi / review |
|---|---|---|---|
| `TV1-P2A-07` | Tạo supervisor ba loop, progress heartbeat, phân loại fatal/transient, bounded cancellation và fail-fast | Không có loop chết/hung mà Manager vẫn báo khỏe; scan rỗng không bị nhầm hang | TV1; TV2/TV3 góp fault taxonomy |
| `TV1-P2A-08` | Nối Scheduler 2s với TV4 policy và **một TV2 UoW trọn vẹn** cho mỗi Listing | FIFO head only; no allocation khi PAUSED; đúng atomic `RUNNING+Allocation+Attempt+Outbox` | TV1 wiring; TV2/TV4 owner nghiệp vụ |
| `TV1-P2A-09` | Nối Outbox lease/ACK/retry/repair bằng DB adapter TV2 và HTTP transport TV5 | Stable event/attempt, 30s fencing, không giữ DB lock qua HTTP; `202` không terminalize | TV1; TV2/TV3/TV5 review |
| `TV1-P2A-10` | Nối Inbox scan/Verifier/Finalizer/Fallback với các interface TV2/TV3/TV5 | Không lock Inbox trước Listing/Job; hết eligible on-time candidates trước fallback; Job/release/reputation once | TV1; TV2/TV3/TV5 review |
| `TV1-P2A-11` | Bảo vệ DB event loop với executor/queue/connection pools bounded, cleanup Session cùng execution context | Không share SQLAlchemy Session qua thread/task; không nghẽn hai loop còn lại | TV1 + TV2/TV4 |
| `TV1-P2A-12` | Wire Compose, service Bearers, Worker signer key injection và process lifecycle theo ma trận §8 | API/Manager/Simulator chỉ nhận đúng secret/DB role; fail closed; no oracle leaks | TV1 + TV3/TV5 |
| `TV1-P2A-13` | Tổ chức PG 2-connection/clock/barrier, fault injection, full 5-service HTTP/Chromium/DB E2E | `TV1-T01..T16` thực thi trên exact SHA, evidence và PASS/FAIL có thể kiểm chứng | TV1 phối hợp TV2–TV5 |
| `TV1-P2A-14` | Handoff implementation, interphase impact, regression, independent human review, merge recommendation | PR/handoff với SHA, CI, review, test matrix; không còn P0/P1/P2 blocker chưa disposition | TV1 + reviewers phù hợp |

**Nguyên tắc nhánh:** ưu tiên **một nhánh triển khai xuyên suốt công việc TV1** (không tự bẻ thành nhiều nhánh nhỏ). Nhánh PR #39 vẫn là Phase 1 integration, không dùng trực tiếp làm Phase 2 branch nếu chưa có quyết định scope/baseline mới.

## 5. Hợp đồng giữa TV1 và TV2–TV5 — chưa có ACK code-level

PR #45 chỉ đưa policy thuần cho review; PR #46 là proposal pre-code. Vì vậy, interface matrix dưới đây là target contract, không phải xác nhận đã tích hợp. Dùng Appendix C của Phase 2A (được link ở đầu handoff) để xem đủ purpose, inputs/outputs, success/error, call order, transaction boundary, owner và trạng thái.

| Mã/Gate | Producer → Consumer | Nội dung cần khóa | Kết quả lỗi/no-op và trách nhiệm TV1 |
|---|---|---|---|
| `X-IF-01` / `P2A-IF-01` | TV4 FIFO + TV2 DB → TV1 Manager | `allocate_one_listing(listing_id)` là **một** UoW, lấy Listing trước Job, `ORDER BY enqueue_seq`, tạo Allocation/Attempt/Outbox atomically | Các kiểu kết quả `ALLOCATED/EMPTY/BLOCKED/PAUSED/CONTENDED/UNKNOWN` mới là **khái niệm**, chưa là tên Python đã duyệt. Không skip head hoặc tự retry unknown COMMIT |
| `X-IF-02` | TV2 Outbox/TV5 payload → TV1 Dispatcher → Simulator | Immutable `event_id`, stable `attempt_id`, đúng `simulation_input={"workload_profile":"demo-v1"}`, 202 ACK chỉ chấp nhận request | Fencing lease `(event_id,owner,lease_version)`; no extra Job/Attempt; no DB locks khi HTTP |
| `X-IF-03` / `P2A-IF-07` | TV5 Simulator → TV3 API ingress + TV2 DB | `SIMULATOR_CALLBACK_TOKEN`, exact original Signed V1 envelope, Inbox commit trước 202 | Raw bytes same result_id 202 duplicate, changed bytes 409; callback không tới Manager trực tiếp |
| `X-IF-04` / `P2A-IF-02` | TV2 Inbox → TV3 Verifier → TV5 Finalizer (+TV1 caller) | Typed verdict có inbox id/hash, persisted context, worker/key identity, strict 11-field V1 JCS/Ed25519 | Không dùng pre-verification snapshot làm quyền COMMIT; recheck under Listing→Job→Allocation→Inbox locks |
| `X-IF-05` / `P2A-IF-03/04` | TV2 UoW + TV5 Finalizer → TV1 | First **valid eligible** Inbox `(received_at,inbox.id)` wins; 1 terminal/release/contribution; invalid candidate REJECTED | Scan bounded **không được** fallback khi còn on-time candidate chưa xử lý; multiple result_id same Attempt không phải exact duplicate |
| `X-IF-06` / `P2A-IF-07` | TV3 key policy + TV5 signer → TV4/TV2 allocation + TV1 wiring | Worker key registration, private-key storage, restart availability, planned rotation and emergency compromise handling | **Không tự đổi tiêu chí `TX-ALLOCATE`** chỉ để kiểm tra key; owner decision required cho biên key-readiness |
| `X-IF-07` / `P2A-IF-05/06/09` | TV1 Supervisor + TV2 DB → TV4/TV5 | Bounded scan, executor/queue, pool, lock/statement timeout, shutdown, health, startup retry | Nonblocking progress; startup fail closed; transient/fatal classification; no unbounded queue |
| `X-IF-08` / `P2A-IF-02/03` | TV2 Inbox/TV3 Verifier → TV5 Finalizer; TV1 caller | Durable candidate locator chỉ **unlocked**, không giữ Inbox row lock khi chờ Listing/Job; canonical sequence và progress pagination | Sau mỗi lock thực hiện fresh re-query/read-committed, no false `SYSTEM_FAULT` do batch limit |
| `X-IF-09` / `P2A-IF-04` | TV1/TV3/TV5 + owner | Cache RAM sau cold Simulator restart không tự phát hiện changed immutable dispatch cùng `attempt_id` | `P2E-CACHE-GAP-01 = NEEDS_OWNER_DECISION`; SQL exactly-once finalization **không thay thế** 409 conflict guarantee |

**Đặc biệt `X-01`:** `Phase_2D_v0.9.md` có pseudocode dùng **`reserved_gpu_count`**, trong khi schema hiện tại đặt tên cột `gpu_listings.allocated_gpu_count`. Open PR #45 ghi TV4 xác nhận dùng tên thứ hai và yêu cầu TV2/lead xác nhận. Trạng thái ở handoff này vẫn `PENDING_ACK`; TV1 không sửa file 2D đã được chốt và không đề xuất tạo cột mới.

**Khác biệt hai cách retry khi Listing PAUSED:** (1) cùng Client/key/body gửi lại TX-SUBMIT trả Job gốc HTTP `200` dù Listing PAUSED — **đã có owner decision** trên #39; (2) một Job đã `RUNNING` được retry dispatch cùng Attempt khi Listing PAUSED — `P2D-OPEN-02`. Không phát sinh **allocation mới** trên Listing PAUSED.

## 6. Ranh giới transaction, deadline và recovery — bất biến không được phá

1. **`TX-ALLOCATE`:** khóa Listing → FIFO-head Job và quyết định capacity trong **cùng** `READ COMMITTED` Session; không chuyển SQLAlchemy Session, locked ORM record hoặc pending transaction qua executor calls. Các effect `RUNNING`, Listing `allocated_gpu_count += gpu`, Allocation, Attempt, Outbox phải COMMIT cùng nhau hoặc rollback tất cả.
2. **Outbox:** claim/ACK/retry dùng **Outbox-only** transaction, `CLAIM_LEASE=30s` + fencing. Không giữ row locks khi thực hiện HTTP. Retry do mất ACK vẫn dùng **cùng** `attempt_id`, `event_id`, immutable dispatch payload. `COMMIT_OUTCOME_UNKNOWN` luôn cần fresh durable reconciliation thay vì blind retry.
3. **Inbox ingress:** API, **không phải Manager**, kiểm tra đúng service Bearer và insert nguyên bản raw envelope vào PostgreSQL; `202` chỉ sau commit. `received_at` là DB time **sau khi khóa Listing→Job**, strict `< hard_deadline_at` cho candidate mới. Same-ID/raw-byte replay giữ nguyên original `received_at` kể cả khi Job đã terminal.
4. **Manager consumption:** unlocked locator để tìm IDs, sau đó lấy domain locks **Listing → Job → Allocation → Inbox candidate** trong transaction thích hợp. Typed verdict của TV3 có thể lập trước lock, nhưng TV2/TV5 phải re-read/revalidate persisted evidence + Job/Attempt/key-binding trước business commit. Không khóa Inbox trước khi chờ Listing/Job.
5. **First valid terminalization:** xếp on-time candidates theo `(received_at, inbox.id)` (không dùng signed `finished_at`); mark invalid candidate `REJECTED`, chấp nhận tối đa một `signed_results` per Job. Một transaction finalization có terminal Job, accepted result, GPU release, Listing decrement, inbox processed, một đóng góp reputation/aggregate phù hợp. `FAILED/JOB_FAULT` có contribution `NONE`; `SYSTEM_FAULT`/`CANCELLED` không có contribution.
6. **Deadline:** khi Manager resume sau deadline vẫn phải đọc/đánh giá **hết mọi committed on-time Inbox candidate**, kể cả qua nhiều batch, rồi mới có quyền `FAILED/SYSTEM_FAULT`. New callback tại `received_at == hard_deadline_at` là muộn. Callback/fallback chạy cạnh tranh phải test **cả hai commit orders**.
7. **Restart & shutdown:** sau SIGTERM ngừng claim mới, chờ hữu hạn UoW đang chạy, dispose engine **sau** khi DB tasks đã kết thúc/được ghi nhận unrecoverable. `asyncio` cancellation **không** lập tức dừng SQL trong thread. SIGKILL/restart chỉ lấy durable due-state từ DB; giữ once-only constraints, không tin RAM Simulator cache.

## 7. Quản lý cấu hình — số nào đã duyệt, số nào chưa duyệt

| Nhóm | Mặc định/quy tắc | Approval và bằng chứng |
|---|---|---|
| Scheduler scan | **2 giây mặc định có thể cấu hình** | `P2D-OPEN-03 APPROVED_DESIGN`; không phải 2s start SLA |
| Outbox/Receipt poll | **2 giây** | ADR-005 accepted |
| Outbox lease | **30 giây** | ADR-005 accepted; stale owner/version cannot ACK |
| HTTP connect/total timeout | **2s / 5s** | ADR-005 accepted; no DB lock across HTTP |
| Transport backoff | **2,4,8,16,30,30... s** | ADR-005 accepted; trusted persisted due time, no jitter MVP fixture |
| Lost-result repair | `finish_due_at + 10s` | ADR-005 accepted; same logical attempt |
| Hard deadline | `finish_due_at + 120s` | ADR-005 accepted; strict bound for new receipt/dispatch |
| Auth-failure retry | Max **một lần / 30s** đến deadline, fail closed | ADR-005 accepted; reject unauthorized acceptance |
| `max_listings_per_scan`, cursor/rotation, fairness | **PENDING** | TV1+TV2+TV4 ACK; test starvation and slow/locked Listing |
| Executor workers/queue, per-loop slots, SQLAlchemy pool/overflow | **PENDING** | TV1+TV2+TV4+TV5 ACK; workload/stress evidence |
| Lock/statement timeouts, startup retry budget, shutdown drain, Compose grace/restart | **PENDING** | TV1+TV2+TV3+TV5 ACK; crash/fault tests; no fake health |
| Simulator cache/body/concurrency limits | **PENDING** ở TV5 | TV1 reviews downstream impact; không tự chọn giới hạn dù kiến trúc cache RAM đã duyệt |

**Supervisor test invariant:** 3 logical loops có trạng thái nội bộ `STARTING/RUNNING/DEGRADED/STOPPING/STOPPED`; phát hiện crash/stall, không coi scan rỗng là stall. `manager/healthcheck.py` hiện chỉ kiểm DB, do đó TV1 phải chứng minh **supervisor thực sự fail-fast và process exit không thành công** khi một loop bắt buộc lỗi nặng. Một IPC/HTTP health endpoint mới **không** nằm trong design approval hiện hành; muốn thêm cần review riêng. Không tự bật Compose auto-restart rồi coi là đã được approve.

## 8. Ma trận secret/roles tối thiểu khi tích hợp

| Material | Container/process được phép giữ | Không được phép |
|---|---|---|
| Manager DB DSN `gpm_manager_app` | Manager | Frontend, Simulator, logs; API dùng DB role riêng `gpm_api_app` |
| `MANAGER_DISPATCH_TOKEN` | Manager (sender), Simulator (receiver) | API callback, browser JWT |
| `SIMULATOR_CALLBACK_TOKEN` | Simulator (sender), API (receiver) | Manager, frontend, Scheduler business DTO |
| Worker Ed25519 **private key** | Simulator qua approved secret injection/provisioning | PostgreSQL, API, Manager, browser, Git, logs |
| Historical public key `(worker_id,key_id)` | Trusted DB/key registry, TV3 Verifier/Manager với grants hẹp | Tự tin khóa public key do callback gửi lên |
| `simulation_references` / protected oracle | Narrow trusted API write trong `TX-SUBMIT` và Manager trusted read theo approved grants | Simulator, public response, callback, logs |
| JWT **signing secret** và Listing/Jobs cursor secrets | **API only**; browser chỉ giữ JWT **access token** trong RAM SessionStore | Lộ signing/cursor secret cho browser, Simulator/Manager hoặc dùng lại làm service Bearer |

**Internal callback port:** API host-reachable không đồng nghĩa route private; Bearer auth + role/ingress guards phải test. CORS không phải biện pháp authentication. K1→K2 planned rotation phải quiescent và phối hợp Listing/Allocation; **bị lộ private key** là case khác, `NEEDS_OWNER_DECISION`.

## 9. Ma trận kiểm thử nghiệm thu TV1 — thiết kế, **tất cả NOT_RUN**

Đây là **integration-orchestrator test owner**; nơi nghiệp vụ thuộc TV2–TV5 thì TV1 phối hợp tạo setup/evidence và owner tương ứng xác nhận. `TV1-Txx` là mã *đề xuất handoff*, không thay thế `P2A-ACC-*`, `DBTX-*`, `WIRE-*`, `E2E-*` đã duyệt.

| ID | Tầng kiểm thử / stimulus | Binary PASS oracle; bản ghi DB/HTTP bắt buộc | Trace |
|---|---|---|---|
| `TV1-T01` | Config/preflight: missing/mis-scoped token, wrong DB role, missing Phase2 table/grant | Fail closed; không mở vòng business; không để lộ DSN/token; no false ready | `P2A-ACC-01/05` |
| `TV1-T02` | Supervisor: inject fatal task exception, hung task, empty scan | Task fatal/hung được phát hiện, process exit lỗi; empty scan vẫn healthy; không silent exit | `P2A-ACC-05/12` |
| `TV1-T03` | Delay DB Scheduler và HTTP Simulator; Dispatch/Finalize vẫn due | Có bounded forward progress trên các loop còn lại, queue/pool không phình vô hạn | `P2A-ACC-02/11` |
| `TV1-T04` | Same Listing FIFO with head=3 GPUs and available=2, tail needs=1 | No tail allocation; listed counter remains sum active allocations; next scan resume đúng head | `P2A-ACC-04`, `DBTX-03/04` |
| `TV1-T05` | Barrier Pause vs Allocate, Cancel vs Allocate, Resize vs Allocate, both commit orders | One legal winner; no CANCELLED allocated, no capacity violation, PAUSED blocks new allocation | `P2A-ACC-04`, `DBTX-05` |
| `TV1-T06` | Kill before/after TX-ALLOCATE commit, unknown COMMIT fault | All-or-none Job+Allocation+Attempt+Outbox; restart reconciles, no double increment | `P2A-ACC-03/04`, `DBTX-06` |
| `TV1-T07` | Two dispatcher claims, stale lease ACK, lost 202/network timeout | Stable Event/Attempt; stale ACK updates 0 rows; HTTP outside locks; due retries fixed | `P2A-ACC-03`, `DBTX-07` |
| `TV1-T08` | Pause Listing after RUNNING, then lost-result retry | Same RUNNING Attempt redispatched while PAUSED, no new allocation/Attempt | `P2D-OPEN-02`, `P2A-ACC-03` |
| `TV1-T09` | Raw callback same-ID identical vs changed bytes, concurrent duplicate insert | Same bytes: 202 duplicate without changing `received_at`; changed: 409; single Inbox row | `DBTX-08`, `P2A-ACC-07` |
| `TV1-T10` | Cold Simulator restart creates distinct result_id for same Attempt | Multiple eligible candidates possible; only first valid accepted, one terminal/release/reputation | `P2A-ACC-10`, `DBTX-12` |
| `TV1-T11` | On-time Inbox batch #1 invalid, batch #2 valid; Manager wakes after deadline | Valid later candidate wins, no false SYSTEM_FAULT, no lost candidate | `P2A-ACC-08`, `DBTX-09/11` |
| `TV1-T12` | Callback vs timeout fallback at deadline-1µs and equality; both commit orders | On-time committed candidate considered; exactly-at-deadline new callback rejected; one final effect | `P2A-ACC-09`, `DBTX-09/10` |
| `TV1-T13` | Signed SUCCESS/WORKER_FAULT/JOB_FAULT, bad signature, missing key, SYSTEM_FAULT | V1 strict; only valid bound claim terminates; correct counter delta; SYSTEM_FAULT no Worker penalty | `P2A-ACC-06/07`, `ENUM-01..06` |
| `TV1-T14` | Test service-token separation, Simulator no DB/oracle, replay after terminal | Wrong token 401/no Inbox; correct raw duplicate 202; public DTO/redacted logs no protected fields | `P2A-ACC-06`, `API-INT` |
| `TV1-T15` | SIGTERM in sync UoW, SIGKILL and restore; exhausted pool/stalled HTTP | Stop new claims, bounded drain, no early engine dispose, recover from durable DB, no fake clean stop | `P2A-ACC-01/12` |
| `TV1-T16` | Full 5-service disposable PG + HTTP/Chromium, audited mutations, role-password harness safety | Worker Listing → Client Submit → Manager Allocation → Simulator receipt → Finalize → read Job; PostgreSQL invariant and cleanup PASS, PR39 regression unaffected | `P2A-ACC-07`, `E2E-01/02` |

**Test evidence chuẩn:** exact Git commit + base SHA, single Alembic head và `alembic_version`, test class/fixture/seed (không ghi secret), guarded disposable PostgreSQL 16, barrier/fake-DB-clock method, thực tế trước/sau `jobs`, `allocations`, `execution_attempts`, `outbox`, `inbox`, `signed_results`, `job_reputation_contributions`, `worker_reputation_aggregates`, HTTP statuses, redacted logs, CI run link, từng assertion `PASS | FAIL | SKIPPED | BLOCKED | NOT_RUN`, reviewer. **Không coi một test được discover hoặc unit mock PASS là PostgreSQL concurrency E2E PASS.**

## 10. Phân nhóm issues và điều kiện qua từng gate

| Gate | Trước khi mở | State tại lần review này |
|---|---|---|
| `G0 BASELINE` | Phase 1 main SHA/PR #39 final-head CI đã ghi nhận; applied DB revision/roles cần xác minh theo TV2; theo dõi độc lập role-rejection audit, human review và C1 production gate | `PHASE1_BASELINE_RECORDED / DB_AND_REVIEW_FOLLOW_UP_OPEN` |
| `G1 DESIGN_ACK` | X-01 errata; X-02 cold-restart contract và X-03 key compromise owner decisions; X-IF01..09 source/consumer ACK; DB/key readiness/budget parameters | `PENDING_ACK / NEEDS_OWNER_DECISION` |
| `G2 CODE_AUTH` | **Quyết định nhóm trưởng cho phép code riêng** có scope, base và nhánh, review class, rollback plan | `NOT_AUTHORIZED` |
| `G3 IMPLEMENT_AND_TEST` | Sau G2, triển khai công việc `TV1-P2A-07..13`, test T01..T16 và TV2–TV5 integration | `NOT_RUN` (không yêu cầu PASS trước khi viết code) |
| `G4 MERGE` | CI trên exact final HEAD, review người độc lập, ACK theo đúng thay đổi, không còn blocker chưa xử lý, rollback documented | `NOT_READY` |
| `G5 DEPLOY` | Load/recovery/security/observability, C1, TLS/ingress assumption và quyết định release riêng | `NOT_READY` |

**Phân biệt:** Một interface được `ACK_DESIGN` trước code không thay thế `ACK_CODE_COMPATIBLE` sau khi có implementation/test. Thay đổi Phase trước ảnh hưởng Phase sau cần hai phía xác nhận; nếu làm thay khác owner, phải có delegation/change request rõ. Không tuyên bố tất cả G0/G1 phải có runtime Phase 2 PASS — điều đó chỉ xuất hiện ở G3/G4.

## 11. Mẫu comment / báo cáo bàn giao sau triển khai

```text
[HANDOFF TV1 / P2A Manager Integration]
TV1 owner: @thangSy221105
Approved design sources: 2A v0.9 / 2B v1.3 / 2C v0.9 / 2D v0.9 / 2E v1.8
Accepted Phase 1 main SHA / Alembic head / database alembic_version:
Implementation authorization decision / branch / PR / HEAD SHA:
Phase 1 PR39 disposition and outstanding waivers:
Cross-owner design ACKs: X-IF01..09 (links, scope, owner/consumer):
Code compatibility ACKs: TV2=..., TV3=..., TV4=..., TV5=...
Manager 3 loops / bounded executor / DB pool / shutdown config:
Correct runtime roles/secrets injected (REDACTED evidence only):
Tests TV1-T01..T16: PASS=..., FAIL=..., SKIPPED=..., BLOCKED=..., NOT_RUN=...
Critical DB/HTTP/Compose/Chromium test artifacts & CI URL:
Crash/callback/deadline/lock/unknown-COMMIT reconciliation evidence:
Independent human review (reviewer, risk class, reviewed SHA):
Unresolved P0/P1/P2 or scope-approved deferrals:
Recommendation: ACK_COMPATIBLE / ACK_WITH_ACTIONS / BLOCKED
```

**Exit status của bản handoff này:** `READY_FOR_OWNER_DESIGN_REVIEW`, **không** phải `READY_TO_CODE`, `READY_TO_MERGE` hay `PRODUCTION_READY`. Nội dung đã rõ để nhóm trưởng review từng điều kiện; các hợp đồng đang mở vẫn chờ người sở hữu xác nhận.
