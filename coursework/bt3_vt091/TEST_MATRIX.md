# VT-091 — test strategy và traceability

Oracle được ghi trong PLAN.md trước validation revision. Dữ liệu giả lấy hình
dạng 4 trường từ ListingForm, không copy test/data của thành viên khác. Các từ
`OLD`, `NEW`, `FIRST` làm sai lệch nội dung dễ thấy; revision 1/2/3 có cả sáu
hoán vị. Kỳ vọng lấy từ AC2: revision lớn nhất được chấp nhận thắng, không lấy từ
thứ tự kết quả implementation. Test vừa kiểm tra rejection vừa kiểm tra dữ liệu
đã lưu, gồm cả luồng trả lỗi và 6 thứ tự hợp lệ.

Unit bảo vệ invariant và validation; integration/ASGI kiểm tra ánh xạ kết quả
HTTP vào cùng store. Browser E2E **NOT_RUN**, vì chưa tích hợp UI và không muốn
gọi test mô hình là E2E. Không cần crypto/scheduler/Simulator/DB migration cho
slice test-only này. Regression Listings chỉ dùng suite đã có, không thay oracle.

File `tests/test_drafts.py`: VT01–12. File `tests/test_api.py`: VT13–16.
Tên test bắt đầu `test_vtNN_`; nhiều giá trị param tạo tổng cộng **35 test cases**.

| ID | Risk / AC | Level | Precondition / input | Expected result từ requirement | Priority |
|---|---|---|---|---|---|
| VT01 | Snapshot alias / AC1 | Unit | on_change rồi mutate dict đầu vào | Tự lưu snapshot trước mutate | P1 |
| VT02 | Ép validation submit / AC3,4 | Unit | 4 chuỗi rỗng; sửa dict đọc ra | Đọc lại rỗng, state store không đổi | P1 |
| VT03 | Stale overwrite / AC2 | Unit | lưu 2 NEW, sau đó 1 OLD | StaleDraft, store còn 2 NEW | P0 |
| VT04 | Request đảo thứ tự / AC1,2 | Integration | request 1 chờ Event; request 2 hoàn tất trước | 1 bị từ chối, NEW còn nguyên | P0 |
| VT05 | Oracle bám impl / AC2 | Unit, 6 params | Tất cả hoán vị revision 1/2/3 | Sau mỗi bước giữ max đã nhận, cuối 3 | P0 |
| VT06 | Retry ghi khác nội dung / AC2 | Unit | cùng rev/cùng data, rồi cùng rev/khác data | Idempotent; conflict giữ data cũ | P1 |
| VT07 | Revision sai / AC4 | Unit, 6 negative | 0, -1, bool, string, float, null | InvalidDraft, zero row | P1 |
| VT08 | Schema sai / AC4 | Unit, 5 negative | thiếu/thừa key, số, quá dài, null | Từ chối, giữ bản đã lưu | P1 |
| VT09 | Lẫn draft / AC3 | Unit | 2 owner + 2 listing | Mỗi key trả riêng; key mới None | P1 |
| VT10 | Lỗi lưu / AC4 | Integration failure path | transport OSError giữa 2 lần save | Lỗi hiện ra, bản trước an toàn; edit sau lưu được | P1 |
| VT11 | Reset revision / AC1,2 | Unit | đã lưu rev10, editor bắt đầu từ10 | Edit mới rev11 | P1 |
| VT12 | Editor state sai / AC4 | Unit, 2 negative | initial revision -1 hoặc bool | InvalidDraft | P2 |
| VT13 | API conflict/đọc / AC2,3 | ASGI | 2 NEW rồi 1 OLD, same rev khác, retry | 200/409/409/200; GET đúng NEW | P1 |
| VT14 | API input / AC4 | ASGI, 5 negative | malformed JSON, array, missing/extra, bool | 422, GET404, zero write | P1 |
| VT15 | API unavailable / AC4 | ASGI failure path | store OSError với nội dung nội bộ | 503 sanitized; GET giữ bản trước | P1 |
| VT16 | API concurrency / AC2 | ASGI | 2 PUT cùng tồn tại, barrier giữ request1 | PUT2=200, PUT1=409, GET=2 NEW | P0 |
| VT17 | Load/race / AC5 | Harness performance | 150 unique và 150 cùng key; 3 lượt/profile | 150 complete/run; không lỗi bất ngờ; invariant; p95<=4s | P1 |

Traceability bổ sung: AC1 → VT01/04/11; AC2 → VT03/04/05/06/11/13/16;
AC3 → VT02/09/13; AC4 → VT02/07/08/10/12/14/15; AC5 → VT17 + `load.py`.
Các test/harness trên cùng nhánh `test/bt3-vt091-autosave`; source hash, commit
baseline và output trong evidence; dùng link nhánh cùng commit sau khi push.

## Đánh giá test

Mutation bắt buộc: xóa hai dòng `if revision < current.revision: raise StaleDraft`.
VT03 phải fail `DID NOT RAISE StaleDraft`. VT03 có cả kiểm tra final data: khi
implementation chỉ im lặng bỏ OLD thay vì reject, test vẫn bắt contract rejection.
Đây là một mutant, **không phải mutation score cho mọi loại lỗi**.

Flaky risks đã xử lý: (1) time/concurrency: Event ép request cũ hoàn tất sau mới,
không dùng sleep để đoán scheduler; timeout 5s chỉ chống treo, không phải oracle;
(2) order/shared state: store mới mỗi scenario, 10 process mới và selection đảo
thứ tự; (3) random/network: permutation đầy đủ, load seed cố định, ASGI in-process,
không external network. 10 lượt pass không chứng minh không bao giờ flaky.

Line coverage chỉ cho execution, không đủ chứng minh invariant. Branch coverage
NOT_RUN do stdlib trace không đo branch, môi trường chưa có coverage plugin.
Risk coverage còn hở: multi-tab/device, crash persistence, thực authz, real HTTP,
PostgreSQL, UI debounce/reload. Các phần này không được tính PASS.
