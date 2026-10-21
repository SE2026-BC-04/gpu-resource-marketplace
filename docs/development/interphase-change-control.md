# Quy trình kiểm soát thay đổi liên Phase — Inter-Phase Change Control

> **Dự án:** GPU Resource Marketplace<br>
> **Quyết định chủ dự án:** **OWNER-APPROVED REQUIREMENT**, ngày 21/10/2026<br>
> **Trạng thái triển khai:** Quy tắc áp dụng từ các thay đổi tiếp theo; tài liệu này **chưa commit/merge** lên repository<br>
> **Phạm vi:** GPU-001, GPU-002, GPU-003, GPU-004, GPU-005 và các Phase sau<br>
> **Liên hệ quy trình hiện hành:** [Team Contribution Rules](team-contribution-rules.md) và [Change Control](change-control.md). Tài liệu này **bổ sung** điều kiện phối hợp liên Phase, không thay thế các mức L0–L3, reviewer hoặc thẩm quyền owner.

## 1. Nguyên tắc bắt buộc

Khi **Markdown kiến trúc, handoff, contract hoặc code** của một Phase thay đổi, người thực hiện phải xác định xem thay đổi đó có làm **sai giả định, interface, schema, test oracle, thời gian thực hiện hoặc kết quả** của Phase khác hay không.

- `NO_IMPACT`: chỉnh chính tả, định dạng hoặc làm rõ diễn đạt **không đổi nghĩa kỹ thuật** và không ảnh hưởng các Phase khác. Ghi lý do ngắn trong commit/PR; **không buộc hai owner xác nhận**.
- `POTENTIAL_IMPACT`: có khả năng ảnh hưởng nhưng chưa đủ bằng chứng. **Cảnh báo sớm** và chuyển `AWAITING_CROSS_PHASE_ACK`; chưa được tự kết luận tương thích.
- `CONFIRMED_IMPACT`: ảnh hưởng schema/contract/behavior/timeline/integration/tests đã xác định. **Bắt buộc** có đối chiếu, phương án xử lý và xác nhận từ hai phía **trước khi merge hoặc dùng thay đổi làm baseline tích hợp**.
- `BLOCKED_INTERPHASE`: người liên quan phản đối, chưa xác nhận hoặc còn lỗi/contract conflict. Dừng merge/tích hợp phần phụ thuộc; không ghi `PASS`/`IMPLEMENTED` giả.

**Hai người phải xác nhận:** (1) **người chịu trách nhiệm Phase phát sinh thay đổi (upstream/source owner)** và (2) **người chịu trách nhiệm từng Phase bị ảnh hưởng (downstream/consumer owner)**. Thay đổi ảnh hưởng ba Phase thì cần ba xác nhận riêng của consumer owner, không chỉ một xác nhận đại diện. Nhóm trưởng nhận cảnh báo, điều phối và xác nhận với vai trò **owner Phase 1/integrator** khi đó là phạm vi của mình; không tự nhận thay xác nhận của thành viên khác. Im lặng không được hiểu là đồng ý. Một người không được tự ký thay cả hai phía.

**Phạm vi áp dụng hai chiều:** thay đổi một Phase sau cũng phải cảnh báo owner của Phase trước nếu thay đổi chạm interface/contract do người đó sở hữu. Quy trình này áp dụng **ngay khi sửa file `.md` có nội dung tác động**, không chờ đến khi viết code.

## 2. Trường hợp nào phải cảnh báo

| Thay đổi thực chất | Ví dụ và phạm vi ảnh hưởng |
|---|---|
| Database schema/seed/migrations/repositories | Cột, type, nullable, FK, UNIQUE, CHECK, index, role seed, transaction/UoW signatures hoặc query semantics đổi → GPU-003/004/005 |
| Authentication/RBAC | JWT profile/expiry, login normalization, password provisioning, principal/role guard, token storage đổi → GPU-004/005; có thể tác động GPU-002 |
| Listings | DTO/route, ownership, ACTIVE/PAUSED, capacity, read filters đổi → GPU-005 và các phép kiểm thử Phase 2 |
| Jobs/queue/reference | Job DTO, `enqueue_seq`, idempotency, `TX-SUBMIT`, protected simulation reference đổi → GPU-002/004 và Phase 2 |
| Foundation/shared infrastructure | `api/app.py`, DB connection permissions, Compose networks, config/env, CI, frontend API client/shared shell đổi → mọi Phase thực sự sử dụng thành phần đó |
| API/ADR/Requirements/Test Design | Thay định nghĩa endpoint, error code, state machine, lock order, test oracle hoặc tiêu chí nghiệm thu → các owner module chịu tác động; có thể cần CR L2/L3 |

