# GPU Resource Marketplace — Functional Requirements (MVP)

**Phiên bản:** Baseline v1.2 (Dispute 7 ngày; chính sách giữ bằng chứng OPEN và cảnh báo/retry đã chốt; 21 FR/6 modules không đổi)  
**Phạm vi:** Marketplace GPU giả lập; không thực thi compute thật, không dùng tiền/token có giá trị.  
**Kiến trúc nghiệp vụ:** Worker cung cấp listing; Client chọn listing và gửi job; Manager tự động lập lịch, xác minh kết quả có chữ ký, giải quyết dispute mock và cập nhật reputation; Admin giám sát.

## 1. Các quyết định đã thống nhất

- Tài khoản được tạo sẵn, mỗi tài khoản có một vai trò `WORKER`, `CLIENT` hoặc `ADMIN`; mô hình dữ liệu có thể hỗ trợ multi-role sau này.
- Worker có thể đăng/quản lý GPU giả lập; Client chọn **một listing cụ thể**, không có auto-matching giữa Worker.
- Manager lập lịch **FIFO riêng cho mỗi listing**; không cấp phát vượt capacity.
- Trạng thái Job: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`; Client chỉ được hủy job `QUEUED`.
- Trạng thái Listing: `ACTIVE`, `PAUSED`. `PAUSED` không nhận job mới, không cấp phát job đang chờ; job `RUNNING` tiếp tục. `ACTIVE` trở lại thì tiếp tục FIFO.
- **Worker Simulator ký kết quả bằng Ed25519 private key**; Manager xác minh bằng public key tương ứng trong Worker Registry.
- **Deterministic Simulation**: hệ thống tạo trước kết quả tham chiếu bất biến cho mỗi job theo fixture/seed có thể tái lập; chỉ backend tin cậy được đọc oracle này, Client không tự đặt kết quả hoặc lỗi Worker.
- Admin chỉ giám sát; Manager là module tự động, không phải một vai trò người dùng.

## 2. Functional Requirements

Tất cả yêu cầu trong bảng là **P0 — bắt buộc trong MVP**. AC (Acceptance Criteria) là tiêu chí kiểm thử, không áp đặt framework hoặc cách thiết kế database.

### M1 — Worker Registry & GPU Listings

| ID | Yêu cầu | Acceptance Criteria |
|---|---|---|
| FR-WR-01 | Quản lý Worker tạo sẵn: `worker_id`, tên, `public_key`, `key_id` và quyền sở hữu tài nguyên. | Manager lấy được public key đúng Worker; private key không xuất hiện trong API/frontend. |
| FR-WR-02 | Worker đăng GPU Listing gồm model, VRAM, tổng GPU, giá mô phỏng (nếu hiển thị). | Từ chối số GPU hoặc VRAM không hợp lệ; listing thuộc đúng Worker đang đăng nhập. |
| FR-WR-03 | Worker sửa cấu hình, tạm dừng và khôi phục listing. | Không giảm capacity dưới số GPU đã cấp hoặc yêu cầu lớn nhất còn `QUEUED`; không sửa model/VRAM khi có job chưa kết thúc. |
| FR-WR-04 | Client duyệt GPU listings, xem thông số, khả năng sẵn có và reputation. | Chỉ listing `ACTIVE` nhận yêu cầu mới; listing `PAUSED` không làm mất lịch sử. |

### M2 — Job Lifecycle & Scheduling

| ID | Yêu cầu | Acceptance Criteria |
|---|---|---|
| FR-JL-01 | Client gửi job vào một listing xác định, nhập `gpu_count` và `duration_seconds`. | Validate quyền, trạng thái listing, thời lượng, giới hạn GPU; job hợp lệ được lưu ở `QUEUED`. |
| FR-JL-02 | Manager xử lý **FIFO nghiêm ngặt theo từng listing**. | Job phía sau không vượt qua job đầu hàng đợi đang thiếu tài nguyên; có thể cấp tiếp nhiều job theo đúng thứ tự nếu còn đủ capacity. |
| FR-JL-03 | Manager cấp phát/giải phóng GPU nguyên tử và tôn trọng Pause. | Không over-allocation dưới tải đồng thời; `PAUSED` không cấp job mới, nhưng cho `RUNNING` kết thúc. |
| FR-JL-04 | Client hủy **chỉ job `QUEUED` thuộc mình**. | `QUEUED → CANCELLED` thành công; `RUNNING` trả xung đột; khi cancel và allocate đồng thời chỉ một thao tác thành công. |
| FR-JL-05 | Manager điều phối Worker Simulator theo kịch bản deterministic và chỉ chốt kết quả đã xác minh (ngoại lệ: timeout `SYSTEM_FAULT`), đồng thời giải phóng GPU. | Chỉ có `RUNNING → COMPLETED/FAILED`; hoàn tất/giải phóng không bị thực hiện trùng khi retry. |
| FR-JL-06 | Lưu dòng thời gian và nguyên nhân lỗi. | Lưu `submitted_at`, `started_at`, `finished_at`; lỗi phân loại `WORKER_FAULT`, `JOB_FAULT`, `SYSTEM_FAULT`. |

### M3 — Signed Result

| ID | Yêu cầu | Acceptance Criteria |
|---|---|---|
| FR-SR-01 | Mỗi Worker Simulator có cặp khóa **Ed25519**; public key/`key_id` đăng ký trong Registry. | Private key chỉ ở nơi lưu secret của backend Worker Simulator; không commit Git, không trả về frontend. Chưa cần giao diện xoay khóa. |
| FR-SR-02 | Worker Simulator produces deterministic execution receipt and signs its canonical byte representation with the Worker Ed25519 private key. | The signed payload binds `schema_version`, `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `outcome`, `failure_reason`, `result_digest`, `finished_at`, and `key_id`. A one-field modification fails verification. |
| FR-SR-03 | Manager verifies Ed25519 signature AND receipt context before accepting the reported outcome. | Check registered public key, matching Worker/Listing, current Job and execution `attempt_id`, `RUNNING` state, valid payload, and unique accepted result. Valid signatures do not establish outcome truthfulness; dispute checks use separate reference data. |
| FR-SR-04 | Từ chối receipt bị sửa, sai Worker hoặc replay; không cộng reputation. | Sửa một trường đã ký → verify thất bại; gửi trùng không gây tác động lặp. Có log; quá thời hạn retry, Manager có thể đóng job là `FAILED / SYSTEM_FAULT`, giải phóng GPU mà không phạt Worker. |

