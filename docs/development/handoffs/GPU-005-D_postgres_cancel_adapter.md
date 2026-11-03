# GPU-005-D — PostgreSQL TX-CANCEL adapter (bàn giao TV2 → TV5)

**Trạng thái:** đề xuất, chờ review độc lập. Không đổi contract/API/migration/code của TV5. Xếp chồng trên #34 (cần #33/#34 để có `jobs/cancel_ports.py`, `jobs/cancel.py`).

## 1. Phạm vi
- `backend/src/gpu_marketplace/repositories/jobs.py`: `PostgresJobLocatorReader`, `PostgresJobCancelUnitOfWork` (+ giao dịch dùng một lần `PostgresJobCancelTransaction`).
- Chỉ `QUEUED → CANCELLED` (kể cả Listing `PAUSED`). Không đụng allocation, `allocated_gpu_count`, `simulation_references`, reputation.
- Không thêm bảng/migration/service. PG-CANCEL-15 (Manager thật) vẫn `BLOCKED` chờ Phase 2.

## 2. Hành vi
| Bước | SQL / quy tắc |
|---|---|
| Locator | `SELECT listing_id FROM jobs WHERE id=:job_id` (không khóa), phiên ngắn |
| `__enter__` | `READ COMMITTED`; `current_user ∈ {gpm_api_app, gpm_api_rw}` nếu không → `DependencyUnavailable`; `set_config('lock_timeout'/'statement_timeout', …, true)` |
| `lock_listing` | `SELECT id FROM gpu_listings WHERE id=:l FOR UPDATE OF gpu_listings` (luôn trước Job; gọi `lock_job` trước → `RuntimeError`) |
| `lock_job` | `SELECT <11 cột JobRecord> FROM jobs WHERE id=:j FOR UPDATE` (đọc mới sau khóa; `None` nếu không có) |
| `cancel_queued` | `UPDATE jobs SET status='CANCELLED', terminal_at=clock_timestamp() WHERE id,listing_id,client_id khớp AND status='QUEUED' RETURNING …`; 0 dòng → phân loại `MISSING/NOT_OWNER/NOT_QUEUED` dưới khóa → `CancelGuardRejected` |
| `commit` | đặt outcome `COMMIT_OUTCOME_UNKNOWN` trước `session.commit()` |
| `__exit__` | rollback nếu chưa commit, rồi `close()` đúng một lần; không nuốt/ghi đè exception; trả `False` |

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

## 6. Bằng chứng (đĩa PostgreSQL 16.15 tạm, port 55433, `db_safety` guard)
- `uv run --project backend --locked --group dev pytest backend/tests/test_jobs_cancel_adapter_postgres.py` → **24 passed**.
- Toàn bộ `backend/tests` → **686 passed**.
- Ánh xạ: PG-CANCEL-01,05,06 (thành công/PAUSED/lặp), 02,03,04,08 (404/409/phân loại 0 dòng), 07 (rollback), 09 (role + từ chối owner DSN), 10,11,12 (đồng hồ DB, 2 cancel đồng thời, thứ tự khóa Listing→Job), 13 (mất kết nối/terminate backend/lock_timeout, không lộ driver text, không rò connection), 14 (mất ack, mất kết nối khi COMMIT, abort 40001/40P01/23514, không retry).
- CI: xem PR (chưa có tại thời điểm viết).
