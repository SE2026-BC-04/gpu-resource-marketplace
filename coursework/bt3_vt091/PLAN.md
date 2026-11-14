# BT3 — VT-091 — kế hoạch trước patch

- Sinh viên: Nguyễn Ngọc Việt — 23001954, SE2026-T23, BC-04.
- Repository: https://github.com/SE2026-BC-04/gpu-resource-marketplace
- Baseline đã fetch: `bee832eaf5463df20f6c6815174322871eb6685a`.
- Nhánh: `test/bt3-vt091-autosave`. Ngày: 2026-11-14, Asia/Bangkok.
- Chỉ là executable coursework harness; không tích hợp vào API/UI/DB hoặc Phase 2.

## Problem statement

Khi người dùng sửa biểu mẫu Listing, các lần lưu nháp bất đồng bộ có thể đến sai
thứ tự. Cần tự gửi snapshot khi thay đổi và giữ snapshot có revision mới nhất,
không để lần lưu cũ ghi đè. Risk trọng tâm: AI sinh test theo implementation;
expected result phải được ghi từ đặc tả trước khi thêm validation revision.

## Hai phương án do AI đề xuất và review bằng repository

1. **Tích hợp lưu nháp server vào Listing PATCH**: có UI thật, nhưng PATCH đang
   thay đổi Listing đã công bố và không có optimistic version/ETag. Bị loại cho
   lần thực nghiệm này: cần CR/schema/API và review nhóm trước.
2. **Chọn: harness Python bất đồng bộ riêng**, mô phỏng snapshot 4 trường của
   ListingForm, store trong bộ nhớ với lock và revision, API ASGI chỉ trong test.
   Dùng Python 3.12, pytest/FastAPI/httpx đã có; không thêm dependency. Đề cho phép
   executable harness khi repo chưa đủ điều kiện tích hợp.

Evidence và ít nhất hai điểm sửa/bác bỏ plan ban đầu:

| Giả định/phương án cần bác bỏ | Evidence baseline | Điều chỉnh |
|---|---|---|
| Dùng PATCH hiện có làm autosave là an toàn | `docs/design/api-contract.md:440`: last committed value wins, không version/ETag | Tách harness, chưa thay accepted API |
| Dùng validation submit cho mọi bản nháp | `frontend/src/ui/listings/ListingForm.tsx:14,33-40`: submit đòi model và số nguyên dương | Nháp cho phép chuỗi rỗng/dang dở; chỉ kiểm tra schema, kiểu và revision |
| Chỉ cần giữ dữ liệu bằng useState là đã lưu nháp | `ListingForm.tsx:20-25,43`: state cục bộ, lưu qua onSubmit | Cần mô hình store và lần đọc lại riêng; chưa gọi đó là persistence trên đĩa |

## Acceptance criteria — chỉ áp dụng harness

- **AC1**: mỗi on_change tự gửi snapshot riêng, revision tăng theo thứ tự chỉnh sửa
  của **một editor stream**; không cần bấm Submit.
- **AC2**: với cùng owner/listing, revision nhỏ hơn đã lưu bị từ chối; revision bằng
  và nội dung khác bị conflict; retry giống hệt không đổi dữ liệu. Invariant:
  revision đã lưu không giảm và nội dung khớp revision lớn nhất đã được chấp nhận.
- **AC3**: đọc lại từ cùng store trả về bản nháp mới nhất; hai owner/listing không
  lẫn dữ liệu. Đây không phải chứng minh authentication/authorization production.
- **AC4**: revision sai kiểu/không dương và payload sai schema/kiểu bị từ chối;
  lưu lỗi không làm mất bản nháp đã chấp nhận; nháp dang dở vẫn hợp lệ.
- **AC5**: test đảo thứ tự lưu và 150 task đồng thời vẫn bảo vệ AC2; báo p95 với
  ngưỡng 4.0 giây, số mẫu, lỗi và giới hạn môi trường.

NFR1: p95 <= 4.0s cho workload harness đã mô tả, không suy ra API/DB thật.
NFR2: concurrency test dùng Event/barrier, không dựa vào sleep hoặc wall-clock;
test độc lập state và dữ liệu giả, không secrets/DB/network bên ngoài.

## Phạm vi, file và thứ tự dự kiến

1. Viết PLAN này, `tests/test_drafts.py`, `pytest.ini`; dựng scaffold `drafts.py`
   last-arrival-wins để test import/chạy được (không giả là lỗi đã chạy trên app).
2. `verify.py red`: chỉ chạy oracle stale-write, lưu fail trước patch.
3. Patch nhỏ trong `drafts.py`: so revision và ghi trong cùng critical section.
4. `harness_api.py`, integration tests: ASGI test-only 200/409/422/503.
5. `verify.py green|mutation|load|repeat|coverage|regression`: lưu JSON/text evidence.
   Mutation xóa validation stale trong bản sao tạm, không để mutant trong nguồn.
6. `README.md`, test matrix/traceability và AI log; review diff trước commit.

Không sửa production, dependency, migration, API contract, Phase2 docs; không merge.
Các ID VT-* là test cá nhân, không phải acceptance ID đã được nhóm duyệt.

## AI Usage Log (khởi tạo trước patch)

- Công cụ: Codex trong chat này; AI có hỗ trợ đọc repo, chọn thiết kế, sinh code/test.
- Prompt người dùng: “ok vậy tranh thủ test gì test nhanh cho tôi nhé vì bài này
  hết hôm này tôi phải nọp rồi”. Các yêu cầu trước trong chat: đọc đề VT-091,
  xác định việc cần làm; đã thống nhất thử nghiệm nhỏ/harness trước.
- Output được dùng: hai phương án trên, AC1–5, plan và tests. Không có review độc
  lập của con người; người nộp phải tự đọc và giải thích code trước khi nộp.
- Không đáng tin ngay: (1) kiểm tra kết quả cuối mà không điều khiển thứ tự lưu có
  thể không kích hoạt race; (2) p95 in-memory thấp không chứng minh 150 user HTTP.
- Bác bỏ/điều chỉnh: bảng evidence ở trên; kết quả thực thi bổ sung sau, không điền
  PASS trước khi chạy.
