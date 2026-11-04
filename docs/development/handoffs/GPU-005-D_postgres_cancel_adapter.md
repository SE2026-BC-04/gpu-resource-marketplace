# GPU-005-D — PostgreSQL TX-CANCEL adapter (bàn giao TV2 → TV5)

**Trạng thái:** Draft/HOLD, chờ review độc lập và CI trên đúng head. Không đổi contract/API/migration/code của TV5. Xếp chồng trên #34 (cần #33/#34 để có `jobs/cancel_ports.py`, `jobs/cancel.py`).

## 1. Phạm vi
- `backend/src/gpu_marketplace/repositories/jobs.py`: `PostgresJobLocatorReader`, `PostgresJobCancelUnitOfWork` (+ giao dịch dùng một lần `PostgresJobCancelTransaction`).
- Chỉ `QUEUED → CANCELLED` (kể cả Listing `PAUSED`). Không đụng allocation, `allocated_gpu_count`, `simulation_references`, reputation.
- Không thêm bảng/migration/service. PG-CANCEL-15 (Manager thật) vẫn `BLOCKED` chờ Phase 2.

## 2. Hành vi
| Bước | SQL / quy tắc |
|---|---|
| Locator | kiểm `current_user` và `session_user` (như `__enter__`) **trước khi** đọc `jobs`; rồi `SELECT listing_id FROM jobs WHERE id=:job_id` (không khóa), phiên ngắn. Sai role/đăng nhập → `DependencyUnavailable`, không đọc Job (không có existence oracle) |
| `__enter__` | `READ COMMITTED`; `current_user ∈ {gpm_api_app, gpm_api_rw}` **và** `session_user ∈ ALLOWED_RUNTIME_LOGINS` (mặc định `{gpm_api_app}`), nếu không → `DependencyUnavailable`; `set_config('lock_timeout'/'statement_timeout', …, true)` |
| `lock_listing` | `SELECT id FROM gpu_listings WHERE id=:l FOR UPDATE OF gpu_listings` (luôn trước Job; gọi `lock_job` trước → `RuntimeError`) |
| `lock_job` | `SELECT <11 cột JobRecord> FROM jobs WHERE id=:j FOR UPDATE` (đọc mới sau khóa; `None` nếu không có) |
| `cancel_queued` | `UPDATE jobs SET status='CANCELLED', terminal_at=clock_timestamp() WHERE id,listing_id,client_id khớp AND status='QUEUED' RETURNING …`; 0 dòng → phân loại `MISSING/NOT_OWNER/NOT_QUEUED` dưới khóa → `CancelGuardRejected` |
| `commit` | đặt outcome `COMMIT_OUTCOME_UNKNOWN` trước `session.commit()` |
| `__exit__` | rollback nếu chưa commit, rồi `close()` đúng một lần; trả `False`. Exception đang bay luôn thắng (lỗi cleanup chỉ được log). Body sạch: lỗi lập trình bất ngờ (không phải SQLAlchemy) từ rollback/close được raise lại, kể cả sau COMMIT (`outcome` vẫn `COMMITTED`); lỗi storage lúc cleanup trước COMMIT → `DependencyUnavailable`, sau COMMIT chỉ log |

## 3. Ánh xạ lỗi
| Tình huống | Adapter | Service/API |
|---|---|---|
| Job không tồn tại / không thuộc Client / sai Listing | `CancelGuardRejected(MISSING|NOT_OWNER)` hoặc `lock_job → None` | 404 `JOB_NOT_FOUND` |
| Job không `QUEUED` | `CancelGuardRejected(NOT_QUEUED)` | 409 `JOB_NOT_CANCELLABLE` |
| Mọi `SQLAlchemyError` ở begin/lock/update/locator (mất kết nối, `lock_timeout` 55P03, `statement_timeout` 57014, quyền…) | `DependencyUnavailable` (`from None`, chỉ log type + SQLSTATE) | 503 |
| COMMIT lỗi, SQLSTATE lớp `23`/`40` (server chắc chắn abort) | `DependencyUnavailable`, outcome `ROLLED_BACK` | 503 |
| COMMIT lỗi khác (mất kết nối, mất ack…) | `CommitOutcomeUnknown` (outcome `COMMIT_OUTCOME_UNKNOWN`), **không retry** | service để lan ra; TV5 quyết định ánh xạ HTTP |

