# VT-090 Reflection — Draft for Student Confirmation

> Đây là bản nháp do Codex tổng hợp từ log và diff thực tế. Vương Sỹ Thắng cần đọc, xác nhận cách diễn đạt và bổ sung trải nghiệm cá nhân trước khi nộp; không xem đây là lời chứng cá nhân đã được xác nhận.

Review cho thấy test cần tái hiện lỗi trước khi sửa. Hai test mới ban đầu đỏ: sau Cancel trả `409` và Job được đọc là `RUNNING`, không có GET tiếp theo; request polling cũ cũng không bị abort. Sau khi sửa, cả hai xanh. Component hủy timer và GET cũ trước reconciliation, rồi bắt đầu polling lại cho Job đang chọn. Response cũ không ghi đè dữ liệu mới.

Fake timer và promise điều khiển kiểm tra retry, timeout, terminal state, đổi Job, đổi identity và unmount. Pairwise matrix chỉ giữ transition hợp lệ theo lifecycle hiện có; `TIMEOUT`/503 là lỗi GET, không phải trạng thái Job. Generator tự tính feasible pairs, ghi lý do loại case và mỗi dòng được sinh có test thực thi. 36 test là covering array chứ không chạy hết mọi cấu hình. API-client mock không chứng minh PostgreSQL idempotency; database guard cũng chưa chạy vì chưa xác nhận được disposable cluster.

Mutation đổi `>` thành `>=` bị test biên phát hiện; khôi phục toán tử thì PASS. Bảy test race/timer lặp năm lượt đạt 35/35. Fixture hủy từ `QUEUED` giữ `started_at=null`, có `terminal_at` và không có failure reason. Coverage dòng/nhánh vẫn `NOT_RUN` do thiếu provider.

Harness 60 client nhận 60 DTO tổng hợp hợp lệ, không lỗi HTTP, transport hay schema; max in-flight là 60 và p95 nearest-rank 215.261 ms. Đây là `SIMULATED_ONLY`, không chạy FastAPI, PostgreSQL, auth thật hay GPU. Manager trên baseline chưa thực thi Job nên trạng thái thật chưa được chứng minh. Bước tiếp theo là test polling trên API cùng database disposable an toàn và chờ human review. Bản này vẫn là nháp: tôi cần xác nhận trải nghiệm cá nhân trước khi nộp. AI hỗ trợ test và tổng hợp log; tôi chịu trách nhiệm về oracle và kết luận.