**Không phải mọi thay đổi Markdown đều phải phối hợp hai người.** Thay đổi câu chữ thuần túy không tạo ra thay đổi hợp đồng và đã có phân tích `NO_IMPACT` được xử lý như tài liệu thông thường.

## 3. Quy trình 6 bước

1. **Diff và truy vết:** người sửa đối chiếu `old → new` của file Markdown/code, liên kết commit SHA/revision nguồn, và lập danh sách Phase có thể dùng nội dung đó. Không dựa vào bản thiết kế local cũ hơn `main` mà không kiểm tra.
2. **Phân loại tác động:** ghi `NO_IMPACT`, `POTENTIAL_IMPACT` hoặc `CONFIRMED_IMPACT`, phạm vi ảnh hưởng, yêu cầu/ADR/API/DB/test IDs và giải thích tại sao. Nếu chưa chắc, phân loại `POTENTIAL_IMPACT` và cảnh báo trước.
3. **Cảnh báo có nội dung:** thông báo trực tiếp tới **source owner, từng consumer owner và nhóm trưởng** bằng PR mention/comment hoặc kênh nhóm có link truy vết; nêu thay đổi trước/sau, giả định bị ảnh hưởng, việc cần sửa và thời điểm dự kiến dùng baseline mới.
4. **Hai phía xác minh:** source owner xác nhận mô tả thay đổi và tương thích migration/contract; consumer owner đối chiếu code/tests/tài liệu của Phase mình, trả lời **`ACK_COMPATIBLE`** hoặc **`ACK_WITH_ACTIONS`** (nêu việc và owner/date) hoặc **`REJECTED/BLOCKED`** (nêu bất tương thích). Mỗi phản hồi phải có người thật, ngày và link comment/PR/biên bản; không chấp nhận xác nhận miệng không truy vết.
5. **Khắc phục và kiểm thử:** người chịu trách nhiệm cập nhật tài liệu/adapter/tests trong đúng module ownership. Chạy các test tích hợp/regression thực sự áp dụng; nếu chưa chạy, ghi `NOT_RUN` hoặc `BLOCKED`. Không sửa Requirements, ADR, Database Design, API Contract đã duyệt nếu chưa qua change control; thay đổi L2/L3 phải có owner approval và hai reviewer độc lập theo quy định hiện hành.
6. **Đóng gate và cập nhật baseline:** chỉ được merge/tiêu thụ hợp đồng mới khi mọi consumer owner đã xác nhận, hành động bắt buộc đã xử lý hoặc có quyết định chấp thuận phương án chuyển tiếp có thể kiểm chứng, không còn blocking failure và đáp ứng human review. Ghi commit SHA, PR, affected phase revision, test evidence và trạng thái `CLOSED`. Chuyển `BLOCKED_INTERPHASE` về trạng thái bình thường **chỉ sau** khi hết blocker.

## 4. Mẫu bản ghi cảnh báo liên Phase (đính vào PR/Markdown)

```markdown
### Inter-Phase Impact Review — XPH-<task>-<sequence>
- Source phase / owner: ...
- Changed file(s), base SHA → target SHA: ...
- Changed contract/assumption (before → after): ...
- Classification: NO_IMPACT | POTENTIAL_IMPACT | CONFIRMED_IMPACT
- Affected phase(s), owner(s): ...
- Impact: schema/API/permissions/UI/test/migration/CI/timeline...
- Required updates / responsible person / deadline: ...
- Verification: test IDs, command, PASS/FAIL/BLOCKED/NOT_RUN, evidence link...
- Source owner acknowledgement: name, ACK, date, evidence link
- Consumer owner acknowledgement(s): name, ACK_COMPATIBLE |
  ACK_WITH_ACTIONS | REJECTED/BLOCKED, date, evidence link
- Leader coordination: name, date (nếu liên quan)
- Gate status: AWAITING_CROSS_PHASE_ACK | BLOCKED_INTERPHASE | CLOSED
- Linked change-control record (L2/L3, nếu có): ...
```

