# VT-091 — kết quả và hướng dẫn đối chiếu báo cáo

Sinh viên Nguyễn Ngọc Việt, 23001954, SE2026-T23, BC-04.
Baseline: `bee832eaf5463df20f6c6815174322871eb6685a`.
Nhánh: `test/bt3-vt091-autosave`. Bài theo phương án harness được đề cho phép.

## Kết quả đã chạy

- VT01–VT16: 35 case harness pass; RED trước patch được giữ nguyên trong01_red*.
- VT17: 2 profile × 3 lượt ×150 =900 coroutine; p95 cao nhất1.072ms trong bộ nhớ.
- VT18: 2 case qua router/service Listings thật, UoW giả; newer PATCH trước,
  older PATCH đến sau đều200, GET trả older. Đây là contract last-commit-wins,
  không phải defect hoặc chứng minh SQL concurrency.
- Mutation M1–M4: 4/4 mutant được chọn bị phát hiện (stale, bool, conflict, độ dài).
  Đây là tỷ lệ trên mẫu chọn, không phải mutation score mọi lỗi có thể xảy ra.
- coverage.py7.10.6: drafts.py52/52 statements,16/16 branches; harness_api.py28/28
  statements,4/4 branches. Tổng80 statements,20 branch exits, đều được chạy.
- Flaky check ban đầu:10 lượt mới,90 case executions pass. Regression ban đầu:
  312 case Listings pass. Chưa chạy lại toàn bộ repo; không suy ra DB/E2E pass.

## Evidence và hash

02/03/04/05/06/07 là lịch sử thí nghiệm ban đầu. 08_mutation_matrix,09_branch_*
và10_characterization là phần bổ sung sau review. Không trộn số liệu stdlib trace
với coverage.py vì phương pháp đếm khác nhau. Chạy lại bằng --output-dir sẽ giữ
nguyên snapshot. README có lệnh Windows và Linux/macOS.

Hash scaffold trước patch bắt đầu06092793; hash drafts.py sau patch bắt đầu607c3252.
Hai hash phải khác vì nội dung khác; metadata gắn từng hash với đúng giai đoạn.
SNAPSHOT.json lưu checksum chuẩn hóa LF để đối chiếu nội dung Git và PDF.

## Khai báo AI và review

Codex hỗ trợ plan, code, tests, thu thập evidence và văn bản báo cáo. Prompt gốc có
lỗi chính tả được ghi là trích nguyên văn. Review của Codex không phải human
approval; không ghi đã được thành viên nhóm duyệt. CODE_REVIEW_GUIDE giải thích
module, invariant và các giới hạn để sinh viên tự đọc và chuẩn bị vấn đáp.

PDF nộp: BT3_23001954_VT-091.pdf, 8 trang nội dung chính + phụ lục AI/log.
Giữ khai báo AI; không ghi đã kiểm chứng multi-tab, crash persistence, real authz,
PostgreSQL hay150 user thật. Nộp PDF cùng link nhánh riêng, không tự merge.
