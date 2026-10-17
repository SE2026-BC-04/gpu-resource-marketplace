# GPU Resource Marketplace — Software Requirements Specification (SRS)

**Tệp chính:** `docs/requirements.md`  
**Version:** 1.1 (documentation alignment only; no approved MVP scope change)  
**Ngày:** 17/10/2026  
**Trạng thái:** Đã chốt *phạm vi nghiệp vụ và yêu cầu MVP*; chưa xác nhận sản phẩm đã triển khai/đạt kiểm thử.  
**Dự án:** [SE2026-BC-04/gpu-resource-marketplace](https://github.com/SE2026-BC-04/gpu-resource-marketplace)

> **Mục đích:** Đây là tài liệu yêu cầu tổng hợp (single requirements baseline) của MVP. Mọi sửa đổi phạm vi sau này cần cập nhật phiên bản, lý do thay đổi và các FR/NFR/acceptance tests bị ảnh hưởng. Các quyết định kiến trúc còn mở được đánh dấu riêng, không được coi là chức năng đã duyệt.

## Document hierarchy / Source of truth

This is the **main SRS entry point** for scope, actors, business rules, use cases, cross-cutting decisions, and release acceptance. To prevent two independently maintained copies of each requirement:

- **Functional requirement IDs and detailed acceptance criteria:** [functional-requirements.md](functional-requirements.md) (21 P0 requirements across six modules).
- **Non-functional requirement IDs, numeric targets, and test evidence:** [non-functional-requirements.md](non-functional-requirements.md) (33 requirements).
- **Original business vision:** [project-vision-and-scope.md](project-vision-and-scope.md). If an older statement differs from the signed-result/dispute/cancel/pause baseline here, the newer approved decisions in this SRS take precedence pending synchronization of that overview.
- **FR/NFR mapping and architecture readiness:** [fr-nfr-consistency-and-architecture-readiness.md](fr-nfr-consistency-and-architecture-readiness.md).

This file intentionally summarizes FR/NFR instead of duplicating their complete requirement tables. Changes to an individual FR/NFR ID must be made in its owning detailed document and reflected here only when they change scope, rules, traceability or release acceptance.

## 1. Project Vision & Problem Statement

### 1.1. Vision

Xây dựng **GPU Resource Marketplace**, một nền tảng web *prototype* mô phỏng thị trường chia sẻ tài nguyên GPU. **Worker** đăng tài nguyên giả lập; **Client** khám phá GPU Listing và tạo Job; **Manager** tự động lập lịch, cấp phát, ghi nhận Signed Result, xét Dispute Mock và cập nhật Reputation; **Admin** giám sát tổng thể.

Sản phẩm kết hợp đặc tính của marketplace (hiển thị nhà cung cấp, listing và thông tin chi phí mô phỏng) với cơ chế điều phối tài nguyên HPC lấy cảm hứng từ NCI Australia. Giá trị học thuật và kỹ thuật nằm ở **workflow, state consistency, scheduling, concurrency, digital signature verification, dispute và auditable reputation**, không nằm ở thực thi mô hình AI trên GPU thật.

### 1.2. Problem Statement

Kiểm thử một thị trường tài nguyên GPU thật thường cần phần cứng và hạ tầng đắt tiền. MVP tạo môi trường kiểm chứng quy tắc phân bổ và tin cậy kết quả **không cần tài nguyên GPU thật**, với workload mô phỏng có thể tái lập bằng fixture/seed.

### 1.3. Mục tiêu thành công

1. Worker có thể đăng và quản lý tài nguyên GPU giả lập; Client chọn đúng một listing và gửi yêu cầu.
2. Manager phân bổ GPU theo FIFO, không vượt capacity và xử lý đúng Pause/Resume/Cancel.
3. Worker Simulator tạo Signed Result Ed25519; Manager xác minh chữ ký và ngữ cảnh.
4. Client có thể dispute một kết quả đã ký và Manager tự động đối chiếu bằng chứng tham chiếu.
5. Reputation được ghi nhận nhất quán, điều chỉnh chính xác một lần sau dispute và giữ dạng tổng hợp lâu dài.
6. Dashboard hiển thị đúng dữ liệu theo vai trò; hệ thống có kiểm thử phục hồi, cạnh tranh đồng thời và dữ liệu hết hạn.

## 2. Scope, Assumptions & Constraints

### 2.1. Trong phạm vi MVP (In Scope)

- **Worker Registry:** tài khoản Worker tạo sẵn, định danh/public key, quản lý GPU Listings.
- **Job Lifecycle:** Client chọn listing, submit/cancel `QUEUED`, FIFO theo listing, cấp phát và giải phóng GPU.
- **Signed Result:** Worker Simulator ký Ed25519, Manager kiểm tra chữ ký, ngữ cảnh và replay.
- **Dispute Mock:** tối đa một dispute cho mỗi job đủ điều kiện; đối chiếu với deterministic simulation reference; `UPHELD`/`REJECTED`.
- **Reputation:** tính tỷ lệ thành công từ kết quả hợp lệ, lưu bộ đếm lifetime, cập nhật chính xác một lần.
- **Dashboard:** góc nhìn Client, Worker và Admin; read APIs theo quyền và polling đơn giản.
- **Authentication/RBAC:** có đăng nhập cơ bản, một role cố định cho mỗi tài khoản MVP; cấu trúc có thể mở rộng multi-role.

### 2.2. Ngoài phạm vi MVP (Out of Scope)

Không có: real GPU compute/provisioning, AI training thật, container execution/SSH, thanh toán thật, token có giá trị, blockchain, smart contract, public Worker onboarding, xác minh Worker ngoài đời, auto-matching nhiều nhà cung cấp, một Job trải rộng nhiều Workers, Kubernetes, microservices, fair-share/backfilling, xử lý tranh chấp bởi trọng tài, hardware attestation, HA production hoặc realtime dashboard phức tạp.

### 2.3. Ràng buộc định lượng tạm thời

| Mã | Nội dung | Giá trị / Ý nghĩa |
|---|---|---|
| BL-01 | Load test đồng thời | **736** người dùng ảo hoạt động đồng thời; không đồng nghĩa 736 job đang chạy GPU |
| BL-02 | Retention | **23 ngày** cho dữ liệu lịch sử chi tiết sau khi job terminal; tài khoản, listing còn hoạt động và tổng hợp reputation được giữ |
| BL-03 | Change Request | Phản hồi và đánh giá sơ bộ trong **18 giờ**, không phải hoàn thành triển khai trong 18 giờ |
| BL-04 | Simulation | Deterministic, có fixture/seed tái lập; ground truth được tạo trước và bảo vệ khỏi Client/Worker |

Các con số BL-01..03 được nhóm **tạm sử dụng** làm baseline; chỉ tiêu p95/recovery là mục tiêu đề xuất, cần benchmark để xác nhận đạt hay không.

## 3. Stakeholders, Actors & Authorization

### 3.1. Actors

| Actor | Mục tiêu | Quyền chính | Không được làm trong MVP |
|---|---|---|---|
| **Worker** | Cung cấp GPU giả lập | Đăng/sửa/pause/resume listing của mình; xem job liên quan, uy tín | Tự chọn job được cấp phát; sửa receipt/uy tín đã ghi nhận |
| **Client** | Yêu cầu tài nguyên | Xem listing; tạo job; hủy job `QUEUED` của mình; xem result; mở dispute | Sửa listing/job của người khác; buộc Manager gán sang Worker khác |
| **Admin** | Giám sát hệ thống | Xem worker, listing, queues, jobs, receipt/dispute, audit và reputation | Cấp phát job hoặc sửa reputation thủ công |

**Manager** là **internal automated component**, không phải Actor. **Worker Simulator** là tiến trình phần mềm đại diện Worker khi chạy mô phỏng và ký kết quả, không phải người dùng. Stakeholders bổ sung: nhóm phát triển, project owner, giảng viên/người đánh giá.

### 3.2. Account policy

- Tài khoản được seed trong MVP; mỗi tài khoản mang đúng một role `WORKER`, `CLIENT`, `ADMIN`.
- Chỉ Backend API cấp quyền cho người dùng; phân quyền ở mức object ownership, không tin dữ liệu role/worker_id do frontend tự gửi.
- Có thể thiết kế dữ liệu để hỗ trợ multi-role về sau, nhưng không bắt buộc triển khai hành vi multi-role trong MVP.

## 4. Business Rules & State Machines

| ID | Quy tắc nghiệp vụ đã chốt |
|---|---|
| BR-01 | Mỗi GPU Listing thuộc đúng một Worker; một Job chọn đúng **một** Listing của một Worker. |
| BR-02 | Client chọn Listing cụ thể; Manager **không** auto-match hoặc chuyển Job sang Worker khác. |
| BR-03 | Manager scheduling **FIFO nghiêm ngặt trong từng Listing**; có thể cấp tiếp các job liên tiếp nếu đủ capacity, không vượt qua job đầu hàng đợi thiếu GPU. |
| BR-04 | `0 ≤ allocated_gpu ≤ total_gpu`; kiểm tra và cập nhật cấp phát phải nguyên tử. |
| BR-05 | Job hợp lệ bắt đầu ở `QUEUED`; `QUEUED → RUNNING → COMPLETED/FAILED` hoặc `QUEUED → CANCELLED`. Terminal state không đổi lại. |
| BR-06 | Client chỉ có quyền hủy job `QUEUED` thuộc mình; tranh chấp cancel vs allocate chỉ cho một transaction thắng. |
| BR-07 | GPU Listing `ACTIVE ↔ PAUSED`. `PAUSED` không nhận job mới, không cấp phát job `QUEUED`; job `RUNNING` hoàn tất bình thường; `RESUME` tiếp tục queue. |
| BR-08 | Không giảm Listing capacity dưới số GPU đang được cấp hoặc yêu cầu lớn nhất của một job `QUEUED`; không đổi GPU model/VRAM khi còn job chưa terminal. |
| BR-09 | Worker Simulator ký Ed25519; Manager xác minh public key và đúng job/worker/listing trước khi chấp nhận receipt. |
| BR-10 | Chữ ký chứng minh nguồn gốc khóa/tính toàn vẹn, **không** chứng minh kết quả mô phỏng đúng hay có compute thật. |
| BR-11 | Dispute có trạng thái `OPEN → RESOLVED`, quyết định `UPHELD/REJECTED`; tối đa một dispute/job; receipt gốc bất biến. |
| BR-12 | Reputation chỉ dựa vào kết quả đủ điều kiện; lifetime counters sống lâu hơn lịch sử chi tiết 23 ngày. |
| BR-13 | Finalize job, release capacity, xử lý callback trùng, dispute decision và reputation adjustment phải idempotent. |
| BR-14 | `WORKER_FAULT` có thể ảnh hưởng reputation; `JOB_FAULT`, `SYSTEM_FAULT`, `CANCELLED` và receipt không hợp lệ không được tự động phạt Worker. |
| BR-15 | Không thanh toán thật và không có token mang giá trị tài chính. |

### 4.1. State machines

```text
Job:       NEW --validate--> QUEUED --allocate--> RUNNING --success--> COMPLETED
                           |                          \--failure--> FAILED
                           \--cancel (Client)--> CANCELLED

Listing:   ACTIVE <--> PAUSED
            (PAUSED: freeze QUEUED allocations; RUNNING jobs finish)

Dispute:   OPEN --automated resolution--> RESOLVED (UPHELD | REJECTED)
```

Một yêu cầu không hợp lệ bị từ chối trước khi tạo Job; không được tạo Job ở `FAILED` chỉ vì validation lỗi. `SYSTEM_FAULT` là **failure reason** khi Job `FAILED`, không phải trạng thái Job thứ sáu.

## 5. Use Case Catalog & Key Specifications

### 5.1. Use Case Index

| ID | Actor | Use Case | Mức |
|---|---|---|---|
| UC-G01 | All | Login / Logout | P0 |
| UC-W01 | Worker | Register GPU Listing | P0 |
| UC-W02 | Worker | Update / Pause / Resume Listing | P0 |
| UC-W03 | Worker | View Assigned Jobs | P0 |
| UC-W04 | Worker | View Reputation | P0 |
| UC-C01 | Client | Browse GPU Marketplace | P0 |
| UC-C02 | Client | View Listing Details | P0 |
| UC-C03 | Client | Submit Job to Selected Listing | P0 |
| UC-C04 | Client | Track Job Status | P0 |
| UC-C05 | Client | View Signed Result & Usage | P0 |
| UC-C06 | Client | Cancel Queued Job | P0 |
| UC-C07 | Client | Open Dispute for Signed Result | P0 |
| UC-C08 | Client | View Dispute Decision | P0 |
| UC-A01 | Admin | Monitor GPU Resources | P0 |
| UC-A02 | Admin | Monitor Jobs & Queue | P0 |
| UC-A03 | Admin | View Reputation, Disputes & Logs | P0 |

**Lưu ý:** UC-C07 và UC-C08 được bổ sung vào danh mục vì Dispute Mock trở thành module P0 sau khi Use Case list ban đầu được phác thảo. Các tác vụ nội bộ Scheduler/Verifier/Simulation/Finalize không phải Actor use cases độc lập.

### 5.2. UC-W01 — Register GPU Listing

- **Precondition:** Worker đã đăng nhập; tài khoản Worker được seed sẵn.
- **Trigger:** Worker chọn đăng GPU Listing.
- **Main Flow:** (1) Nhập model, VRAM, quantity, giá giả lập nếu hiển thị; (2) Backend kiểm tra quyền và giá trị; (3) Lưu Listing thuộc đúng Worker; (4) Listing xuất hiện trên marketplace ở `ACTIVE`.
- **Exception Flows:** Quantity/VRAM không hợp lệ → reject; user sai role → `403`; DB lỗi → không tạo Listing nửa chừng.
- **Postcondition:** Listing được tạo đầy đủ, có định danh và owner bất biến.

### 5.3. UC-W02 — Update / Pause / Resume Listing

- **Precondition:** Worker sở hữu Listing.
- **Main Flow:** Worker sửa thuộc tính cho phép hoặc chọn Pause/Resume; Backend validate trạng thái/capacity; lưu thay đổi nguyên tử.
- **Alternative Flow:** Pause đóng băng các job `QUEUED`, không hủy hay ngắt các job `RUNNING`; Resume mở lại FIFO.
- **Exception Flows:** Giảm capacity dưới allocations/job đang chờ → reject; sửa model/VRAM khi còn job chưa terminal → reject; Pause cạnh tranh với Allocate → một thứ tự commit hợp lệ, không cấp phát sau khi Pause đã commit.

### 5.4. UC-C03 — Submit Job

- **Precondition:** Client đã đăng nhập, Listing tồn tại và `ACTIVE`.
- **Main Flow:** (1) Client chọn **một** Listing; (2) nhập `gpu_count` và `duration_seconds`; (3) Backend validate quyền, capacity, duration; (4) tạo Job `QUEUED`; (5) Manager xem FIFO; (6) khi đủ capacity, cấp phát rồi chuyển `RUNNING`; (7) Worker Simulator mô phỏng, ký receipt; (8) Manager verify, finalize và release; (9) Client xem Signed Result.
- **Alternative Flows:** Thiếu GPU tạm thời → chờ `QUEUED`; Worker Pause sau khi Job được nhận → tiếp tục chờ, không cấp thêm cho đến khi Resume.
- **Exception Flows:** Listing missing/paused, quantity > total capacity, validation sai → reject trước tạo job; Manager crash → khôi phục theo dữ liệu bền vững; race concurrent → không over-allocation.
- **Postcondition:** Job được lưu chính xác một lần; khi terminal, GPU được release đúng một lần.

### 5.5. UC-C06 — Cancel Queued Job

- **Precondition:** Client sở hữu Job đang `QUEUED`.
- **Main Flow:** Client yêu cầu cancel; Backend chuyển nguyên tử `QUEUED → CANCELLED`.
- **Exception Flows:** Job đã `RUNNING` → `409 Conflict`; job người khác → `403/404` theo API convention; cancel/allocate race → chỉ một thao tác commit.
- **Postcondition:** Không allocation mới cho Job đã cancel; không ảnh hưởng reputation.

### 5.6. UC-C07 — Open Dispute

- **Precondition:** Client sở hữu Job terminal và có **accepted signed result** còn bằng chứng trong thời hạn lưu; chưa có Dispute trước đó.
- **Main Flow:** Client gửi lý do; hệ thống tạo Dispute `OPEN`; Manager đối chiếu immutable simulation reference với signed receipt; ghi `RESOLVED`, decision `UPHELD` hoặc `REJECTED`; nếu cần, điều chỉnh effective reputation classification đúng một lần.
- **Exception Flows:** Bằng chứng hết hạn, đã có Dispute, job chưa đủ điều kiện hoặc Client không sở hữu job → reject; Manager restart → retry an toàn, không nhân đôi reputation.
- **Postcondition:** Receipt gốc không bị sửa; chỉ classification có hiệu lực cho thống kê có thể được điều chỉnh.

### 5.7. Internal Workflow — Job Execution and Verification

- Manager kiểm tra FIFO và capacity trong giao dịch an toàn.
- Worker Simulator mô phỏng deterministic; dùng Ed25519 private key tạo signed payload.
- Manager chỉ chấp nhận receipt có chữ ký và ngữ cảnh hợp lệ. Receipt **được ký hợp lệ nhưng báo sai sự thật mô phỏng** vẫn có thể là đối tượng Dispute Mock; không được nhầm signature verification với oracle correctness check.
- Khi kết thúc Job, Manager ghi result, chuyển trạng thái terminal, release GPU và áp dụng đóng góp reputation trong transaction chống trùng. Receipt không hợp lệ sau retry có thể dẫn tới `FAILED/SYSTEM_FAULT`, không phạt Worker.

## 6. Functional Requirements — MVP P0 index

**Normative detail:** [docs/functional-requirements.md](functional-requirements.md). The following is an index, not a second copy of the detailed acceptance criteria.

| Module | FR IDs | Core behavior |
|---|---|---|
| **M1 — Worker Registry & GPU Listings** | FR-WR-01 ... FR-WR-04 (4) | Seeded Worker identity and signing public keys; Worker-owned GPU listings; edit / pause / resume; Client resource discovery. |
| **M2 — Job Lifecycle & Scheduling** | FR-JL-01 ... FR-JL-06 (6) | Submit on one selected listing; per-listing strict FIFO; atomic capacity allocation; cancel only `QUEUED`; durable simulation completion and failure history. |
| **M3 — Signed Result** | FR-SR-01 ... FR-SR-04 (4) | Worker Simulator signs canonical Ed25519 receipt; Manager verifies cryptographic signature, execution context and replay protection. |
| **M4 — Dispute Mock** | FR-DP-01 ... FR-DP-03 (3) | Client may dispute one eligible retained verified result; Manager deterministically compares hidden reference; immutable signed evidence. |
| **M5 — Reputation** | FR-RP-01 ... FR-RP-02 (2) | Lifetime Worker counters; idempotent contribution and dispute corrections; 23-day evidence retention does not reset counters. |
| **M6 — Dashboard** | FR-DB-01 ... FR-DB-02 (2) | Role-scoped views for Client, Worker and read-only Admin; server-side source of truth. |
| **Total** | **21 P0 FRs** | Six business modules; authentication and RBAC remain mandatory cross-cutting controls from UC-G01 and NFR-S01/S02. |

**Signed Result contract (summary):** an accepted receipt binds at least `schema_version`, `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `outcome`, `failure_reason`, `result_digest`, `finished_at` and `key_id` into a canonical signed payload. Manager verifies the expected execution `attempt_id` and registered Worker public key, not just a mathematically valid signature. Exact canonical byte serialization remains an architecture decision.

**Dispute and retention (summary):** a Client can open at most one dispute for their own terminal Job with an accepted verified receipt and still-retained evidence. An upheld dispute adjusts the effective classification, not the original signed receipt. An unexpectedly unresolved dispute at expiration is an explicit retention exception; the final opening cutoff and maximum exception hold remain open policy details.

## 7. Non-functional Requirements — Baseline v1.0 index

**Normative detail and acceptance tests:** [docs/non-functional-requirements.md](non-functional-requirements.md). All numeric API/recovery values below are **proposed measurable targets**, not achieved performance claims.

| Category | NFR IDs | Count | Baseline summary |
|---|---|---:|---|
| Performance and capacity | NFR-P01 ... NFR-P05 | 5 | 736 active VUs in a documented load profile; proposed 10-minute test; p95 read <= 2s, submit <= 3s, unexpected 5xx < 1%; correctness cannot be sacrificed for speed. |
| Reliability and concurrency | NFR-R01 ... NFR-R08 | 8 | Recover persisted Jobs after Manager restart, proposed recovery <= 120s; atomic capacity updates; safe pause/cancel races; idempotent finalization, dispute resolution and retry. |
| Security and trust | NFR-S01 ... NFR-S07 | 7 | Authentication, RBAC, object ownership, protected Worker private keys, canonical Ed25519 verification, replay prevention, protected simulation oracle and redacted audit events. |
| Data management | NFR-D01 ... NFR-D08 | 8 | Terminal job detail and dependent evidence retained 23 days from `terminal_at`; unresolved dispute exception; retain active identities/listings and lifetime Worker aggregates. |
| Maintainability | NFR-M01 ... NFR-M04 | 4 | Clear module boundaries, automated CI correctness tests, reproducible local setup, environment-specific secrets/configuration. |
| Project process | NFR-O01 | 1 | Acknowledge, triage and initially assess Change Requests within 18 elapsed hours; implementation deadline is separate. |
| **Total** | | **33** | Baseline targets remain subject to evidence from tests. |

**Lifetime reputation invariant:** persist `successful_jobs` and `worker_fault_jobs` per Worker; `success_rate = successful_jobs / (successful_jobs + worker_fault_jobs)`; show `N/A` when there are no eligible samples. Expiration of already-accounted Job history does not decrement these lifetime counters. An upheld dispute replaces one effective per-job contribution atomically before detail expiration. Never silently delete unresolved dispute evidence.

**Reliability boundary:** process-restart recovery assumes PostgreSQL data remains durable and available. It does not promise disaster recovery of a lost database volume or production HA. Private keys in the Worker Simulator are protected separately from the Manager; a valid signature does not prove actual GPU computation or result truthfulness.

## 8. FR–NFR Alignment & Clarifications

| Vấn đề | Các ID liên quan | Quy tắc nhất quán bắt buộc |
|---|---|---|
| Retention vs Reputation | FR-RP-01/02; NFR-D02/D05/D06 | Duy trì `successful_jobs`, `worker_fault_jobs` theo **lifetime**. Cleanup detail 23 ngày **không** trừ lifetime counters. |
| Dispute sau khi Job kết thúc | FR-DP-01/02/03; NFR-D03/D06/D08 | Chỉ mở khi accepted signed receipt và bằng chứng còn thời hạn; không sửa receipt gốc; `UPHELD` thay effective classification đúng một lần. |
| Invalid vs false-but-signed result | FR-SR-03/04; FR-DP-02; NFR-S04/S06 | Chữ ký sai → reject; chữ ký đúng nhưng báo sai reference → vẫn có thể nhận báo cáo và sau đó xử lý qua dispute. |
| Manager restart & retry | FR-JL-03/05; NFR-R01/R04/R08 | Job/capacity/deadline được persist; replay không gây double allocation, finalization hoặc reputation contribution. |
| Pause vs Cancel vs Allocate | FR-WR-03; FR-JL-03/04; NFR-R03/R06 | Không có allocation mới sau Pause commit; cancel được phép chỉ khi `QUEUED`; race phải giải quyết nguyên tử. |
| Key retention & verification | FR-WR-01; FR-SR-01/03; NFR-S03/S04/D01 | Chỉ Worker Simulator giữ private key; lưu public key/`key_id` để xác minh mọi receipt còn thời hạn. |
| Dashboard visibility | FR-DB-01/02; NFR-S01/S02 | Admin chỉ đọc; Client không thấy dữ liệu riêng người khác; Worker chỉ thao tác listing của mình. |

### 8.1. Reputation Lifetime Rule — Normative Clarification

- Với mỗi job có receipt đã xác minh và đủ điều kiện, ghi **một** hiệu ứng reputation của job và cập nhật các bộ đếm lifetime của Worker theo transaction.
- `SUCCESS` đóng góp `(successful_jobs +1, worker_fault_jobs +0)`; `WORKER_FAULT` đóng góp `(0,+1)`; `JOB_FAULT`, `SYSTEM_FAULT`, `CANCELLED`, receipt không hợp lệ đóng góp `(0,0)`.
- `UPHELD` dispute thay đổi **effective category** theo reference; cập nhật phần chênh lệch đúng một lần, giữ signed receipt cũ nguyên vẹn.
- `reputation = successful_jobs / (successful_jobs + worker_fault_jobs)`; mẫu số 0 hiển thị `N/A`, kèm `sample_count = 0`.
- Khi dữ liệu chi tiết hết hạn, chỉ xóa job evidence/contribution detail đủ điều kiện. Không tự động trừ aggregate; người dùng được thông báo rằng lịch sử đã xóa không thể kiểm toán lại theo từng job.

### 8.2. Retention Rules — Normative Clarification

- `expires_at = terminal_at + 23 * 24 hours` đối với job `COMPLETED`, `FAILED` hoặc `CANCELLED`.
- Job `QUEUED`/`RUNNING`, tài khoản, Worker Registry, GPU Listing đang quản lý và lifetime reputation **không** thuộc diện xóa theo TTL job.
- Khi đủ điều kiện, xóa đồng bộ result/dispute/reference/audit phụ thuộc để không còn orphan records; audit logs có TTL riêng 23 ngày kể từ lúc sự kiện tạo.
- Cleanup định kỳ theo giờ, mục tiêu dọn trong vòng một giờ sau mốc hết hạn (chỉ tiêu đề xuất).
- Trường hợp dispute chưa giải quyết khi bằng chứng đến hạn: **ghi nhận retention exception**, ưu tiên hoàn tất resolution, không âm thầm xóa bằng chứng; thời gian gia hạn tối đa cần được chốt trước khi tuyên bố hard-delete SLA.

**Traceability note:** Login/logout (`UC-G01`) is mandatory and is covered at the cross-cutting security level (`NFR-S01`, `NFR-S02`), but it has no dedicated numbered `FR-A*` entry among the 21 module FRs. Before API contract freeze, the team should either add a non-scope-expanding authentication FR ID to the detailed FR document (with a documented count/version update) or explicitly reference UC-G01 and NFR-S01 as its acceptance contract. Do not silently claim 21 FR IDs cover authentication as a separate module.

## 9. Requirements Traceability Matrix (MVP)

| Module | Functional Requirements | Use Cases | Key NFRs |
|---|---|---|---|
| Worker Registry | FR-WR-01..04 | UC-W01..04, UC-C01..02 | NFR-S01..04, NFR-D01 |
| Job Lifecycle | FR-JL-01..06 | UC-C03..06 | NFR-R01..04, NFR-R06..08, NFR-P01..05 |
| Signed Result | FR-SR-01..04 | UC-C05, internal execution | NFR-S03..07, NFR-R04/R07 |
| Dispute Mock | FR-DP-01..03 | UC-C07..08 | NFR-S02/S06, NFR-R05, NFR-D06/D08 |
| Reputation | FR-RP-01..02 | UC-W04, UC-C02, UC-A03 | NFR-D05..07, NFR-R05 |
| Dashboard | FR-DB-01..02 | UC-C04..05, UC-W03..04, UC-A01..03 | NFR-P01..04, NFR-S01..02 |
| Cross-cutting auth/process | FR ownership and login preconditions | UC-G01 | NFR-M01..04, NFR-O01 |

## 10. MVP Acceptance Scenarios (Definition of Done)

1. **Worker listing:** Worker tạo GPU Listing có cấu hình hợp lệ; user sai role/khác chủ sở hữu không thể sửa.
2. **Job workflow:** Client tạo Job trên Listing cụ thể, Manager chuyển `QUEUED → RUNNING → COMPLETED` và giải phóng GPU.
3. **FIFO / Capacity:** Với 4 GPU, A chạy 3 GPU; B chờ 2 GPU; C chờ 1 GPU phía sau B. Scheduler không cấp C vượt B, không bao giờ cấp > 4; sau A xong cấp B rồi có thể cấp C trong cùng lượt xét nếu còn đủ.
4. **Pause / Resume:** Worker Pause → từ chối Job mới, Job QUEUED không được allocate, Job RUNNING hoàn tất; Resume → tiếp tục FIFO.
5. **Cancel race:** Client hủy chỉ Job QUEUED; cancel đồng thời với allocate không dẫn đến Job CANCELLED nhưng vẫn chiếm GPU.
6. **Signed Result:** Worker Simulator ký; Manager verify đúng; chỉnh sửa payload/ký sai/mismatch Worker → reject; receipt replay không làm chốt/ghi reputation trùng.
7. **Deterministic Dispute:** Signed Result có nội dung sai reference nhưng chữ ký đúng → `UPHELD`; khớp reference → `REJECTED`; receipt gốc không bị thay đổi.
8. **Lifetime Reputation:** Đúng một effective contribution/job; dispute adjustment idempotent; expired Job History bị xóa nhưng lifetime counts không đổi.
9. **Restart Recovery:** Tắt Manager khi có job QUEUED/RUNNING, chạy lại vẫn còn job và không double allocate/finalize.
10. **Security:** Client/Worker không đọc hoặc sửa dữ liệu riêng của tài khoản khác; private keys không lộ ở Git, frontend, API hoặc log.
11. **Retention:** Fake clock kiểm thử trước/sau 23 ngày; job active và listing/worker còn hoạt động không bị dọn sai; dispute chưa xong không bị xóa âm thầm.
12. **Dashboard:** Mỗi actor nhìn đúng dữ liệu theo quyền; số liệu phản ánh database, không giả lập cục bộ ở frontend.
13. **Load testing:** Chạy profile 736 VU đã tài liệu hóa; ghi kết quả p95/5xx và kiểm tra invariant; không được tuyên bố đã đạt trước khi đo.
14. **Change Request:** Ticket ghi rõ thời điểm nhận, người phụ trách, đánh giá sơ bộ và phản hồi trong 18 giờ.

## 11. System Architecture Constraints & Status

### 11.1. Đã chốt (approved)

- **Architectural style:** Modular Monolith một repository; **Backend API, Manager và Worker Simulator là các tiến trình riêng**.
- **Database access:** Backend API và Manager cùng truy cập trực tiếp **PostgreSQL**, dùng chung domain/repository modules; **Worker Simulator không có quyền truy cập database**.
- **Ownership:** Backend API tạo/hủy Job và quản lý Worker/Listing theo RBAC; Manager điều phối, finalize receipt, dispute và reputation; Worker Simulator mô phỏng và ký bằng private key.
- **Persistence:** Trạng thái job, allocation và simulation deadline phải persist; PostgreSQL là nguồn dữ liệu chuẩn.

### 11.2. Đang đề xuất, chưa được người dùng xác nhận (architecture design — OPEN)

- **Internal communication:** Manager → Worker Simulator bằng internal HTTP; Worker → API bằng signed-result callback; **Transactional Outbox/Result Inbox** dựa trên PostgreSQL (at-least-once delivery + idempotent business effects).
- **Crypto serialization:** exact canonical JSON encoding, signed payload version/schema, correlation và attempt ID.
- **Failure policy:** timeout, số lần retry, backoff cụ thể, durable deduplication khi Worker Simulator restart.
- **Retention edge:** dispute submission cutoff và hạn tối đa giữ bằng chứng khi có unresolved dispute.
- **Load-test profile:** tỷ lệ loại request, dataset, máy chạy; mục tiêu latency vẫn phải đo.
- **Framework selection:** React/TypeScript + FastAPI + PostgreSQL là **đề xuất**, PostgreSQL và process split đã chốt; framework chưa được xác nhận riêng.

> Các OPEN này không làm thiếu phạm vi FR/NFR của MVP. Đây là quyết định triển khai cần giải quyết trong tài liệu `docs/architecture.md`, `docs/database-design.md` và `docs/api-contract.md`.

## 12. Change Control & Document Ownership

- Tài liệu này là bản **requirements baseline** dùng để chia việc, review code và lập acceptance tests.
- Đề xuất thay đổi: ghi nhận mục tiêu, FR/NFR liên quan, đánh giá tác động phạm vi/thời gian/kiểm thử; phản hồi ban đầu trong 18 giờ.
- Không thay đổi công thức reputation, quy tắc state machine, retention hoặc quyền Actor trong code mà không cập nhật tài liệu và acceptance tests liên quan.
- **Version next:** 1.1 khi có thay đổi nghiệp vụ; kiến trúc tiếp tục có thể phát triển mà không làm đổi version của requirements nếu hành vi bên ngoài không đổi.