**Mẫu ngắn `NO_IMPACT`:** `Changed docs: clarification only; no contract/schema/API/test impact; assessed by <owner>; linked diff <url>`. Không cần tạo bản ghi dài khi thật sự không có tác động.

## 5. Bản đồ phối hợp theo ownership

| Phase phát sinh thay đổi | Owner nguồn | Phase thường cần kiểm tra và người xác nhận |
|---|---|---|
| **GPU-001 Foundation** | Nhóm trưởng | GPU-002/Thành viên 2, GPU-003/Thành viên 3, GPU-004/Thành viên 4, GPU-005/Thành viên 5 — **chỉ các consumer thực sự bị ảnh hưởng** |
| **GPU-002 Database** | Thành viên 2 | GPU-003/Thành viên 3, GPU-004/Thành viên 4, GPU-005/Thành viên 5; nhóm trưởng nếu shared DB/Compose/Manager integration bị ảnh hưởng |
| **GPU-003 Identity** | Thành viên 3 | GPU-004/Thành viên 4, GPU-005/Thành viên 5; Thành viên 2 nếu provisioning/DB query contract thay đổi; nhóm trưởng nếu router/config bị ảnh hưởng |
| **GPU-004 Listings** | Thành viên 4 | GPU-005/Thành viên 5; Thành viên 2 hoặc 3 nếu schema/guards thay đổi; nhóm trưởng nếu app integration bị ảnh hưởng |
| **GPU-005 Jobs** | Thành viên 5 | Phase 2 owner(s) khi được giao; Thành viên 2/3/4 nếu schema/identity/listing boundaries bị ảnh hưởng; nhóm trưởng khi Manager/API boundary thay đổi |

Bảng trên là **danh sách rà soát**, không mặc định mọi owner đều phải ký nếu diff không chạm trách nhiệm của họ.

## 6. Gate cho các Phase tiếp theo

**Bắt buộc có một mục `Inter-Phase Impact & Dual Acknowledgement` trong mọi tài liệu phase/handoff mới**, đặc biệt GPU-004 và GPU-005. Trước khi ghi `IMPLEMENTED` hay yêu cầu merge, owner phase phải công bố:

- Baseline upstream đã sử dụng (tên tài liệu, commit SHA, revision migration/contract nếu có).
- Những assumption/interfaces có thể bị ảnh hưởng và Phase downstream sẽ chịu tác động.
- Danh sách cảnh báo liên Phase còn mở hoặc tuyên bố `NO_OPEN_CROSS_PHASE_IMPACT` kèm rà soát diff/PR.
- Các xác nhận hai phía và link evidence cho mọi `CONFIRMED_IMPACT`.
- Kiểm thử contract/integration đã chạy và các mục còn `NOT_RUN/BLOCKED`.

**GPU-004:** phải xác nhận contract DB/listing ownership với Thành viên 2, auth principal/role guard với Thành viên 3, shared API/UI integration với nhóm trưởng; cảnh báo Thành viên 5 khi public Listing API, state hoặc capacity semantics đổi. **GPU-005:** phải xác nhận Job/Reference/transaction contract với Thành viên 2, JWT/Client principal với Thành viên 3, Listing capacity/ownership với Thành viên 4, routing/integration với nhóm trưởng; cảnh báo owner Phase 2 về schema/state/oracle contract khi được phân công.

**Không được báo `CLOSED` hoặc `ACK` cho bất kỳ thay đổi cụ thể nào chỉ vì tài liệu policy này được phê duyệt.** Hai người chỉ xác nhận **diff thật** khi phát sinh; các Phase 1B/1C hiện mới phê duyệt thiết kế, chưa có evidence triển khai. PR #3 của GPU-001 đã merge trước khi bổ sung quy tắc; không áp dụng hồi tố để thay đổi trạng thái lịch sử của PR đó.
