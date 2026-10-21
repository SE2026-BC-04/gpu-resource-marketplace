# Mẫu bắt buộc — Inter-Phase Impact & Dual Acknowledgement

> **Status:** `TEMPLATE ONLY`; Phase 1D and Phase 1E are now APPROVED DESIGN (2026-10-21), but this generic template is not evidence of impact sign-off for any particular diff.
> **Nguồn yêu cầu:** [Inter-Phase Change Control](../../development/interphase-change-control.md), chủ dự án chấp thuận 21/10/2026.

**Chèn mục sau vào từng file phase và handoff mới** (không xóa hoặc làm yếu các điều kiện review khác):

```markdown
## Inter-Phase Impact & Dual Acknowledgement

- Baseline nguồn: Phase/tài liệu/commit SHA/migration revision/API Contract revision ...
- Phụ thuộc vào Phase trước: interface/DTO/schema/ownership/role/transactions ...
- Các Phase tiêu thụ kết quả: Phase/owner/concrete dependency ...
- Diff tác động (old -> new): ...
- Mức độ: NO_IMPACT | POTENTIAL_IMPACT | CONFIRMED_IMPACT
- Cảnh báo: link PR/issue/comment và danh sách người nhận ...
- Source owner ACK: người/date/link ...
- Consumer owner ACK(s): người/date/ACK_COMPATIBLE hoặc
  ACK_WITH_ACTIONS hoặc REJECTED và link ...
- Remediation/testing: owner, test IDs, PASS/FAIL/BLOCKED/NOT_RUN ...
- Gate: CLOSED | AWAITING_CROSS_PHASE_ACK | BLOCKED_INTERPHASE
```

**Điều kiện trước khi dùng:** nếu chưa có diff thật, hãy ghi `NO_CHANGE_ASSESSED` hoặc `NOT_APPLICABLE` theo đúng tình hình; **không tự điền `ACK` giả** chỉ vì owner đã phê duyệt protocol.

## Checklist riêng cho GPU-004 — Listings (Thành viên 4)

- [ ] Đã nhận schema và Listing repository ở **revision thực** của GPU-002; **Thành viên 2 ↔ 4** xác nhận nếu có khác biệt/changing interface.
- [ ] Đã nhận `AuthenticatedPrincipal`, `require_role(WORKER)`, Auth API client ở revision thực GPU-003; **Thành viên 3 ↔ 4** xác nhận khi có tác động.
- [ ] Thay đổi shared API/router, frontend shell do nhóm trưởng quản lý đã được **nhóm trưởng ↔ Thành viên 4** xác nhận nếu ảnh hưởng.
- [ ] Nếu thay public Listing DTO/state/ownership/capacity semantics ảnh hưởng Job submission, **Thành viên 4 ↔ 5** xác nhận trước merge hoặc trước khi TV5 dùng contract mới.
- [ ] Các diff không tác động thật đã ghi `NO_IMPACT` và lý do; các diff tác động có link 2 phía xác nhận, test/regression và trạng thái đóng gate.

## Checklist riêng cho GPU-005 — Jobs (Thành viên 5)

- [ ] Đã xác định schema `jobs`, `simulation_references`, `enqueue_seq`, UoW/migration thực từ GPU-002; **Thành viên 2 ↔ 5** xác nhận nếu thay đổi ảnh hưởng.
- [ ] Đã xác định Auth Client principal/JWT/role guard từ GPU-003; **Thành viên 3 ↔ 5** xác nhận nếu khác biệt.
- [ ] Đã xác định Listing ACTIVE/PAUSED, ownership, capacity và client DTO từ GPU-004; **Thành viên 4 ↔ 5** xác nhận khi bị ảnh hưởng.
- [ ] Đã xác nhận shared route/config với nhóm trưởng khi sửa `api/app.py`, DB grants hoặc UI shell.
- [ ] Nếu `TX-SUBMIT`, protected oracle, trạng thái Job/queue ảnh hưởng Phase 2: cảnh báo owner Phase 2 **khi được phân công**; không tự phê duyệt `DEC-P1-04` seed/digest spec chưa có.
- [ ] Có test evidence và status rõ ràng; thiếu 2 phía ACK cho impact thật thì gate `BLOCKED_INTERPHASE`.

**Gate xuyên suốt:** 2 bên thực sự cùng review/ack + quy trình PR human independent review hiện hành. Không tự commit/push/merge ngoài phạm vi được giao.
