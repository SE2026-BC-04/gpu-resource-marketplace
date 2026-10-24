# GPU-002-A — Schema Matrix 10 bảng Phase 1B (bản trình review)

> **Phase:** 1B — Database Schema & Persistence Layer<br>
> **Task:** `GPU-002-A` — phân tích 10 bảng, FK/constraint/index matrix đối chiếu Database Design §9<br>
> **Người soạn:** Thành viên 2 (Database & Persistence)<br>
> **Ngày soạn:** 23/10/2026<br>
> **Baseline đã đọc:** `main@538802a` (so với baseline handoff `c90f540`: chỉ khác tài liệu/fixture, không khác code); rà lại trên `main@cceffbf` (PR #7 chỉ làm rõ Phase 1D/GPU-004 handoff: API tạo Listing với `allocated_gpu_count=0`, Manager là writer duy nhất của counter — khớp mục 3.6 và 6.2, không đổi matrix)<br>
> **Trạng thái:** `PROPOSED / FOR LEAD REVIEW` — **không phải migration**, không có SQL đã chạy; mọi test `NOT_RUN`<br>
> **Revision 2 (24/10/2026):** sửa theo technical review GPU-002-A (`CHANGES REQUESTED`: 2×P1, 2×P2) — xem mục 14. D1–D10 (và D11 mới) vẫn `PROPOSED` tới khi nhóm trưởng quyết định<br>
> **Revision 3 (24/10/2026):** sửa P1 "PostgreSQL Test Cluster Isolation" — test có bootstrap role chỉ chạy trên cluster PostgreSQL riêng, dùng xong bỏ; bootstrap không bao giờ tự đổi mật khẩu/quyền role đã tồn tại; thêm test kiểm chứng cô lập (mục 9.3, D12, R5 ở mục 14)<br>
> **Revision 4 (25/10/2026):** chỉ ghi nhận các quyết định nhóm trưởng đã đưa ra cho D1, D2, D3, D8 (mục 11.1). Không đổi matrix, grant hay trigger đã đề xuất; các quyết định khác vẫn `PENDING LEAD DECISION`<br>
> **Nguồn chuẩn:** [Database Design v0.4 §9, §11](../../design/database-design.md), [Phase 1B](phase1b_database_persistence.md), [GPU-002 handoff](../../development/handoffs/GPU-002_member2_handoff.md), [Module Design §5](../../design/module-design.md), [ADR-002](../decisions/ADR-002-postgresql-access-boundaries.md), [Phase 1C](phase1c_authentication_rbac.md), [Phase 1D](phase1d_gpu_listings.md), [Phase 1E](phase1e_job_submission_queue.md)

## 0. Mục đích, phạm vi và cách đọc

**Mục đích:** chuyển đặc tả vật lý đã duyệt (Database Design §9) thành một matrix có thể review từng dòng trước khi viết ORM/Alembic (`GPU-002-B`), và trình nhóm trưởng các **đề xuất chưa được đặc tả** về DB grants, triggers và guarded delete (Gate 1 trong handoff).

**Hai loại nội dung trong tài liệu, phải phân biệt khi review:**

| Nhãn | Ý nghĩa | Cần gì |
|---|---|---|
| `SPEC` | Chép/diễn giải trực tiếp từ Database Design §9 đã duyệt; tên constraint là đề xuất đặt tên | Chỉ kiểm tra khớp nguồn; không đổi nghĩa |
| `IMPL` | Lựa chọn triển khai trong phạm vi thiết kế (tên, default, cách viết CHECK) | Reviewer xác nhận, L1 |
| `PROPOSAL` | Cơ chế mà thiết kế yêu cầu nhưng chưa đặc tả (grants, trigger, guarded delete, test DB) | **Quyết định của nhóm trưởng** (mục 11); phần đụng xóa dữ liệu/quyền là L2 |

**Ngoài phạm vi:** 8 bảng Phase 2–3, Repository/UoW API chi tiết (`GPU-002-C`), thuật toán oracle (`DEC-P1-04`), hash mật khẩu và normalization login (GPU-003), business flow `TX-SUBMIT`/`TX-PAUSE-EDIT`/`TX-CANCEL` (GPU-004/005). Không thêm bảng, cột, service hay role nghiệp vụ.

## 1. Quy ước chung

| Quy ước | Nội dung | Nhãn |
|---|---|---|
| Kiểu dữ liệu | `uuid`, `timestamptz(6)`, `bytea`, `numeric(12,2)`, `bigint`, `integer`, `varchar(n)`, `text`, `jsonb` đúng §9.2; enum/state là `varchar` + `CHECK IN (...)`, **không** dùng PostgreSQL native ENUM | `SPEC` |
| UUID | `DEFAULT gen_random_uuid()` (built-in từ PostgreSQL 13, không cần `pgcrypto`) sinh UUIDv4. Không thêm `CHECK` version UUID ở DB; ID đưa từ ngoài (fixture) được validate ở đường provisioning | `SPEC` / `IMPL` |
| Thời gian DB | Mọi `created_at`/`assigned_at`/`registered_at` có `DEFAULT clock_timestamp()`. `jobs.submitted_at` **không có default**: caller phải truyền `clock_timestamp()` sau khi khóa Listing (§11.3 A) | `IMPL` (D6) |
| Tên constraint | `pk_<table>`, `fk_<table>_<mục đích>`, `uq_<table>_<cột>`, `ck_<table>_<mục đích>`, `ix_<table>_<mục đích>`; đặt qua `MetaData(naming_convention=...)` của `Base` và viết tường minh trong migration. **Tên constraint là contract** để repository ánh xạ lỗi (ví dụ `uq_jobs_client_idempotency` → replay/409 ở GPU-005) | `IMPL` |
| ON DELETE | `RESTRICT` cho mọi FK master/ownership; `CASCADE` duy nhất cho `simulation_references → jobs` và chỉ có hiệu lực sau guarded delete (mục 8). `ON UPDATE` để mặc định `NO ACTION` | `SPEC` (§9.3) |
| Migration | **Một** baseline revision viết tay (không dùng autogenerate làm bằng chứng), thứ tự: `roles`, `users` → `user_roles` → `workers` → `worker_public_keys`, `worker_reputation_aggregates` → `gpu_listings` → `jobs` → `simulation_references`; `audit_events` độc lập; sau đó index, trigger, grants, seed | `SPEC` (Phase 1B §3.3) |

## 2. Matrix từng bảng

Ký hiệu: `NN` = `NOT NULL`. Cột "Test" liệt kê test ID đã duyệt hoặc negative test bắt buộc trong handoff.

### 2.1. `roles` (Identity lookup)

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `code` | `varchar(8)` | NN | PK |
| `description` | `varchar(100)` | NN | |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_roles` | `PRIMARY KEY (code)` | §9.2-02 | catalog |
| `ck_roles_code` | `code IN ('CLIENT','WORKER','ADMIN')` | §9.2-02 | negative insert `'OWNER'` |

### 2.2. `users`

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `id` | `uuid` | NN; `gen_random_uuid()` | PK |
| `login_name` | `varchar(128)` | NN | Đã normalize ở provisioning; **không** có CHECK normalization ở DB (xem A2) |
| `password_hash` | `text` | NN | Chỉ hash; định dạng do GPU-003 chốt |
| `status` | `varchar(16)` | NN; `'ACTIVE'` | |
| `created_at` | `timestamptz(6)` | NN; `clock_timestamp()` | |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_users` | `PRIMARY KEY (id)` | §9.2-01 | catalog |
| `uq_users_login_name` | `UNIQUE (login_name)` | §9.2-01 | duplicate login rejected |
| `ck_users_status` | `status IN ('ACTIVE','DISABLED')` | §9.2-01 | negative status |

### 2.3. `user_roles` (đúng một role/account)

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `user_id` | `uuid` | NN | PK |
| `role_code` | `varchar(8)` | NN | |
| `assigned_at` | `timestamptz(6)` | NN; `clock_timestamp()` | |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_user_roles` | `PRIMARY KEY (user_id)` — chặn multi-role | §9.2-03 | second role rejected |
| `uq_user_roles_user_id_role_code` | `UNIQUE (user_id, role_code)` — chỉ để làm đích composite FK | §9.2-03, §9.4 | catalog |
| `fk_user_roles_user_id` | `(user_id) → users(id) ON DELETE RESTRICT` | §9.2-03 | delete user rejected |
| `fk_user_roles_role_code` | `(role_code) → roles(code) ON DELETE RESTRICT` | §9.2-03 | unknown role rejected |

Hệ quả cần biết: vì `workers` và `jobs` tham chiếu composite `(user_id, role_code)`, đổi role của một account đã có Worker profile hoặc Job sẽ bị FK chặn. Đây đúng ý "role change requires a privileged controlled operation".

### 2.4. `workers`

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `id` | `uuid` | NN; `gen_random_uuid()` | PK |
| `user_id` | `uuid` | NN | |
| `role_code` | `varchar(8)` | NN; `'WORKER'` | Cột phụ cho composite FK |
| `display_name` | `varchar(160)` | NN | |
| `created_at` | `timestamptz(6)` | NN; `clock_timestamp()` | |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_workers` | `PRIMARY KEY (id)` | §9.2-04 | catalog |
| `uq_workers_user_id` | `UNIQUE (user_id)` | §9.2-04 | second profile rejected |
| `ck_workers_role_code` | `role_code = 'WORKER'` | §9.2-04 | `DBP-02` |
| `fk_workers_user_role` | `(user_id, role_code) → user_roles(user_id, role_code) ON DELETE RESTRICT` | §9.2-04, §9.3 | `DBP-02`: Worker profile trên account CLIENT bị từ chối |

### 2.5. `worker_public_keys`

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `key_id` | `uuid` | NN; `gen_random_uuid()` | PK; ADR-004 `key_id` |
| `worker_id` | `uuid` | NN | |
| `public_key_raw` | `bytea` | NN | Ed25519 public key; **không có cột private key** |
| `registered_at` | `timestamptz(6)` | NN; `clock_timestamp()` | |
| `retired_at` | `timestamptz(6)` | nullable | |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_worker_public_keys` | `PRIMARY KEY (key_id)` | §9.2-05 | catalog |
| `fk_worker_public_keys_worker_id` | `(worker_id) → workers(id) ON DELETE RESTRICT` | §9.2-05 | delete Worker có key rejected |
| `uq_worker_public_keys_worker_id_key_id` | `UNIQUE (worker_id, key_id)` — đích FK của `signed_results` Phase 2 | §9.2-05, §9.4 | catalog |
| `ck_worker_public_keys_raw_len` | `octet_length(public_key_raw) = 32` | §9.2-05 | key 31/33 bytes rejected |
| `ck_worker_public_keys_retired_after_registered` | `retired_at IS NULL OR retired_at >= registered_at` | §9.2-05 | negative retire time |
| `uq_worker_public_keys_active_worker` | `UNIQUE (worker_id) WHERE retired_at IS NULL` | §9.2-05 ghi "**Proposed policy**" | **Cần xác nhận (D4)** |

### 2.6. `gpu_listings`

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `id` | `uuid` | NN; `gen_random_uuid()` | PK |
| `worker_id` | `uuid` | NN | Bất biến (Listing không chuyển owner) |
| `gpu_model` | `varchar(160)` | NN | API trim trước khi ghi |
| `vram_gb` | `integer` | NN | |
| `total_gpu_count` | `integer` | NN | |
| `allocated_gpu_count` | `integer` | NN; `0` | Writer duy nhất là Manager (Phase 2) |
| `status` | `varchar(8)` | NN; `'ACTIVE'` | |
| `mock_price_per_hour` | `numeric(12,2)` | nullable | Không phải billing |
| `created_at` | `timestamptz(6)` | NN; `clock_timestamp()` | |
| `updated_at` | `timestamptz(6)` | NN; `clock_timestamp()` | Đề xuất trigger tự đặt (D7) |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_gpu_listings` | `PRIMARY KEY (id)` | §9.2-06 | catalog |
| `fk_gpu_listings_worker_id` | `(worker_id) → workers(id) ON DELETE RESTRICT` | §9.2-06 | Listing cho Worker không tồn tại rejected |
| `uq_gpu_listings_id_worker_id` | `UNIQUE (id, worker_id)` — đích FK của `jobs` | §9.2-06, §9.4 | catalog |
| `ck_gpu_listings_gpu_model_nonblank` | `btrim(gpu_model) <> ''` | §9.2-06 "must be nonblank" | chuỗi rỗng/chỉ space rejected |
| `ck_gpu_listings_vram_positive` | `vram_gb > 0` | §9.2-06 | `0`, `-1` rejected |
| `ck_gpu_listings_total_positive` | `total_gpu_count > 0` | §9.2-06 | `0` rejected |
| `ck_gpu_listings_allocated_range` | `allocated_gpu_count >= 0 AND allocated_gpu_count <= total_gpu_count` | §9.2-06, DB-INV-01 | **`DBP-04`**: total=4, allocated `-1`/`5` rejected, giá trị cũ giữ nguyên |
| `ck_gpu_listings_status` | `status IN ('ACTIVE','PAUSED')` | §9.2-06 | negative status |
| `ck_gpu_listings_price_nonnegative` | `mock_price_per_hour IS NULL OR mock_price_per_hour >= 0` | §9.2-06 | `-0.01` rejected |

Ghi chú `IMPL`: `btrim()` mặc định chỉ bỏ ký tự space; đây là lưới an toàn cuối, quy tắc trim đầy đủ thuộc validation của GPU-004.

### 2.7. `jobs`

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `id` | `uuid` | NN; `gen_random_uuid()` | PK |
| `client_id` | `uuid` | NN | |
| `client_role` | `varchar(8)` | NN; `'CLIENT'` | Cột phụ cho composite FK |
| `listing_id` | `uuid` | NN | |
| `worker_id` | `uuid` | NN | Snapshot owner của Listing |
| `requested_gpu_count` | `integer` | NN | So với total trong `TX-SUBMIT` (GPU-005) |
| `duration_seconds` | `integer` | NN | |
| `status` | `varchar(12)` | NN; `'QUEUED'` | |
| `submitted_at` | `timestamptz(6)` | NN; **không default** | `clock_timestamp()` sau Listing lock |
| `enqueue_seq` | `bigint GENERATED ALWAYS AS IDENTITY` | NN | FIFO; có thể có gap |
| `started_at` | `timestamptz(6)` | nullable | Phase 2 ghi |
| `terminal_at` | `timestamptz(6)` | nullable | |
| `failure_reason` | `varchar(16)` | nullable | |
| `idempotency_key` | `varchar(128)` | nullable | |
| `request_sha256` | `bytea` | nullable | 32 bytes khi có key |
| `correlation_id` | `uuid` | NN | Không dùng cho FIFO |

| Constraint / index | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_jobs` | `PRIMARY KEY (id)` | §9.2-07 | catalog |
| `fk_jobs_client_user_role` | `(client_id, client_role) → user_roles(user_id, role_code) ON DELETE RESTRICT` | §9.2-07, §9.3 | **`DBP-02`**: Job với Worker làm Client rejected |
| `fk_jobs_listing_worker` | `(listing_id, worker_id) → gpu_listings(id, worker_id) ON DELETE RESTRICT` | §9.2-07, §9.3 | **`DBP-01`**: L1 của W1 + `worker_id`=W2 rejected, 0 row |
| `ck_jobs_client_role` | `client_role = 'CLIENT'` | §9.2-07 | `DBP-02` |
| `ck_jobs_requested_gpu_count_positive` | `requested_gpu_count > 0` | §9.2-07 | `0` rejected |
| `ck_jobs_duration_seconds_positive` | `duration_seconds > 0` | §9.2-07 | `0` rejected |
| `ck_jobs_status` | `status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')` | §9.2-07 | negative status |
| `ck_jobs_terminal_at_consistency` | `(status IN ('COMPLETED','FAILED','CANCELLED')) = (terminal_at IS NOT NULL)` | §9.2-07 | CANCELLED thiếu `terminal_at` rejected |
| `ck_jobs_failure_reason` | `(status = 'FAILED') = (failure_reason IS NOT NULL) AND (failure_reason IS NULL OR failure_reason IN ('WORKER_FAULT','JOB_FAULT','SYSTEM_FAULT'))` | §9.2-07 | FAILED thiếu reason / COMPLETED có reason rejected |
| `ck_jobs_started_at_never_running` | `status NOT IN ('QUEUED','CANCELLED') OR started_at IS NULL` | §9.2-07 | QUEUED có `started_at` rejected |
| `ck_jobs_idempotency_pair` | `(idempotency_key IS NULL) = (request_sha256 IS NULL)` | §9.2-07 | key thiếu hash rejected |
| `ck_jobs_request_sha256_len` | `request_sha256 IS NULL OR octet_length(request_sha256) = 32` | §9.2-07 | hash 31 bytes rejected |
| `uq_jobs_enqueue_seq` | `UNIQUE (enqueue_seq)` | §9.2-07, §9.4 | `DBP-03` (phần lưu trữ) |
| `uq_jobs_id_listing_id` | `UNIQUE (id, listing_id)` — đích FK `allocations` (Phase 2) | §9.2-07, §9.4 | catalog |
| `uq_jobs_id_worker_id` | `UNIQUE (id, worker_id)` — đích FK `job_reputation_contributions` | §9.2-07, §9.4 | catalog |
| `uq_jobs_id_client_id` | `UNIQUE (id, client_id)` — đích FK `disputes` | §9.2-07, §9.4 | catalog |
| `uq_jobs_id_listing_id_worker_id` | `UNIQUE (id, listing_id, worker_id)` — đích FK `signed_results` | §9.2-07, §9.4 | catalog |
| `uq_jobs_client_idempotency` | `UNIQUE (client_id, idempotency_key) WHERE idempotency_key IS NOT NULL` | §9.2-07, §9.4 | duplicate client key rejected; hai Client dùng cùng key được phép |
| `ix_jobs_listing_fifo` | `(listing_id, enqueue_seq) WHERE status = 'QUEUED'` | §9.4 | `DBP-03`, EXPLAIN về sau |
| `ix_jobs_client_history` | `(client_id, submitted_at DESC, id DESC)` | §9.4 | catalog |
| `ix_jobs_terminal_cleanup` | `(terminal_at, id) WHERE status IN ('COMPLETED','FAILED','CANCELLED')` | §9.4 | catalog |

Ghi chú `SPEC`: bốn UNIQUE phụ `uq_jobs_id_*` thuộc bảng `jobs` (đã tồn tại ở Phase 1B) nên được tạo ngay theo §9.2. Việc này không tạo index cho bảng chưa tồn tại và giúp Phase 2 không phải `ALTER` bảng `jobs` đang có dữ liệu.

### 2.8. `simulation_references` (protected oracle)

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `job_id` | `uuid` | NN | PK + FK |
| `seed_value` | `bigint` | NN | |
| `algorithm_version` | `varchar(32)` | NN | |
| `expected_outcome` | `varchar(8)` | NN | |
| `expected_failure_reason` | `varchar(16)` | nullable | |
| `expected_digest` | `varchar(71)` | NN | |
| `created_at` | `timestamptz(6)` | NN; `clock_timestamp()` | |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_simulation_references` | `PRIMARY KEY (job_id)` — tối đa một reference/Job | §9.2-08 | `DBP-05` (phần áp dụng): reference thứ hai rejected |
| `fk_simulation_references_job_id` | `(job_id) → jobs(id) ON DELETE CASCADE` (chỉ sau guarded delete) | §9.2-08, §9.3 | cascade chỉ khi guard cho phép (mục 8) |
| `ck_simulation_references_outcome` | `expected_outcome IN ('SUCCESS','FAILED')` | §9.2-08 | negative outcome |
| `ck_simulation_references_outcome_reason` | `(expected_outcome = 'SUCCESS' AND expected_failure_reason IS NULL) OR (expected_outcome = 'FAILED' AND expected_failure_reason IS NOT NULL AND expected_failure_reason IN ('WORKER_FAULT','JOB_FAULT'))` | §9.2-08 | SUCCESS có reason / FAILED với `SYSTEM_FAULT` / FAILED với reason NULL rejected (`IN` trên NULL cho kết quả UNKNOWN nên cần `IS NOT NULL` tường minh) |
| `ck_simulation_references_digest_format` | `expected_digest ~ '^sha256:[0-9a-f]{64}$'` | §9.2-08 | hex hoa, thiếu prefix, 63 ký tự rejected |

`SPEC`: PK/FK chỉ bảo đảm **tối đa** một reference. "Đúng một reference cho mỗi Job" thuộc `TX-SUBMIT` (GPU-005), trừ khi chọn thêm cơ chế DB ở D5. Fixture test chỉ dùng giá trị hợp lệ về **định dạng**, không phải output của generator, và không được trình bày như oracle thật.

### 2.9. `worker_reputation_aggregates`

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `worker_id` | `uuid` | NN | PK + FK |
| `successful_jobs` | `bigint` | NN; `0` | |
| `worker_fault_jobs` | `bigint` | NN; `0` | |
| `updated_at` | `timestamptz(6)` | NN; `clock_timestamp()` | |

| Constraint | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_worker_reputation_aggregates` | `PRIMARY KEY (worker_id)` | §9.2-15 | catalog |
| `fk_worker_reputation_aggregates_worker_id` | `(worker_id) → workers(id) ON DELETE RESTRICT` — **không cascade** từ Job | §9.2-15, §9.3 | delete Worker rejected |
| `ck_worker_reputation_aggregates_successful_nonneg` | `successful_jobs >= 0` | §9.2-15 | `-1` rejected |
| `ck_worker_reputation_aggregates_fault_nonneg` | `worker_fault_jobs >= 0` | §9.2-15 | `-1` rejected |

### 2.10. `audit_events`

| Cột | Kiểu | Null / default | Ghi chú |
|---|---|---|---|
| `id` | `uuid` | NN; `gen_random_uuid()` | PK |
| `created_at` | `timestamptz(6)` | NN; `clock_timestamp()` | Mốc TTL 23 ngày riêng |
| `actor_kind` | `varchar(12)` | NN | |
| `actor_ref` | `varchar(128)` | NN | Không chứa secret/token |
| `correlation_id` | `uuid` | NN | |
| `subject_type` | `varchar(32)` | nullable | Không CHECK (taxonomy mở theo §9.2) |
| `subject_id` | `uuid` | nullable | **Không FK** tới Job |
| `event_type` | `varchar(64)` | NN | |
| `outcome` | `varchar(12)` | NN | |
| `metadata_redacted` | `jsonb` | NN; `'{}'::jsonb` | |

| Constraint / index | Định nghĩa | Nguồn | Test |
|---|---|---|---|
| `pk_audit_events` | `PRIMARY KEY (id)` | §9.2-18 | catalog |
| `ck_audit_events_actor_kind` | `actor_kind IN ('USER','SERVICE')` | §9.2-18 | negative |
| `ck_audit_events_outcome` | `outcome IN ('SUCCESS','REJECTED','ERROR')` | §9.2-18 | negative |
| `ck_audit_events_metadata_object` | `jsonb_typeof(metadata_redacted) = 'object'` | §9.2-18 | array/scalar rejected |
| `ix_audit_events_created_at_id` | `(created_at, id)` | §9.4 | catalog |

## 3. Tổng hợp FK (9 FK)

| # | Child → parent | Hành động | Ý nghĩa |
|---|---|---|---|
| 1 | `user_roles(user_id)` → `users(id)` | RESTRICT | Giữ account |
| 2 | `user_roles(role_code)` → `roles(code)` | RESTRICT | Catalog role cố định |
| 3 | `workers(user_id, role_code)` → `user_roles(user_id, role_code)` | RESTRICT | Worker profile chỉ cho account WORKER |
| 4 | `worker_public_keys(worker_id)` → `workers(id)` | RESTRICT | Giữ lịch sử key |
| 5 | `gpu_listings(worker_id)` → `workers(id)` | RESTRICT | Listing có đúng một owner |
| 6 | `jobs(client_id, client_role)` → `user_roles(user_id, role_code)` | RESTRICT | Chỉ CLIENT submit |
| 7 | `jobs(listing_id, worker_id)` → `gpu_listings(id, worker_id)` | RESTRICT | Snapshot owner không lệch Listing |
| 8 | `simulation_references(job_id)` → `jobs(id)` | **CASCADE** (guarded) | Xóa cùng Job khi hết hạn |
| 9 | `worker_reputation_aggregates(worker_id)` → `workers(id)` | RESTRICT | Lifetime counter không theo Job |

`audit_events.subject_id` cố ý **không có FK**.

## 4. Index và độ phủ FK

PostgreSQL không tự tạo index cho cột FK phía child. Rà soát cho thấy không cần index FK bổ sung ngoài §9.4:

| FK child | Index phủ | Kết luận |
|---|---|---|
| `user_roles(role_code)` | không | Bảng `roles` có 3 dòng, không bao giờ xóa → không cần |
| `workers(user_id, role_code)` | `uq_workers_user_id` (prefix) | Đủ |
| `worker_public_keys(worker_id)` | `uq_worker_public_keys_worker_id_key_id` (prefix) | Đủ |
| `gpu_listings(worker_id)` | `ix_gpu_listings_worker_id_status` (prefix) | Đủ |
| `jobs(client_id, client_role)` | `ix_jobs_client_history` (prefix `client_id`) | Đủ |
| `jobs(listing_id, worker_id)` | `ix_jobs_listing_fifo` chỉ phủ `QUEUED` | Listing không bị xóa/đổi owner → không cần cho FK. Truy vấn Job `RUNNING` theo Listing (Phase 1D hardware lock) sẽ scan; **không thêm index suy đoán**, đo bằng `EXPLAIN` khi có dữ liệu SCA |

**Tổng số:** 5 index thường (`ix_gpu_listings_worker_id_status`, `ix_jobs_listing_fifo`, `ix_jobs_client_history`, `ix_jobs_terminal_cleanup`, `ix_audit_events_created_at_id`) và 2 UNIQUE partial (`uq_jobs_client_idempotency`, `uq_worker_public_keys_active_worker` nếu D4 được duyệt).

## 5. Seed

| Dữ liệu | Cách nạp | Trạng thái |
|---|---|---|
| `roles` 3 dòng: `CLIENT`/"Client user", `WORKER`/"GPU resource provider", `ADMIN`/"System administrator" (theo `roles.json`) | Trong baseline migration, `INSERT ... ON CONFLICT (code) DO NOTHING` → chạy lại an toàn | Sẵn sàng làm ở GPU-002-B |
| `users`, `user_roles` (8 account demo) | Công cụ provisioning ngoài migration, chạy bằng owner DSN, hash mật khẩu lúc provisioning | **BLOCKED**: thuật toán hash + quy tắc normalization chưa chốt trên Git (A2) |
| `workers`, `worker_reputation_aggregates` (3), `gpu_listings` (8) | Cùng công cụ provisioning, sau users | **BLOCKED** theo users |
| `worker_public_keys`, `jobs`, `simulation_references`, `audit_events` | Không seed | Theo README fixture: không bịa key/Job/oracle |

Nguyên tắc: **migration không chứa dữ liệu demo**; dữ liệu demo không bao giờ đi vào môi trường thật qua `alembic upgrade`.

## 6. Đề xuất DB roles và grants — `PROPOSAL`

### 6.1. Rủi ro hiện tại

`compose.yaml` cấp cùng một `GPU_MARKETPLACE_DATABASE_URL` cho API và Manager, dùng `POSTGRES_USER`. Image `postgres` tạo user này là **superuser**, nên mọi GRANT/REVOKE đều vô hiệu với API/Manager hôm nay. Thiết kế yêu cầu tách quyền (§9.1, §11.5; Module Design §5; ADR-002 §6), nên **không được tuyên bố quyền ghi đã phân tách** chỉ nhờ code ownership.

### 6.2. Mô hình role đề xuất

| Role | Loại | Tạo bởi | Dùng cho |
|---|---|---|---|
| `gpu_marketplace` (hiện có) | Owner / superuser | Image postgres | Chỉ bootstrap role, migration và provisioning; runtime **không** dùng |
| `gpm_api_rw` | `NOLOGIN` group | **Bootstrap role (bước 0)** | Nhận grants của API |
| `gpm_manager_rw` | `NOLOGIN` group | **Bootstrap role (bước 0)** | Nhận grants của Manager |
| `gpm_api_app` | `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT`, member của `gpm_api_rw` | **Bootstrap role (bước 0)** | DSN của service `api` |
| `gpm_manager_app` | Như trên, member của `gpm_manager_rw` | **Bootstrap role (bước 0)** | DSN của service `manager` |

**Thứ tự khởi tạo (sửa theo review P1-1).** Revision 1 để migration tạo group role còn init script tạo login role và cấp membership; vì init script chạy **trước** migration trên volume rỗng, `GRANT gpm_api_rw TO gpm_api_app` sẽ lỗi do group chưa tồn tại. Revision 2 gom **toàn bộ** role vào một bước bootstrap duy nhất, chạy trước migration; migration không bao giờ tạo hay xóa role:

| Bước | Ai chạy / bằng role nào | Làm gì | Điều kiện an toàn |
|---|---|---|---|
| 0. Bootstrap role | Owner. Hai đường gọi **cùng một script**: (a) `docker-entrypoint-initdb.d` khi volume rỗng; (b) lệnh chạy lại thủ công cho volume đã có dữ liệu hoặc khi đổi mật khẩu | Tạo 2 group `NOLOGIN` → tạo 2 login role → `GRANT` group cho login. **Chế độ mặc định chỉ tạo mới (create-only):** role chưa có thì tạo; role đã có thì **không** `ALTER` mật khẩu, thuộc tính hay membership, chỉ **kiểm tra** thuộc tính (`NOSUPERUSER`, `NOREPLICATION`, `NOBYPASSRLS`, `LOGIN`/`NOLOGIN`) và membership mong đợi; lệch thì dừng với mã lỗi khác 0 và báo cho người vận hành sửa thủ công. Đổi mật khẩu là lệnh riêng, phải gọi tường minh (cờ `--rotate-password`), không bao giờ chạy từ init script hay test (sửa theo review R5) | Mật khẩu lấy từ biến môi trường **chỉ của container `postgres`**, đưa vào SQL qua biến psql và `format('%L')`, không ghi vào file SQL, không echo. Script không đụng bảng nào |
| 1. Migration | Owner (mục 9, D9) | Bước đầu tiên của baseline revision: kiểm tra `gpm_api_rw` và `gpm_manager_rw` tồn tại trong `pg_roles`; thiếu thì **dừng** với thông báo "chạy bootstrap role trước" (không tự tạo). Sau đó tạo bảng, trigger, rồi `GRANT` cho **group** | Không chứa mật khẩu, không tham chiếu login role |
| 2. Runtime | `gpm_api_app` / `gpm_manager_app` | API/Manager kết nối bằng DSN riêng | Không service runtime nào nhận owner DSN |

Hệ quả: (1) thứ tự phụ thuộc chỉ một chiều, bootstrap → migration; (2) migration downgrade chỉ `REVOKE` và xóa object, **không `DROP ROLE`** vì role là đối tượng toàn cluster dùng chung với DB test; (3) volume dev hiện có không chạy lại init script, nên runbook ghi lệnh (b) trước `alembic upgrade head`; (4) test fixture cũng gọi cùng script bootstrap trước migration, nên CI kiểm chứng đúng thứ tự này — nhưng **chỉ** trên cluster test riêng đã qua hàng rào mục 9.3, với mật khẩu ngẫu nhiên sinh cho từng test session, không đọc mật khẩu từ `.env` dev. Mọi thay đổi `compose.yaml`/`.env.example`/init script là shared infra, cần nhóm trưởng (D1).

Thêm: `REVOKE ALL ON DATABASE ... FROM PUBLIC`, `GRANT CONNECT` cho hai group; `REVOKE EXECUTE` trên các trigger function khỏi `PUBLIC`; trigger function đặt `SET search_path = pg_catalog, public`.

### 6.3. Grant matrix Phase 1B

`gpm_manager_rw` ở Phase 1B chỉ cần `CONNECT` (Manager hiện chỉ chạy `SELECT 1`). Cột "Manager — Phase 2" chỉ để tham khảo, cấp trong migration Phase 2 theo least privilege.

| Bảng | `gpm_api_rw` (Phase 1B) | Manager — Phase 2 (tham khảo) | Lý do / nguồn |
|---|---|---|---|
| `roles` | `SELECT` | `SELECT` | Read-only lookup |
| `users` | `SELECT` | — | Login đọc `password_hash`; provisioning qua owner |
| `user_roles` | `SELECT` | — | Principal + role |
| `workers` | `SELECT` | `SELECT` | Profile đã provision |
| `worker_public_keys` | `SELECT (key_id, worker_id, registered_at, retired_at)` — **không** `public_key_raw` | `SELECT` | API không cần raw key ở Phase 1; Manager verify |
| `gpu_listings` | `SELECT`; `INSERT (worker_id, gpu_model, vram_gb, total_gpu_count, mock_price_per_hour)`; `UPDATE (gpu_model, vram_gb, total_gpu_count, status, mock_price_per_hour)` | `SELECT`; `UPDATE (allocated_gpu_count)` | Manager là writer duy nhất của `allocated_gpu_count` (Phase 1D §2) |
| `jobs` | `SELECT`; `INSERT (client_id, listing_id, worker_id, requested_gpu_count, duration_seconds, submitted_at, idempotency_key, request_sha256, correlation_id)`; `UPDATE (status, terminal_at)` | `SELECT`; `UPDATE (status, started_at, terminal_at, failure_reason)` | INSERT không có `status`/`client_role` → bắt buộc dùng default `QUEUED`/`CLIENT` |
| `simulation_references` | `INSERT (job_id, seed_value, algorithm_version, expected_outcome, expected_failure_reason, expected_digest)` — **không `SELECT`** | `SELECT` | Repository public không thể đọc oracle (P1B-AC-07) |
| `worker_reputation_aggregates` | `SELECT` | `SELECT`; `UPDATE (successful_jobs, worker_fault_jobs)` | API chỉ đọc projection |
| `audit_events` | `INSERT` (trừ `id`, `created_at`) | `INSERT`; `DELETE` khi có `TX-AUDIT-PURGE` (Phase 3) | Không cho caller backdate |

Không role runtime nào có `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` hay quyền DDL ở Phase 1B.

### 6.4. Hệ quả kỹ thuật cần kiểm chứng trong test

1. `SELECT ... FOR UPDATE` yêu cầu quyền `UPDATE` trên **ít nhất một cột**. API có column UPDATE trên `gpu_listings` và `jobs` nên khóa được Listing → Job. Manager sẽ có ở Phase 2.
2. Không cấp INSERT cho `created_at`/`updated_at`/`assigned_at` → thời gian luôn do DB cấp.
3. API INSERT `simulation_references` **không được dùng `RETURNING`** (cần SELECT). Repository phải dùng Core `insert()` không RETURNING và tắt eager server defaults cho mapping này.
4. Cột identity `enqueue_seq`: INSERT vào bảng không cần grant riêng trên sequence identity. **Phải xác nhận bằng test** với role `gpm_api_app`.
5. Repository ánh xạ lỗi theo `constraint_name` (psycopg `diag`), vì vậy tên constraint ở mục 2 là contract với GPU-003/004/005.

## 7. Đề xuất triggers bảo vệ — `PROPOSAL`

Trigger là **defense in depth**, áp dụng cả cho owner. Owner/superuser vẫn có thể `DISABLE TRIGGER`, nên trigger không thay thế việc runtime không dùng owner. Mọi lỗi trigger raise `ERRCODE = 'integrity_constraint_violation'` (23000) với `CONSTRAINT = '<tên trigger>'` để repository xử lý cùng đường với UNIQUE/FK/CHECK.

| Trigger | Bảng / thời điểm | Quy tắc | Nguồn yêu cầu |
|---|---|---|---|
| `trg_jobs_guard_update` | `jobs` BEFORE UPDATE | (a) Job terminal (`COMPLETED`/`FAILED`/`CANCELLED`) không được UPDATE; (b) cột bất biến không đổi: `id, client_id, client_role, listing_id, worker_id, requested_gpu_count, duration_seconds, submitted_at, enqueue_seq, idempotency_key, request_sha256, correlation_id`; (c) chỉ cho cạnh `QUEUED→RUNNING`, `QUEUED→CANCELLED`, `RUNNING→COMPLETED`, `RUNNING→FAILED`; nếu `status` không đổi thì không cột nào được đổi; (d) ràng buộc cạnh theo loại caller (API/Manager/owner/không xác định) — xem bảng phân loại bên dưới | BR-05; §9.2-07 "never rewrite core Job identity"; §9.5.8; §11.5 "no API/Manager UPDATE grant bypassing lifecycle"; Module Design §5 |
| `trg_jobs_guard_delete` | `jobs` BEFORE DELETE | Xem mục 8 | §9.3 safety barrier |
| `trg_simulation_references_immutable` | `simulation_references` BEFORE UPDATE | Từ chối mọi UPDATE (DELETE chỉ qua cascade sau guard) | §9.2-08 "immutable truth record"; §9.5.8 |
| `trg_audit_events_immutable` | `audit_events` BEFORE UPDATE | Từ chối mọi UPDATE | §9.2-18 "insert-only" |
| `trg_worker_public_keys_guard_update` | `worker_public_keys` BEFORE UPDATE | Chỉ cho `retired_at` đổi từ `NULL` sang giá trị; `key_id`, `worker_id`, `public_key_raw`, `registered_at` bất biến | §9.2-05; evidence ADR-004/006 |
| `trg_gpu_listings_guard_update` | `gpu_listings` BEFORE UPDATE | `id`, `worker_id`, `created_at` bất biến; đặt `NEW.updated_at = clock_timestamp()` | Database Design §3.1 "Listings do not transfer Worker ownership"; §9.2-06 "DB time" |
| `trg_worker_reputation_aggregates_touch` | `worker_reputation_aggregates` BEFORE UPDATE | `worker_id` bất biến; đặt `NEW.updated_at = clock_timestamp()` | §9.2-15 |

Pseudocode `trg_jobs_guard_update` (không phải SQL chạy được):

```text
IF OLD.status IN terminal: REJECT 'job_terminal_immutable'
IF any immutable column IS DISTINCT FROM OLD: REJECT 'job_identity_immutable'
IF NEW.status = OLD.status:
    IF NEW row IS DISTINCT FROM OLD row: REJECT 'job_update_without_transition'
    RETURN NEW
IF (OLD.status, NEW.status) NOT IN legal edges: REJECT 'job_illegal_transition'
caller = classify(current_user)          # xem bảng bên dưới
IF caller = API     AND edge <> QUEUED -> CANCELLED:            REJECT 'job_transition_not_owned_by_api'
IF caller = MANAGER AND edge NOT IN (QUEUED -> RUNNING,
                                     RUNNING -> COMPLETED, RUNNING -> FAILED):
                                                                REJECT 'job_transition_not_owned_by_manager'
IF caller = UNKNOWN:                                            REJECT 'job_update_role_not_permitted'
RETURN NEW                               # caller = OWNER_MAINTENANCE: chỉ qua (a)-(c)
```

**Cách xác định caller (sửa theo review P2-3).** Function là `SECURITY INVOKER` (không dùng `SECURITY DEFINER`), nên `current_user` là role đang thực thi câu lệnh, kể cả sau `SET ROLE`. Membership được tính bằng truy vấn **đệ quy trên `pg_auth_members`** bắt đầu từ chính `current_user` (bao gồm trường hợp `current_user` là group), **không** dùng `pg_has_role()`/`is_member_of()` vì hai hàm này trả `true` cho superuser với mọi role:

| Thứ tự xét | Điều kiện | Caller | Hành vi |
|---|---|---|---|
| 1 | Thuộc **cả** `gpm_api_rw` và `gpm_manager_rw` | — | Từ chối mọi UPDATE (`job_update_role_ambiguous`): cấu hình role sai |
| 2 | Thuộc `gpm_api_rw` | `API` | Chỉ `QUEUED→CANCELLED` |
| 3 | Thuộc `gpm_manager_rw` | `MANAGER` | Chỉ `QUEUED→RUNNING`, `RUNNING→COMPLETED`, `RUNNING→FAILED` (Phase 2 mới cấp grant UPDATE) |
| 4 | Không thuộc group nào, và `rolsuper` hoặc là owner của DB | `OWNER_MAINTENANCE` | **Không** được miễn (a)–(c): Job terminal vẫn bất biến, cột định danh vẫn bất biến, chỉ đi theo cạnh hợp lệ. Chỉ bỏ ràng buộc "cạnh thuộc service nào" để phục vụ sửa dữ liệu có kiểm soát |
| 5 | Mọi trường hợp còn lại | `UNKNOWN` | Từ chối (fail closed), kể cả khi role đó có grant UPDATE |

**Giới hạn phải ghi nhận:** superuser có thể `ALTER TABLE ... DISABLE TRIGGER` hoặc `SET session_replication_role = replica` để bỏ qua trigger. Trigger không chặn được việc này; lớp bảo vệ thực sự là runtime **không bao giờ** chạy bằng superuser/owner (mục 6.2). Test ở GPU-002-D phải kiểm: `gpm_api_app` và `gpm_manager_app` có `rolsuper = false`, `rolreplication = false`, `rolbypassrls = false`; `gpm_api_app` đi `QUEUED→RUNNING` bị từ chối, `QUEUED→CANCELLED` được phép; owner sửa Job terminal hoặc đi `RUNNING→QUEUED` bị từ chối; một role thử nghiệm có grant UPDATE nhưng không thuộc group nào bị từ chối; `SET ROLE gpm_api_rw` vẫn được phân loại `API`.

Không đề xuất trigger cho `roles`/`users`/`user_roles`/`workers`: runtime không có quyền ghi, provisioning chạy bằng owner.

## 8. Guarded delete cho `jobs` — `PROPOSAL`

**Yêu cầu (§9.3):** PostgreSQL phải từ chối `DELETE FROM jobs` không được phép; đường cleanup được phép phải từ chối Job chưa terminal, Job chưa đủ 23 ngày, hoặc Job có Dispute `OPEN`, trước khi cascade.

**Phase 1B đề xuất hai lớp:**

1. **Quyền:** không role runtime nào có `DELETE`/`TRUNCATE` trên `jobs`. Phase 3 sẽ cấp `DELETE` cho `gpm_manager_rw` cùng cleanup transaction.
2. **Trigger `trg_jobs_guard_delete`** (áp dụng cả owner):

```text
IF OLD.status NOT IN ('COMPLETED','FAILED','CANCELLED')
   OR OLD.terminal_at IS NULL
   OR clock_timestamp() < OLD.terminal_at + interval '23 days':
    REJECT 'job_delete_not_eligible'
-- Phase 3 migration mở rộng: REJECT nếu tồn tại disputes(job_id, status='OPEN')
RETURN OLD
```

Ở Phase 1B chưa có bảng `disputes`, nên điều kiện OPEN Dispute **chưa thể** có. Đây là phần ghi rõ `BLOCKED` cho `DBP-09`, không được báo PASS. Cascade sang `simulation_references` chỉ xảy ra khi trigger cho phép. `TRUNCATE` không kích hoạt trigger DELETE theo dòng; chỉ được dùng bởi owner trên **DB test** (mục 9).

## 9. Migration và hạ tầng test — `PROPOSAL`

| Chủ đề | Đề xuất | Owner quyết định |
|---|---|---|
| Chạy migration ở Compose | Chạy tạm một container `api` bằng `docker compose run --rm` với lệnh `alembic upgrade head`, nhận owner DSN qua biến **riêng** `GPU_MARKETPLACE_MIGRATION_DATABASE_URL` theo mục 9.1 — **không** truyền giá trị DSN trên dòng lệnh. **Không** thêm service `migrate`: `tests/test_compose_topology.py` khóa đúng 5 services. **Không** tự migrate khi API khởi động (role API không có DDL; nhiều instance có thể race) | Nhóm trưởng (D9) |
| PostgreSQL cho CI | Thêm `services: postgres` vào job `python` của `foundation.yml`, pin cùng image digest với `compose.yaml` (`postgres:16.15-bookworm@sha256:0ea6...`). Không thêm dependency mới (testcontainers…) | Nhóm trưởng (D8) |
| An toàn DB test | Integration test chỉ đọc `GPU_MARKETPLACE_TEST_DATABASE_URL` và phải qua **toàn bộ** hàng rào cấp cluster ở mục 9.3 rồi hàng rào cấp database ở mục 9.2 trước mọi bootstrap role, `DROP`/`CREATE`/`TRUNCATE`. Test **không bao giờ** chạy trên service `postgres` của Compose dev. Fixture session chạy bootstrap role → tạo DB test → `alembic upgrade head`; dọn dữ liệu giữa test bằng `TRUNCATE` (owner) vì test race cần commit thật trên nhiều connection. Thiếu biến → test được skip và báo `NOT_RUN`, không PASS | TV2, review nhóm trưởng (D11) |
| Round-trip | `upgrade head` → kiểm tra catalog → `downgrade base` → `upgrade head` chỉ trên DB test (P1B-AC-08). Downgrade xóa trigger, function, bảng theo thứ tự ngược, `REVOKE`; **không** `DROP ROLE` | TV2 |
| Drift ORM ↔ DB | (a) `alembic.autogenerate.compare_metadata` phải rỗng; (b) vì autogenerate không so CHECK/partial predicate đầy đủ, thêm test truy vấn `pg_constraint`/`pg_indexes`/`information_schema` so với danh sách tên ở mục 2 | TV2 |

### 9.1. Cấp owner DSN cho migration mà không lộ credential (sửa theo review P2-4)

Revision 1 hướng dẫn `-e GPU_MARKETPLACE_DATABASE_URL=<owner DSN>` trên dòng lệnh. Cách đó để mật khẩu owner lọt vào shell history, danh sách tiến trình của máy host và log CI; đồng thời dùng chung tên biến với DSN runtime nên dễ cấu hình nhầm service `api` chạy bằng owner. Revision 2 đề xuất:

| Quy tắc | Nội dung |
|---|---|
| Biến riêng | Migration chỉ đọc `GPU_MARKETPLACE_MIGRATION_DATABASE_URL`. `migrations/env.py` **không fallback** sang DSN runtime: thiếu biến thì dừng với thông báo không chứa URL. Role runtime không có DDL nên fallback cũng không chạy được, chỉ gây lỗi khó hiểu |
| Không đưa giá trị lên dòng lệnh | Giá trị nằm trong `.env` (đã được `.gitignore`) hoặc secret của CI. Khi chạy, chỉ truyền **tên** biến (`docker compose run --rm -e GPU_MARKETPLACE_MIGRATION_DATABASE_URL api alembic upgrade head`) để Compose lấy giá trị từ môi trường của shell; hoặc chạy Alembic từ host qua cổng loopback với biến đã nạp từ `.env` |
| Không gắn vào service thường trực | `compose.yaml` **không** khai báo biến migration trong `environment` của `api`/`manager`, nên container thường trực không bao giờ giữ owner DSN. Container migration dùng `--rm` |
| Không in ra | `env.py` và mọi tool không log URL; lỗi kết nối chỉ ghi tên exception (giống `tools/compose_smoke.py`). `alembic.ini` giữ `sqlalchemy.url` rỗng |
| Tách credential | Owner DSN ≠ DSN runtime ≠ mật khẩu login role ≠ secret JWT/service token. `.env.example` chỉ chứa giá trị dev giả, có ghi chú phải thay |
| CI | Postgres service của CI dùng mật khẩu tạm của job, nạp từ secret hoặc sinh trong job; không log `env` |

Phạm vi file: `migrations/env.py` thuộc TV2; `compose.yaml`, `.env.example`, `.github/workflows/foundation.yml` là shared infra (D1, D8, D9).

### 9.2. Hàng rào bảo vệ DB test trước `DROP`/`CREATE` (sửa theo review P1-2)

Chỉ kiểm hậu tố `_test` là chưa đủ: một DB dev hoặc DB của người khác vẫn có thể trùng tên, và cấu hình nhầm có thể trỏ test vào cluster dùng chung. Fixture phải qua **tất cả** điều kiện dưới đây; vi phạm bất kỳ điều nào thì **abort cả test session** (không skip lặng lẽ, không chạy tiếp):

| # | Hàng rào | Chặn được gì |
|---|---|---|
| G1 | Opt-in tường minh: biến `GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS=1` phải được đặt. Không có biến này thì test DB báo `NOT_RUN` | Chạy nhầm khi chỉ có `TEST_DATABASE_URL` sót lại trong môi trường |
| G2 | Tên DB khớp **toàn bộ** mẫu `^gpu_marketplace_test(_[a-z0-9]{1,16})?$`; không chỉ kiểm hậu tố. Danh sách cấm cứng: `postgres`, `template0`, `template1`, `gpu_marketplace` | Tên tùy ý như `prod_test`, `x_test` |
| G3 | Host phải là loopback (`localhost`, `127.0.0.1`, `::1`) | Trỏ nhầm sang server dùng chung/từ xa |
| G4 | So với `GPU_MARKETPLACE_DATABASE_URL` và `GPU_MARKETPLACE_MIGRATION_DATABASE_URL` (nếu có): cùng host + port + tên DB thì từ chối | Test dùng nhầm DB dev đang chạy |
| G5 | `DROP`/`CREATE` chạy trên connection tới DB bảo trì `postgres`, không bao giờ `DROP` DB của chính connection hiện tại; dùng tên DB đã qua G2 và quote bằng identifier, không ghép chuỗi | SQL injection qua tên DB; drop nhầm DB khác |
| G6 | **Marker sở hữu:** ngay sau `CREATE DATABASE`, đặt `COMMENT ON DATABASE <tên> IS 'gpu-marketplace-disposable-test-db'`. Trước khi `DROP` một DB đã tồn tại, phải đọc được đúng marker này qua `pg_shdescription`; không có marker thì **từ chối drop** và yêu cầu người dùng xử lý thủ công. Marker là comment, không phải bảng, nên không làm sai yêu cầu đúng 10 bảng | DB trùng tên nhưng không do test tạo ra |
| G7 | Trước `DROP`, kiểm `pg_stat_activity`: nếu còn connection tới DB đó mà `application_name` khác `gpm-pytest` thì từ chối. Mọi connection của test đặt `application_name=gpm-pytest`. Không dùng `DROP DATABASE ... WITH (FORCE)` | Drop DB đang có người/khác tiến trình dùng |
| G8 | `TRUNCATE` giữa các test chỉ chạy khi `current_database()` khớp G2 **và** marker G6 có mặt (kiểm lại mỗi lần, không cache) | `search_path`/connection bị đổi giữa chừng |
| G9 | Test không gọi `docker compose down -v`, không đụng volume `postgres-data`, không `DROP ROLE`. Downgrade migration chỉ chạy trong DB test đã qua G1–G6 | Mất dữ liệu dev; xóa role dùng chung cluster |

Kiểm chứng bằng unit test **không cần PostgreSQL**: từng hàng rào G1–G4 có một ca vi phạm phải abort; G5–G8 kiểm trên DB test thật ở GPU-002-D (ví dụ tạo sẵn một DB trùng tên mà không có marker → fixture từ chối drop).

### 9.3. Cô lập cluster PostgreSQL cho test (sửa theo review R5, P1)

**Vấn đề revision 2:** hàng rào G1–G9 chỉ bảo vệ **database**. Nhưng role là đối tượng **toàn cluster**: nếu fixture chạy bootstrap role trên cluster mà môi trường dev cũng dùng, nó có thể đổi mật khẩu hoặc quyền của `gpm_api_app`/`gpm_manager_app` mà API/Manager dev đang dùng, dù DB test đã được cô lập đúng.

**Quyết định đề xuất:** mọi test có thao tác bootstrap role, `CREATE/DROP DATABASE` hoặc downgrade migration **bắt buộc** chạy trên một **cluster PostgreSQL riêng, dùng xong bỏ** (disposable). Không có cluster như vậy thì các test này báo `NOT_RUN`, không fallback sang cluster dev.

| Môi trường | Cách cấp cluster test | Ghi chú |
|---|---|---|
| CI | `services: postgres` của job `python` trong `foundation.yml` (D8): mỗi job một container mới, không volume, mật khẩu tạm của job, publish ra **cổng host khác `5432`** để thỏa C1 giống môi trường local. Một bước workflow đặt marker cluster (C3) ngay sau khi service sẵn sàng | Không đụng `compose.yaml`, không thêm service sản phẩm |
| Local | Container tạm chạy riêng ngoài Compose project sản phẩm: cùng image digest với `compose.yaml`, dữ liệu trên `tmpfs`, `--rm`, bind `127.0.0.1` với **cổng khác** cổng dev; một script helper khởi động container và đặt marker. Lệnh cụ thể ghi ở runbook GPU-002-E | Không phải service thứ 6 trong topology; `tests/test_compose_topology.py` giữ nguyên. Cách cấp này cần nhóm trưởng duyệt (D12) |

**Hàng rào cấp cluster** — kiểm **trước** mọi câu lệnh bootstrap/DDL; vi phạm thì abort cả test session, không chạy câu SQL ghi nào:

| # | Hàng rào | Chặn được gì |
|---|---|---|
| C1 | Cổng của `GPU_MARKETPLACE_TEST_DATABASE_URL` khác cổng trong DSN dev, DSN migration và `POSTGRES_HOST_PORT` (mặc định `5432`) | Trỏ nhầm vào service `postgres` của Compose dev |
| C2 | Cluster chỉ được chứa các DB: `postgres`, `template0`, `template1`, DB marker (C3) và DB khớp mẫu G2. Có DB nào khác (ví dụ `gpu_marketplace`) thì từ chối | Cluster dev hoặc cluster dùng chung có dữ liệu thật |
| C3 | **Marker cluster có token:** script khởi động cluster tạo DB rỗng `gpm_disposable_test_cluster` và đặt `COMMENT ON DATABASE` chứa một token ngẫu nhiên; cùng token được truyền cho test qua `GPU_MARKETPLACE_TEST_CLUSTER_TOKEN`. Fixture đọc comment qua `pg_shdescription` và so khớp chính xác; thiếu hoặc khác thì từ chối. DB marker không có bảng, nên không ảnh hưởng yêu cầu đúng 10 bảng trong DB ứng dụng | Cluster không do harness test tạo ra |
| C4 | Trước bootstrap lần đầu của session: nếu `gpm_api_app`/`gpm_manager_app` đã tồn tại mà marker C3 hợp lệ thì vẫn được dùng (chạy lại trên cùng cluster tạm); nếu marker không hợp lệ thì C3 đã chặn từ trước. Bootstrap trong test luôn ở chế độ create-only, **không bao giờ** dùng `--rotate-password` | Đổi mật khẩu/quyền của role đang được môi trường khác dùng |
| C5 | Mật khẩu login role trong test được sinh ngẫu nhiên cho từng cluster tạm, chỉ giữ trong bộ nhớ tiến trình test; test không đọc `.env` dev | Lộ hoặc ghi đè credential dev |

**Test bắt buộc kiểm chứng cơ chế cô lập** (GPU-002-D; hiện `NOT_RUN`):

| Test | Loại | Kịch bản | PASS khi |
|---|---|---|---|
| `ISO-01-PORT-GUARD` | Unit, không cần PostgreSQL | URL test trùng cổng DSN dev; trùng `POSTGRES_HOST_PORT` | Fixture abort trước khi mở connection |
| `ISO-02-TOKEN-GUARD` | Unit + cluster tạm | Thiếu `GPU_MARKETPLACE_TEST_CLUSTER_TOKEN`; token sai; DB marker không có comment | Abort; số dòng `pg_roles` và `pg_database` không đổi |
| `ISO-03-FOREIGN-DB` | Cluster tạm | Tạo thêm DB `gpu_marketplace` trong cluster tạm rồi khởi động fixture | Abort theo C2, không chạy bootstrap/DDL; sau đó xóa DB giả lập |
| `ISO-04-NO-PASSWORD-CHANGE` | Cluster tạm | Tạo trước `gpm_api_app` với mật khẩu và thuộc tính đúng; ghi lại `rolpassword` (đọc `pg_authid` bằng owner của cluster tạm) và thuộc tính; chạy bootstrap create-only | `rolpassword`, thuộc tính và membership **giữ nguyên**; bootstrap thoát mã 0 |
| `ISO-05-ATTRIBUTE-DRIFT` | Cluster tạm | Tạo trước `gpm_api_app` với `CREATEDB` (lệch mong đợi); chạy bootstrap create-only | Bootstrap thoát mã khác 0, **không** `ALTER` role; thuộc tính vẫn như trước |
| `ISO-06-ROTATE-EXPLICIT` | Cluster tạm | Chạy bootstrap không có `--rotate-password`, rồi có cờ | Chỉ lần có cờ mới đổi `rolpassword` |
| `ISO-07-NO-DEV-CLUSTER` | Unit, không cần PostgreSQL | Không đặt URL/token test | Mọi test cần cluster báo `NOT_RUN` (skip có lý do), không thử kết nối DSN dev |

Ghi chú bằng chứng: `ISO-03..06` tự tạo tình huống "giống cluster dùng chung" **bên trong** cluster tạm, nên không bao giờ cần chạm vào cluster dev để chứng minh cơ chế cô lập.

## 10. Truy vết tới tiêu chí nghiệm thu

| Test / tiêu chí | Đối tượng kiểm | P1B-AC | Trạng thái dự kiến sau GPU-002 |
|---|---|---|---|
| Fresh `upgrade head` = đúng 10 bảng + `alembic_version` | Toàn schema | AC-01 | Có thể PASS |
| Parity catalog/ORM | Mục 2–4 | AC-02 | Có thể PASS |
| `DBP-01-COMPOSITE-WORKER` | `fk_jobs_listing_worker` | AC-03 | Có thể PASS |
| `DBP-02-ROLE` | `fk_workers_user_role`, `fk_jobs_client_user_role` | AC-03 | Có thể PASS |
| `DBP-04-LISTING-CHECK` | `ck_gpu_listings_allocated_range` | AC-04 | Có thể PASS |
| `DBP-05` (phần áp dụng) | `pk_simulation_references`, `uq_jobs_client_idempotency` song song | AC-04 | Một phần; allocations/results/disputes/contributions `BLOCKED` (Phase 2–3) |
| Negative handoff: digest, key bytes, capacity, duplicate key | `ck_simulation_references_digest_format`, `ck_worker_public_keys_raw_len`, `ck_gpu_listings_*`, `uq_jobs_client_idempotency` | AC-04 | Có thể PASS |
| `DBP-03-FIFO-TIE` / `DBTX-01` (phần lưu trữ) | `enqueue_seq` dưới Listing lock, hai connection, `submitted_at` bằng nhau | AC-05 | Có thể PASS phần lưu trữ; chọn head bởi Manager `NOT_RUN` |
| Job + reference cùng UoW, lỗi một INSERT rollback cả hai | UoW `GPU-002-C` | AC-06 | Có thể PASS; **không** chứng minh oracle hay `TX-SUBMIT` |
| API không SELECT được `simulation_references`; Simulator không có DB | Grants mục 6, compose test hiện có | AC-07 | Phụ thuộc D1; nếu hoãn role split → `BLOCKED` |
| `DBP-06` (phần áp dụng) | FK RESTRICT key, `trg_worker_public_keys_guard_update`, `trg_simulation_references_immutable` | AC-07 | Một phần; `signed_results` `BLOCKED` |
| `DBP-09` (phần áp dụng) | `trg_jobs_guard_delete` | AC-07 | Một phần; điều kiện OPEN Dispute `BLOCKED` |
| Migration round-trip + foundation pytest/Vitest/Compose smoke | Mục 9 | AC-08 | Có thể PASS |
| `DBP-07/08/10/11/12`, `DBTX-02..18` | Bảng Phase 2–3 | — | `NOT_RUN` / `BLOCKED` |

## 11. Quyết định cần nhóm trưởng

| ID | Câu hỏi | Đề xuất của TV2 | Mức |
|---|---|---|---|
| D1 | Tách DB role cho API/Manager ngay Phase 1B hay hoãn? | **Ngay Phase 1B**: một script bootstrap tạo cả group và login role, chạy trước migration (init script khi volume rỗng + lệnh chạy lại cho volume cũ); migration chỉ kiểm tra group tồn tại và GRANT (mục 6.2); sửa `compose.yaml`/`.env.example` (shared infra) | L2 |
| D2 | `trg_jobs_guard_update` có ràng buộc theo role? | **Có** — phân loại caller bằng `pg_auth_members` đệ quy, không dùng `pg_has_role()`; API chỉ `QUEUED→CANCELLED`, Manager chỉ cạnh của mình, owner/superuser vẫn bị (a)–(c), role lạ bị từ chối (mục 7) | L2 |
| D3 | Guarded delete Phase 1B = trigger terminal + 23 ngày, mở rộng ở Phase 3? | **Có** | L2 |
| D4 | Partial unique một key active/Worker (§9.2 ghi "Proposed policy")? | **Tạo** — nằm trong §9 đã duyệt, chặn nhập nhằng khi verify | L1 nếu xác nhận là đã duyệt |
| D5 | Constraint trigger `DEFERRABLE INITIALLY DEFERRED` bắt buộc mỗi Job có đúng một reference khi commit? | **Không ở Phase 1B**; để TV5 + nhóm trưởng quyết định cùng spec `DEC-P1-04` | L2 nếu thêm |
| D6 | Default thời gian `clock_timestamp()` thay vì `now()`? | `clock_timestamp()` — nhất quán với quy ước trusted clock §9.1 | L1 |
| D7 | `updated_at` do trigger đặt thay vì caller truyền? | **Trigger** — caller không backdate được, grants không cần cột này | L1 |
| D8 | PostgreSQL service trong CI `foundation.yml`? | **Có**, cùng image digest | L1 (shared infra) |
| D9 | Cách chạy migration trong Compose? | `docker compose run --rm` container `api` chạy `alembic upgrade head`; owner DSN qua biến riêng `GPU_MARKETPLACE_MIGRATION_DATABASE_URL`, chỉ truyền tên biến, không fallback, không gắn vào service thường trực (mục 9.1) | L1 (shared infra) |
| D10 | Mã lỗi trigger: SQLSTATE 23000 + `CONSTRAINT` name? | **Có** | L1 |
| D11 | Chính sách bảo vệ DB test trước `DROP`/`CREATE`/`TRUNCATE`? | Hàng rào G1–G9: opt-in tường minh, tên khớp toàn bộ mẫu, chỉ loopback, khác DSN dev/migration, marker comment do test tạo, kiểm connection khác, abort session khi vi phạm (mục 9.2) | L1 (an toàn dữ liệu; nhóm trưởng xác nhận) |
| D12 | Cluster PostgreSQL riêng cho test có bootstrap role/DDL? | **Bắt buộc**: CI dùng `services: postgres` mới mỗi job; local dùng container tạm (`tmpfs`, `--rm`, cổng khác, ngoài Compose project sản phẩm) do script helper khởi động và đặt marker token; hàng rào C1–C5; bootstrap create-only, đổi mật khẩu chỉ qua cờ tường minh; test cô lập `ISO-01..07` (mục 9.3) | L1 (an toàn dữ liệu + shared CI; nhóm trưởng xác nhận) |

### 11.1. Quyết định đã ghi nhận (cập nhật 25/10/2026)

Bảng này chỉ ghi lại quyết định nhóm trưởng đã đưa ra và nơi lưu bản ghi; nội dung kỹ thuật của từng mục vẫn là phần đề xuất ở trên. Mục không có trong bảng vẫn `PENDING LEAD DECISION`.

| ID | Quyết định | Ngày | Bản ghi | Hiện thực |
|---|---|---|---|---|
| D1 | **APPROVED** — thiết kế role bootstrap + grant; re-land qua PR mới sau khi PR #14 bị revert vì quy trình | 24/10/2026 | [PR #22, 06:36Z](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/22#issuecomment-6380984025); [PR #22, 13:26Z](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/22#issuecomment-6384777132) | PR #27 (đang review); wiring `compose.yaml`/`.env.example` là PR riêng |
| D2 | **APPROVED** — `trg_jobs_guard_update` theo mục 7 | 25/10/2026 | [PR #27 (chuyển tiếp từ nhóm trưởng)](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/27#issuecomment-6387687194) | PR #28 (draft, xếp trên #27) |
| D3 | **APPROVED cho Phase 1B** — `trg_jobs_guard_delete` theo mục 8; phần Dispute `OPEN` của `DBP-09` là `BLOCKED` tới Phase 3; không bật cleanup production tới khi có bằng chứng giữ Dispute chưa giải quyết và test tích hợp | 25/10/2026 | [PR #27 (chuyển tiếp từ nhóm trưởng)](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/27#issuecomment-6387687194) | PR #29 (draft, xếp trên #28) |
| D8 | **APPROVED** — PostgreSQL 16.15 service dùng một lần trong CI, mật khẩu sinh trong job, marker an toàn của cluster; không đổi runtime production hay topology Compose | 24/10/2026 | [PR #24](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/24#issuecomment-6386249190) | PR #24 (đã merge) |

Ghi chú: D6 (`clock_timestamp()`), D10 (SQLSTATE 23000 + tên trigger), D11 và D12 (hàng rào DB test, cluster dùng một lần) đang được code của D2/D3/D8 và test dùng tới nhưng chưa có quyết định riêng; nhờ nhóm trưởng xác nhận.

## 12. Mâu thuẫn và điểm mơ hồ phát hiện khi đối chiếu

| ID | Phát hiện | Xử lý trong matrix |
|---|---|---|
| A1 | §9.2-07 chỉ yêu cầu `started_at IS NULL` khi QUEUED/CANCELLED; **không** yêu cầu `NOT NULL` khi RUNNING/COMPLETED/FAILED | Giữ đúng thiết kế, không tự thêm CHECK (thêm là đổi contract). Có thể đề xuất ở Phase 2 |
| A2 | Phase 1C §2.4 ghi quy tắc trim 4 ký tự ASCII như đã duyệt, nhưng API Contract v0.6 §4.5/§14.3 trên `main` vẫn ghi `NEEDS_OWNER_DECISION` | Không thêm CHECK normalization cho `login_name`; seed users `BLOCKED` tới khi đồng bộ tài liệu |
| A3 | §9.2-05 ghi partial unique active key là "Proposed policy" bên trong §9 đã được duyệt toàn bộ ở §10 | Đưa vào D4 |
| A4 | Thứ tự replay idempotency và kiểm tra Listing PAUSED (Phase 1E §2.3) chưa thống nhất giữa API Contract §8 và DB Design §11.3 | **Không ảnh hưởng schema** (UNIQUE giữ nguyên); thuộc TV4/TV5 + nhóm trưởng |
| A5 | Header Phase 1B/handoff còn ghi "chưa commit", trong khi PR #4 đã merge; ADR-002 §8 còn ghi ADR-008 "PROPOSED" | Doc drift L0, đề xuất PR `docs/` riêng |
| A6 | Compose: API/Manager đang chạy bằng superuser | Mục 6.1, D1 |

## 13. Inter-Phase Impact Review — XPH-GPU-002-01

- Source phase / owner: GPU-002 / Thành viên 2
- Changed file(s), base SHA → target SHA: thêm `docs/architecture/phases/phase1b_gpu002a_schema_matrix.md` trên `main@cceffbf` (branch `docs/gpu-002-a-schema-matrix`, PR #9). Revision 1 = commit `903c5c2`; revision 2 = commit `4fe8c8a`; revision 3 = commit kế tiếp trên cùng branch, sửa P1 cô lập test cluster theo review lần 2 ngày 24/10/2026
- Changed contract/assumption (before → after): chưa có schema thực → **đề xuất** tên constraint (contract ánh xạ lỗi), column-level grants, trigger lifecycle/guarded delete, role DB tách cho API/Manager. **Revision 2 thêm:** role tạo ở bước bootstrap trước migration (không còn trong migration); trigger phân loại caller API/Manager/owner/unknown, Manager bị giới hạn cạnh của mình; owner DSN đổi sang biến riêng `GPU_MARKETPLACE_MIGRATION_DATABASE_URL`; hàng rào DB test G1–G9 với biến opt-in mới. **Revision 3 thêm:** test có bootstrap/DDL chỉ chạy trên cluster PostgreSQL tạm riêng (CI service mới mỗi job; local container `tmpfs` ngoài Compose); biến `GPU_MARKETPLACE_TEST_CLUSTER_TOKEN`; hàng rào C1–C5; bootstrap mặc định create-only, đổi mật khẩu chỉ qua cờ `--rotate-password`; test cô lập `ISO-01..07`
- Classification: `POTENTIAL_IMPACT` (tài liệu đề xuất; thành `CONFIRMED_IMPACT` khi D1–D12 được quyết định)
- Affected phase(s), owner(s): GPU-003/Thành viên 3 (grants `users`, provisioning chạy bằng owner DSN theo mục 9.1); GPU-004/Thành viên 4 (column grants Listing, `allocated_gpu_count` không ghi được từ API, trigger `updated_at`, hàng rào DB test nếu dùng chung fixture); GPU-005/Thành viên 5 (INSERT `jobs` không có `status`, `simulation_references` không RETURNING/SELECT, tên `uq_jobs_client_idempotency`, D5, API chỉ được `QUEUED→CANCELLED`); nhóm trưởng (script bootstrap role + init script, Compose DSN, biến migration riêng, `.env.example`, CI postgres service, cách chạy migration, biến opt-in test, cluster test tạm cho CI và local, biến token cluster); owner Phase 2 khi được giao (Manager chỉ được cạnh `QUEUED→RUNNING`, `RUNNING→COMPLETED/FAILED`)
- Impact: schema/permissions/migration/CI/test/config
- Required updates / responsible person / deadline: nhóm trưởng quyết định D1–D12; TV3/4/5 rà soát grants, tên constraint, phân loại caller và fixture test; hạn: trước khi bắt đầu `GPU-002-B`
- Verification: chưa có; mọi test `NOT_RUN` (kể cả `ISO-01..07`). Technical review revision 1: `CHANGES REQUESTED`; revision 2: `BLOCKED — CHANGES REQUESTED` (1 P1: test cluster isolation), cùng ngày 24/10/2026; revision 3 chờ review lại. Independent human reviews: 0/2
- Source owner acknowledgement: Thành viên 2 — `PENDING` (sau khi gửi revision 3)
- Consumer owner acknowledgement(s): Thành viên 3 / 4 / 5 — `PENDING`
- Leader coordination: `PENDING` (D1–D12: PENDING LEAD DECISION; đang review lại revision 3)
- Gate status: `AWAITING_CROSS_PHASE_ACK`
- Linked change-control record (L2/L3, nếu có): cần tạo cho D1, D2, D3 (và D5 nếu thêm)

## 14. Phản hồi technical review — revision 2 (24/10/2026)

Review revision 1: **CHANGES REQUESTED / NOT APPROVED FOR MERGE**. Schema matrix 10 bảng được đánh giá cơ bản phù hợp Database Design; 4 điểm cần sửa:

| # | Mức | Yêu cầu review | Đã sửa ở đâu | Tóm tắt thay đổi |
|---|---|---|---|---|
| R1 | P1 | Thiết kế lại thứ tự khởi tạo group role và login role; init script không được phụ thuộc role chỉ tạo trong migration chạy sau | Mục 6.2, D1 | Một script bootstrap idempotent tạo cả group và login role, chạy **trước** migration qua init script (volume rỗng) hoặc lệnh chạy lại (volume cũ). Migration chỉ kiểm tra group tồn tại rồi GRANT; không tạo/xóa role |
| R2 | P1 | Bảo vệ DB test khi DROP/CREATE, không chỉ dựa vào hậu tố `_test` | Mục 9 (hàng "An toàn DB test"), 9.2, D11 | 9 hàng rào G1–G9: opt-in tường minh, khớp toàn bộ mẫu tên + danh sách cấm, chỉ loopback, khác DSN dev/migration, DROP/CREATE từ DB bảo trì, marker comment sở hữu, kiểm connection khác, kiểm lại trước TRUNCATE, không đụng volume/role |
| R3 | P2 | Làm rõ cách kiểm tra quyền trong `trg_jobs_guard_update`, đặc biệt với superuser | Mục 7, D2 | Phân loại caller bằng `pg_auth_members` đệ quy từ `current_user` (`SECURITY INVOKER`), không dùng `pg_has_role()`. Superuser/owner không được miễn quy tắc (a)–(c); role lạ bị từ chối; ghi rõ giới hạn `DISABLE TRIGGER`/`session_replication_role` và các test bắt buộc |
| R4 | P2 | Điều chỉnh hướng dẫn cấp owner DSN khi chạy migration để tránh lộ credential | Mục 9 (hàng "Chạy migration"), 9.1, D9 | Biến riêng `GPU_MARKETPLACE_MIGRATION_DATABASE_URL`, chỉ truyền tên biến, không fallback sang DSN runtime, không gắn vào service thường trực, không log URL |

D1–D11 vẫn ở trạng thái `PROPOSED` cho đến khi có quyết định của nhóm trưởng. Revision này không thêm bảng, cột, service hay role nghiệp vụ; biến môi trường mới (`GPU_MARKETPLACE_MIGRATION_DATABASE_URL`, `GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS`) và hai login role DB là đề xuất cấu hình chờ D1/D9/D11.

### 14.1. Revision 3 — phản hồi review lần 2 (24/10/2026)

Review revision 2: **BLOCKED — CHANGES REQUESTED**. Bốn finding R1–R4 được xác nhận đã xử lý; còn 1 P1:

| # | Mức | Yêu cầu review | Đã sửa ở đâu | Tóm tắt thay đổi |
|---|---|---|---|---|
| R5.1 | P1 | Bắt buộc dùng PostgreSQL test cluster độc lập cho test có thao tác bootstrap role | Mục 9 (hàng "An toàn DB test"), 9.3, D12 | CI: service postgres mới mỗi job; local: container tạm `tmpfs`, `--rm`, cổng khác, ngoài Compose project sản phẩm. Hàng rào C1–C3 (cổng khác dev, cluster chỉ chứa DB được phép, marker token) chặn trước mọi SQL ghi. Không có cluster riêng → `NOT_RUN`, không fallback sang dev |
| R5.2 | P1 | Không tự động đổi mật khẩu hoặc quyền của role đã tồn tại trên cluster dùng chung | Mục 6.2 (bước 0), 9.3 (C4, C5) | Bootstrap mặc định create-only: role đã có thì chỉ kiểm tra, lệch thì dừng mã khác 0, không `ALTER`. Đổi mật khẩu chỉ qua cờ `--rotate-password`, không bao giờ gọi từ init script hay test. Mật khẩu test sinh ngẫu nhiên cho cluster tạm |
| R5.3 | P1 | Bổ sung test xác minh cơ chế cô lập | Mục 9.3 | `ISO-01..07`: chặn cổng dev, chặn thiếu/sai token, chặn cluster có DB lạ, không đổi `rolpassword`/thuộc tính role có sẵn, phát hiện lệch thuộc tính mà không sửa, chỉ đổi mật khẩu khi có cờ, không cluster thì `NOT_RUN`. Tất cả hiện `NOT_RUN` |

Trạng thái merge gate không đổi: D1–D12 `PENDING LEAD DECISION`; ACK TV3/TV4/TV5 `PENDING`; independent human reviews 0/2; PostgreSQL integration tests `NOT_RUN`.