**Giới hạn tin cậy:** Chữ ký chỉ chứng minh receipt đến từ khóa tương ứng và chưa bị sửa; **không chứng minh compute thật hoặc tính đúng đắn của kết quả**.

### M4 — Dispute Mock

| ID | Yêu cầu | Acceptance Criteria |
|---|---|---|
| FR-DP-01 | A Client may open **at most one** dispute for their own eligible terminal Job with accepted verified signed result, retained evidence and trusted DB decision instant in `[terminal_at, terminal_at + 604800 seconds)`. | Accept a properly authorized filing just **before** cutoff; reject at/after cutoff, wrong owner, non-terminal Job, duplicate or absent verified receipt; enforce unique `disputes.job_id` and atomic check/insert; persist server-issued decision timestamp. A timely `OPEN` dispute may resolve after day 7. |
| FR-DP-02 | Manager **tự động** xét dispute dựa trên bằng chứng mô phỏng tham chiếu đã tạo trước và không do Worker/Client kiểm soát. | So sánh signed receipt với expected outcome/digest đã lưu từ kịch bản mô phỏng, không cho Worker/Client sửa; sai lệch → `UPHELD`, trùng khớp → `REJECTED`. |
| FR-DP-03 | Manager persists dispute decision and justification without modifying original signed evidence. | `OPEN -> RESOLVED` with `UPHELD/REJECTED` including adjudication **after the seven-day filing window** for a timely filed dispute; retry is idempotent; pending dispute at the 23-day retention deadline creates an explicit evidence hold until RESOLVED (no hard maximum), with Admin WARNING within 1h of detection, CRITICAL at 24h OPEN, Manager retry each 15 minutes in healthy operation, then deletion of already-expired detail within 1h after resolution. |

**Giải pháp demo tối giản:** Trước khi job chạy, backend lưu một `simulation_reference` bất biến (expected outcome/digest) từ fixture hoặc seed xác định. Worker Simulator nhận chỉ phần input cần để báo cáo, có thể được cấu hình trả về receipt chính xác hoặc receipt sai có chữ ký hợp lệ nhằm tạo tình huống dispute `UPHELD`. Manager so với reference khi giải quyết dispute. Cấu trúc này chỉ mô phỏng tính độc lập giữa nguồn báo cáo và nguồn đối soát, không phải attestation ngoài đời.

### M5 — Reputation

