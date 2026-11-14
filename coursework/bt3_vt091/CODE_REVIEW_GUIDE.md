# Giải thích code VT-091 và checklist tự review

Đây là tài liệu giải thích, không phải bằng chứng sinh viên/reviewer đã đọc code.
Chỉ xác nhận review sau khi người review thực sự đọc và hiểu diff.

## drafts.py

1. `Draft` frozen giữ revision và tuple các cặp field/value. `fields()` trả dict
   mới nên sửa dữ liệu đọc ra không sửa store. Chỉ nhận giá trị str, không giữ
   tham chiếu object mutable do caller cung cấp.
2. `type(revision) is not int`: bool không được coi là revision. `isinstance(True,
   int)` là True, nên thay bằng isinstance sẽ làm VT07 bắt được lỗi M2.
3. Nháp chỉ yêu cầu đúng bốn field và chuỗi <=4096 ký tự. Cho phép chuỗi rỗng hoặc
   chưa phải số vì người dùng đang nhập; validation Submit vẫn thuộc sản phẩm.
4. Trong một `asyncio.Lock`, đọc current, so revision rồi ghi. Request cũ bị
   StaleDraft; cùng rev khác nội dung bị RevisionConflict; retry giống hệt trả
   current, không tạo lần ghi mới. Lock này chỉ bảo vệ store một process/loop.
5. `AutoSaver.on_change()` tăng revision đồng bộ trước khi tạo task, copy dict
   ngay nên edit tiếp không làm đổi snapshot. Caller sở hữu task và cần await/
   xử lý lỗi. Harness chưa tích hợp debounce, UI hay tự retry khi đóng trình duyệt.
6. `initial_revision` phải lấy từ bản đã đọc để không reset về 1. Không suy ra
   giải pháp nhiều editor độc lập: cần contract version/concurrency riêng.

## harness_api.py

Route `/harness/...` là adapter test-only, không mount trong API sản phẩm. JSON
malformed/schema/revision sai ->422; stale/conflict ->409; OSError ->503 với thông
báo sạch. GET trả bản gần nhất hoặc404. Owner trong URL là fixture, chưa có authz.

## Characterization sản phẩm thật

`test_vt091_patch_characterization.py` đi qua router, DTO, service và audit thật,
nhưng principal/UoW/storage là doubles của suite Listings có sẵn. Chuẩn bị hai
payload trước, gửi mới rồi cũ, assert cả response, GET và hai lần commit/update.
Việc older thắng là contract hiện tại; test giúp chứng minh PATCH không thể dùng
nguyên trạng như autosave có chống stale. Không mô phỏng SQL row lock.

## Tự kiểm tra trước khi giải thích bài

- Giải thích tại sao “request cuối đến” không đồng nghĩa “edit mới nhất”.
- Giải thích Event tạo đúng thứ tự ở VT04/16 và tại sao sleep không phải oracle.
- Chỉ đúng bốn validation bị thay trong patches M1–M4 và test giết từng mutant.
- Phân biệt 35 harness cases, 2 characterization cases và VT17 performance.
- Phân biệt statement/branch coverage và risk coverage; 4/4 mutant chỉ là mẫu đã chọn.
- Nêu rõ các phần chưa chứng minh: multi-tab/device, crash persistence, DB thật,
  browser E2E và 150 user qua TCP. Không ghi đã human-review/merge khi chưa có.
