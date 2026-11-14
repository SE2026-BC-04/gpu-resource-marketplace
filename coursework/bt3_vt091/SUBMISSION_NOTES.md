# Ghi chú dùng viết PDF — VT-091

Đây là tài liệu hỗ trợ từ AI, **chưa phải PDF hoàn chỉnh để nộp**. Người nộp cần
đọc code, tự review diff, bổ sung reflection 250–350 từ theo trải nghiệm thật và
chịu trách nhiệm nội dung. Không ghi đã human-review/approve khi chưa thực hiện.

## Thông tin trang đầu

- Nguyễn Ngọc Việt — 23001954 — SE2026-T23 — BC-04 — VT-091.
- Repository: https://github.com/SE2026-BC-04/gpu-resource-marketplace
- Baseline: `bee832eaf5463df20f6c6815174322871eb6685a`.
- Branch: `test/bt3-vt091-autosave`.
- Link: https://github.com/SE2026-BC-04/gpu-resource-marketplace/tree/test/bt3-vt091-autosave/coursework/bt3_vt091
- Cam kết theo đề: “Tôi chịu trách nhiệm về toàn bộ code, test và nội dung bài
  làm; tôi đã khai báo việc sử dụng AI.” Chỉ xác nhận sau khi đã đọc và hiểu bài.

## Những kết quả đã thực thi ngày 2026-11-14

| Nội dung | Kết quả thực tế | Giới hạn |
|---|---|---|
| Test-first RED | 1 failed, `DID NOT RAISE StaleDraft`, trước patch | Scaffold thử nghiệm last-arrival-wins, không phải lỗi đã chứng minh trên app |
| GREEN | 35 passed | 35 case parametrized, 16 nhóm requirement |
| Mutation | Bỏ stale validation; VT03 phát hiện bằng test fail | Một mutant, không suy ra mutation score toàn suite |
| Flaky check | 10/10 process mới pass, tổng 90 case executions | Không chứng minh tuyệt đối không flaky |
| Regression Listings | 312 passed | Không phải real PostgreSQL, browser hay toàn bộ repo |
| Line coverage | drafts.py 54/54; harness_api.py 28/28 | stdlib trace; branch NOT_RUN; không thay thế risk coverage |
| Load | 2 profile × 3 lượt × 150 = 900 task; invariant đúng, zero unexpected errors | Coroutine/in-memory, không real HTTP/DB/user |

Lần đo được lưu trong `evidence/04_load.json` có p95 cao nhất khoảng **1.072 ms**,
nhỏ hơn mục tiêu **4000 ms**, chỉ trong profile harness này. Dùng raw JSON làm
nguồn nếu chạy lại; không lấy số cũ áp vào source hoặc môi trường mới.
Profile 150 draft riêng có 150 successful saves/lượt. Profile chung một draft
có cả stale rejection hợp lệ; p95 tính trên mọi request, có nêu riêng số saved,
stale_rejected và unexpected_errors để tránh giấu lỗi hoặc chọn mẫu có lợi.
Latency tính từ lúc barrier chung mở đến lúc task hoàn tất, có cả chờ scheduler;
percentile nearest-rank `ceil(0.95*n)`. Không suy ra benchmark 736 VU của sản phẩm.

Môi trường, package versions, source SHA-256, stdout và exit code có trong
JSON evidence. Hai warning regression về TestClient deprecation và pytest cache
permission được giữ lại trong log; không thêm dependency để che warning.

## Gợi ý bố cục tối đa 8 trang chính

1. Thông tin, problem statement, AC1–5, invariant và NFR.
2. Hai phương án AI, evidence chọn/bác bỏ; review ít nhất hai giả định trong PLAN.
3–4. Strategy và bảng test từ TEST_MATRIX, risk trọng tâm và test data.
5. RED → diff nhỏ → GREEN; baseline, file, lệnh và link nhánh/commit.
6. Mutation, line/risk coverage và flaky risks.
7. Profile tải, kết quả, error counts và các giới hạn.
8. Reflection 250–350 từ và bước kiểm chứng tiếp có giá trị cao nhất.

Phụ lục: AI Usage Log trong PLAN, raw logs/diff trong evidence; không tính vào
8 trang chính theo đề. File cuối: `BT3_23001954_VT-091.pdf`.

Reflection cần tự nêu: vì sao fail đúng lý do và mutation làm tăng confidence;
AI đã đề xuất sai gì và evidence đã sửa thế nào; chưa chứng minh multi-tab,
persistence/crash, authz và DB thật; test tiếp theo là hai session độc lập trên
storage thật sau khi nhóm duyệt thiết kế. Không viết mình đã thực hiện các test
đang NOT_RUN.

## AI Usage Log bổ sung sau thực thi

Codex sinh PLAN, harness, tests, runner và tài liệu. Input là đề cá nhân, hai bài
giảng được đọc ở lượt trước, CONTRIBUTING/AGENTS và các file thật được dẫn trong
PLAN. Kết quả dùng: AC, snapshot/version guard, deterministic Event races, test
matrix, temp-branch mutation, load và raw evidence. Các số PASS ở đây lấy từ
thực thi, không phải dự đoán AI. Lỗi kỹ thuật đã sửa trong runner: bỏ synthetic
bytecode line 0 khỏi mẫu số line coverage và dùng LF cố định để tái lập hash
scaffold. Người dùng đã cho phép commit/push nhánh bài cá nhân trong chat.

Hai output AI chưa thể tin ngay: (1) test chỉ kiểm tra response/final state mà
không ép thứ tự có thể bỏ sót race; (2) kết quả 100% line coverage/p95 nhỏ có thể
gây hiểu nhầm về độ tin cậy và hiệu năng production. Test dùng barrier, assertion
độc lập theo AC, mutant và công bố rõ giới hạn để giảm các risk này.