| ID | Yêu cầu | Acceptance Criteria |
|---|---|---|
| FR-RP-01 | Keep lifetime Worker reputation aggregates: `successful_jobs` and `worker_fault_jobs`; show success rate derived from these durable counts. | For verified eligible results, atomically apply at most one effective contribution per Job; exclude cancelled, unfinished, invalid receipt, `JOB_FAULT`, and `SYSTEM_FAULT`. `success_rate=successful_jobs/(successful_jobs+worker_fault_jobs)`; denominator zero -> `N/A`. Expiring Job detail must NOT decrease lifetime totals. |
| FR-RP-02 | An upheld dispute changes effective reputation classification by an idempotent counter adjustment, NOT by changing the signed receipt. | In one transaction, subtract the old per-job contribution, add the corrected contribution (if eligible), and mark dispute settled. Replays do not change the counters again. Historical before/after detail follows the 23-day retention policy. |

### M6 — Dashboard

| ID | Yêu cầu | Acceptance Criteria |
|---|---|---|
| FR-DB-01 | Hiển thị dữ liệu theo vai trò. | **Client:** job, signed result, dispute của mình. **Worker:** listing, assigned jobs, reputation của mình. **Admin:** số Worker/GPU/job, queue, signed results hợp lệ/lỗi, disputes. Không rò dữ liệu trái quyền. |
| FR-DB-02 | Cập nhật số liệu từ trạng thái lưu trên backend. | Refresh thủ công hoặc polling đủ dùng; chưa cần WebSocket, biểu đồ nâng cao. |

## 3. Quy tắc xuyên suốt

- **Job:** `QUEUED → RUNNING → COMPLETED | FAILED`; `QUEUED → CANCELLED`. Trạng thái kết thúc không chuyển tiếp. Yêu cầu sai bị từ chối *trước* khi tạo job.
- **Listing:** `ACTIVE ↔ PAUSED`. Pause không hủy hay gián đoạn job chạy; không nhận job mới và không cấp job đang chờ.
- **Dispute:** `OPEN → RESOLVED`; `decision = UPHELD | REJECTED`. Không ghi đè chứng cứ đã ký.
- **Capacity:** `0 ≤ allocated_gpu_count ≤ total_gpu_count`; thay đổi capacity, cancel và allocate phải được bảo vệ khỏi race condition.
- **FIFO:** thứ tự ổn định theo thời điểm tiếp nhận; dùng ID bất biến để xử lý trường hợp bằng nhau.
- **Idempotency:** finalize job, release GPU, resolve dispute, cập nhật reputation không được xảy ra hai lần.

## 4. Dữ liệu logic tối thiểu (chưa phải Database Schema)

- **User / Role:** ID, thông tin đăng nhập, role.
- **Worker:** ID, user sở hữu, tên, public key, key ID.
- **GPU Listing:** ID, Worker, model, VRAM, total/allocated count, giá mô phỏng nếu cần, status.
- **Job:** ID, Client, Listing, GPU cần dùng, thời lượng, status, các timestamp, failure reason.
- **Signed Result:** result ID, job/worker/key ID, canonical payload, signature, verification status.
- **Dispute:** ID, job/client ID, reason, status, decision, explanation, các timestamp.
- **Simulation Reference:** job ID, expected outcome/digest từ fixture độc lập (không cho người dùng chỉnh sửa).
- **Reputation:** Lifetime per-Worker aggregate counts `successful_jobs`, `worker_fault_jobs` plus per-job contribution/idempotency evidence retained with Job history for 23 days.

## 5. Bộ Acceptance Tests tối thiểu

1. Worker tạo listing; Client xem và tạo job đúng trên listing đã chọn.
2. Job đi `QUEUED → RUNNING → COMPLETED`, receipt được Worker Simulator ký và Manager xác minh.
3. Khi 4 GPU có 3 GPU đang chạy, job cần 2 GPU phải chờ; sau giải phóng được cấp phát đúng FIFO, không over-allocation.
4. Worker Pause: không tiếp nhận/cấp job mới; job chạy được kết thúc; Resume tiếp tục queue.
5. Cancel chỉ thành công với `QUEUED`; cancel/allocate đồng thời không tạo job vừa hủy vừa chiếm GPU.
6. Sửa nội dung receipt sau ký → verify thất bại, không phạt Worker, không cập nhật reputation, tài nguyên cuối cùng được giải phóng.
7. Dispute với signed result sai oracle → `UPHELD`; đúng oracle → `REJECTED`; một job chỉ có một dispute.
8. Dispute được chấp nhận điều chỉnh reputation đúng **một lần**, vẫn giữ receipt gốc.
9. Dashboard của ba role hiển thị dữ liệu đúng quyền và đúng trạng thái backend.