## 4. Tích hợp (TV5)
```python
engine = create_engine(<URL đăng nhập gpm_api_app>)   # không dùng owner/superuser
sessions = sessionmaker(engine, expire_on_commit=False)
# Mặc định chỉ chấp nhận đăng nhập gốc gpm_api_app (session_user); không truyền allowed_session_users ở production.
service = JobCancelService(
    locator_reader=PostgresJobLocatorReader(sessions),
    uow=PostgresJobCancelUnitOfWork(sessions),         # lock_timeout_ms=5000, statement_timeout_ms=10000 mặc định
)
```
`CommitOutcomeUnknown` hiện chưa có ánh xạ HTTP trong #33; cần TV5/nhóm trưởng chốt (không đoán ở adapter).

## 5. Quyết định cần review
1. `lock_timeout` 5 s / `statement_timeout` 10 s là mặc định do TV2 chọn (tránh treo thread API khi bị giữ khóa Listing); ngoài design hiện hành → cần xác nhận.
2. Mọi `SQLAlchemyError` → 503 (cùng mẫu `PostgresListingUnitOfWork` của #31), kể cả lỗi quyền; log có SQLSTATE để phân biệt.
3. `TransactionOutcome` được khai báo lại trong `repositories/jobs.py` (trùng #31); gộp thành module chung khi cả hai đã merge.

## 6. Bằng chứng (chạy cục bộ của TV2, chưa phải CI)
Môi trường: cluster dùng một lần `postgres:16.15-bookworm` (đúng digest trong `compose.yaml`) ở `127.0.0.1:55432`, `timezone = Asia/Bangkok`, đi qua guard `db_safety`.
- Nhánh này (gồm #34 `628d205` đã merge thường): `pytest backend/tests tests` → **712 passed, 0 failed, 0 skipped**.
- Bộ test của adapter: `test_jobs_cancel_adapter_postgres.py` (PostgreSQL thật) và `test_jobs_cancel_adapter_faults.py` (fake Session, không cần PostgreSQL).
- **Phạm vi bằng chứng về role:** các test chức năng dùng đăng nhập owner của cluster dùng một lần cộng `SET ROLE gpm_api_app` và truyền `allowed_session_users` tường minh, nên chứng minh hành vi theo role hiệu lực. Hai test bổ sung cho đăng nhập gốc: một test **âm** (owner + `SET ROLE` bị từ chối theo mặc định, ở locator và transaction) và một test **dương** (`test_native_api_login_cancels_with_default_allowlist_and_restricted_grants`: đăng nhập thật `gpm_api_app`, allowlist mặc định, hủy thành công, trạng thái bền chỉ đổi ở Job). Compose smoke chung không thay thế bằng chứng cho đường Cancel.
- Ánh xạ: PG-CANCEL-01,05,06 (thành công/PAUSED/lặp), 02,03,04,08 (404/409/phân loại 0 dòng), 07 (rollback), 09 (role + từ chối owner DSN), 10,11,12 (đồng hồ DB, 2 cancel đồng thời, thứ tự khóa Listing→Job), 13 (mất kết nối/terminate backend/lock_timeout, không lộ driver text, không rò connection), 14 (mất ack, mất kết nối khi COMMIT, abort 40001/40P01/23514, không retry).
- CI: **chưa có** run trên đúng head của PR xếp chồng này (base là nhánh #34, không phải `main`). CI của #34 hoặc của head cũ không thay thế.
- Trạng thái stack: Alembic head ở stack vẫn `0003_phase1b_jobs_guard_update`; `main` đã có D3 `0004` và D7 `0005_listing_d7`. Phải sync `main` bằng merge thường sau khi #33 và #34 vào, rồi chạy lại.
- Còn mở: Thang duyệt `lock_timeout`/`statement_timeout` và chính sách 503, ánh xạ HTTP của `CommitOutcomeUnknown`, hai reviewer L2 độc lập.
