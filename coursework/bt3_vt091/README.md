# BT cá nhân 3 — Nguyễn Ngọc Việt — 23001954 — VT-091

Nhóm SE2026-T23; dự án BC-04. Executable **harness** cho lưu nháp biểu mẫu
Listing, dựng theo lựa chọn thay thế được đề cho phép. Không phải tính năng đã
tích hợp trong sản phẩm. Đọc [đặc tả và kế hoạch trước patch](PLAN.md).

Baseline: `bee832eaf5463df20f6c6815174322871eb6685a`.
Nhánh: `test/bt3-vt091-autosave`. Không merge khi nhóm chưa review.

## Chạy lại (từ thư mục gốc repo, Python 3.12)

Nếu chưa có môi trường: `cd backend`, `uv sync --locked --group dev`, rồi về
thư mục gốc. Harness dùng các dependency pytest/FastAPI/httpx có sẵn trong
`backend/uv.lock`; không cần DB, Docker hoặc secrets. Những lệnh bên dưới đã chạy
trên Windows; trên Linux thay `backend/.venv/Scripts/python.exe` bằng
`backend/.venv/bin/python`.

```powershell
# Toàn bộ 35 case của harness
.\backend\.venv\Scripts\python.exe -X utf8 -m pytest coursework/bt3_vt091/tests -q

# Tái lập red trên scaffold tạm; exit 0 nghĩa đã quan sát FAIL mong đợi
.\backend\.venv\Scripts\python.exe -X utf8 coursework/bt3_vt091/verify.py red

# Green và metadata/hash code
.\backend\.venv\Scripts\python.exe -X utf8 coursework/bt3_vt091/verify.py green

# Bỏ validation stale trên nhánh Git tạm; exit 0 nghĩa mutant bị test phát hiện
.\backend\.venv\Scripts\python.exe -X utf8 coursework/bt3_vt091/verify.py mutation

# 2 profile x 3 lượt x 150 task, có raw samples
.\backend\.venv\Scripts\python.exe -X utf8 coursework/bt3_vt091/verify.py load

# 10 lượt mới, đảo thứ tự test; 90 case executions
.\backend\.venv\Scripts\python.exe -X utf8 coursework/bt3_vt091/verify.py repeat

# Line coverage stdlib; branch coverage NOT_RUN
.\backend\.venv\Scripts\python.exe -X utf8 coursework/bt3_vt091/verify.py coverage

# Regression phần Listings hiện có (không yêu cầu PostgreSQL)
.\backend\.venv\Scripts\python.exe -X utf8 -m pytest backend/tests/listings backend/tests/test_api_listings_mount.py -q
```

`verify.py` ghi đè evidence tương ứng bằng kết quả **mới chạy**, không tạo PASS
giả. Nên giữ log bài nộp trước khi chạy lại. Hai mode red/mutation tạo **repository
Git tạm**, nhánh và commit tạm chứa lỗi, chạy oracle, rồi dọn bản sao; không sửa
`drafts.py` trong nhánh nộp. Git commit tạm được ghi trong JSON để giải thích thí
nghiệm; không phải commit đã push lên repo nhóm. Patch chỉ để xem trong evidence.

## Mô hình và giới hạn

- `AutoSaver.on_change()` tạo snapshot ngay và gửi bất đồng bộ, không cần Submit.
- Mỗi `(owner, listing)` có **một luồng revision tăng đơn điệu**; tiếp tục editor
  từ revision đã đọc. Lock bao quanh kiểm tra và ghi. Revision nhỏ bị từ chối,
  revision bằng/nội dung khác conflict, retry giống hệt không tạo thay đổi.
- Revision biểu diễn thứ tự chỉnh sửa trong luồng này, không dùng timestamp hoặc
  thứ tự response. Chưa giải quyết nhiều tab/device độc lập, malicious revision
  hoặc reset session. Không tuyên bố thứ tự thời gian toàn cục giữa các editor.
- Draft giữ raw string, kể cả rỗng/dang dở. Không áp dụng validation Submit cho
  bản nháp; schema đúng 4 trường, kiểu chuỗi, giới hạn 4096 ký tự/trường và
  revision là int dương. Giới hạn này là **giả định harness**, chưa được duyệt cho API.
- Store chỉ trong bộ nhớ. Đọc lại cùng store được kiểm tra; persistence qua process
  crash/restart, database transaction và UI reload thật **NOT_RUN**.
- ASGI `/harness/...` chỉ chạy trong test. Owner trong URL là dữ liệu fixture;
  chưa có authentication/authorization. Không sử dụng route này trong production.
- Load dùng 150 coroutine cùng chờ barrier trước khi chạy. Không phải 150 OS thread,
  không phải HTTP/TCP/browser/PostgreSQL, không suy ra đạt NFR của hệ thống thật.
- Đây là coursework độc lập, không đóng bất kỳ test ID Phase 2 hay benchmark 736 VU.

## Bằng chứng

| Thực nghiệm | File evidence | Cách đọc |
|---|---|---|
| Red thực tế trước patch | [01_red.txt](evidence/01_red.txt), [metadata](evidence/01_red.json) | 1 failed: `DID NOT RAISE StaleDraft`, exit 1 |
| Tái lập scaffold | [01_red_reproduced.json](evidence/01_red_reproduced.json), [patch](evidence/01_red_scaffold.patch) | So hash với scaffold trước patch; không giả đây là lỗi đã có trong app |
| Green | [02_green.json](evidence/02_green.json) | Test output, exit code, source SHA-256, phiên bản môi trường |
| Mutation | [03_mutation.json](evidence/03_mutation.json), [diff](evidence/03_mutation.patch) | Test giết mutant bằng assertion behavior, không phải import error |
| Tải | [04_load.json](evidence/04_load.json) | 900 raw samples; p95 nearest-rank, cả saved và stale_rejected; kiểm tra invariant riêng |
| Flaky/order | [05_repeat.json](evidence/05_repeat.json) | 10 subprocess độc lập, thứ tự chọn test luân phiên |
| Regression | [06_listing_regression.txt](evidence/06_listing_regression.txt) | 312 pass; warning deprecation TestClient và quyền ghi pytest cache được giữ nguyên |
| Coverage | [07_line_coverage.json](evidence/07_line_coverage.json) | Chỉ lines của drafts.py/harness_api.py; không lấy tỷ lệ thay cho quality |

Xem [bảng test/traceability](TEST_MATRIX.md) và [ghi chú nộp bài](SUBMISSION_NOTES.md).