## 6. Ngoài phạm vi MVP

Compute GPU thực, container/SSH, thanh toán/token có giá trị, blockchain, smart contract, đăng ký Worker công khai, auto-matching, multi-worker job, scheduling nâng cao, trọng tài con người, hardware attestation, Kubernetes/microservices, realtime dashboard phức tạp.

## 7. Quyết định đã chốt và những chi tiết còn mở

- **DEC-01 — ĐÃ CHỐT:** MVP dùng **Deterministic Simulation** dựa trên fixture/seed tái lập. Expected outcome/digest được tạo và lưu trước khi nhận signed receipt; Client không thể chọn lỗi để hạ uy tín Worker.
- **DEC-02 — ĐÃ CHỐT:** Mỗi job dùng một listing, FIFO theo listing, Pause đóng băng job chờ, chỉ hủy `QUEUED`; Manager tự động; Admin chỉ giám sát.
- **OPEN-01 — Chi tiết thiết kế:** Chế độ lưu private key của Worker Simulator trong môi trường dev/test (secret hoặc dữ liệu fixture không commit).
- **DEC-03 — ĐÃ CHỐT (ADR-004):** Signed Result V1 dùng RFC 8785 JCS + Ed25519, canonical 11-field payload và `key_id` UUIDv4 được ràng buộc với public key lịch sử; các test triển khai vẫn `NOT_RUN`.
- **OPEN-03 — Chi tiết thiết kế:** Phạm vi tranh chấp với job thiếu receipt hợp lệ để sau MVP; dispute cho job có receipt hợp lệ duy trì quy tắc một dispute/job.
- **NFR BASELINE (CONFIRMED AS PROVISIONAL TARGETS):** 736 concurrently active users in the load-test scenario; 23-day detailed-history retention from `terminal_at`; change-request first substantive response within 18 hours. API latency/recovery targets remain to be measured, not claims of achieved performance.

Các quyết định owner-approved `API-OPEN-01/02/06` đã được đồng bộ tại API Contract v0.6; các ADR-001..008 vẫn ACCEPTED ở mức quyết định kiến trúc. Database/API/Module/Test Design trong `docs/design/` đã được duyệt ở mức tài liệu; chưa có mã nguồn, migration hay kiểm thử thực thi. Các chi tiết JWT ngoài HS256/900 giây và quy tắc lưu token đã duyệt, độ chính xác biểu diễn NumericDate, tập code point của whitespace và Unicode normalization vẫn `NEEDS_OWNER_DECISION` trước Sprint Authentication; chúng không chặn GPU-001 foundation nếu slice đó không triển khai Auth.

## 8. NFR v1.2 integration notes (binding requirements clarification)

- **Retention policy:** After 23 x 24 hours from a Job terminal timestamp, completed Job details, accepted signed receipts, simulation references, settled disputes, and per-job reputation contributions become eligible for coordinated deletion. `QUEUED`/`RUNNING` Jobs, active/paused listings, users, necessary verifier key metadata and lifetime Worker aggregates remain.
- **Lifetime reputation:** Cleanup of an already-accounted Job changes no lifetime counters. After detailed evidence expires, lifetime reputation remains displayable but cannot be reconstructed from deleted Job-by-Job proof. This limitation must be visible in project documentation.
- **Pending dispute at expiry:** The **filing cutoff is APPROVED as 7 days** from `terminal_at` (half-open interval). Do not silently remove evidence for an unexpectedly unresolved dispute at 23-day history expiry. Record and process an explicit retention exception. An unresolved dispute is held until RESOLVED with no predetermined maximum. Admin warning <=1h after detection, CRITICAL at 24h still OPEN, and retries every 15m while Manager is healthy; expired evidence is cleaned within 1h after resolution. The system does not promise a universal hard 23-day deletion bound.
- **Result submission and retries:** Transport may redeliver an execution command or receipt. The business effect must be idempotent: one accepted final result, one GPU release, and at most one effective reputation contribution per Job. Transport decision **ADR-003 ACCEPTED (2026-10-18)**: internal HTTP with PostgreSQL transactional Outbox/Inbox. This is an architecture decision, not an expansion of the 21 FRs; implementation tests remain NOT_RUN.
- **Approved component separation:** Backend API and Manager share repository/domain modules and write PostgreSQL with clear module ownership; Worker Simulator is a separate process that holds Worker signing keys and has no direct application DB access.
- **Traceability:** Detailed quantified targets, security controls, reliability and expiration tests are in `docs/non-functional-requirements.md` v1.2; the primary overview is `docs/requirements.md`.
