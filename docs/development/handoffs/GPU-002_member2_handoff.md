# GPU-002 — Handoff cho Thành viên 2

> **Phase:** 1B — Database Schema & Persistence Layer<br>
> **Trạng thái:** `APPROVED DESIGN / IMPLEMENTATION NOT STARTED`<br>
> **Ngày phê duyệt:** 21/10/2026<br>
> **Người thực hiện dự kiến:** Thành viên 2<br>
> **Baseline:** `main@c90f540b385c8d11789f994748e4f5441bcb7e1b`<br>
> **Kiến trúc đã duyệt:** `docs/architecture/phases/phase1b_database_persistence.md` (bản local, chưa commit)

## 0. Mandatory Reading & Working Rules — BẮT BUỘC

**Điều kiện trước khi bắt đầu:** người phụ trách phải đọc các tài liệu dưới đây **trên baseline Git mới nhất**, ghi phiên bản/commit SHA đã đọc, kiểm tra sự khác biệt với baseline ghi ở đầu handoff và xác nhận các dependency thực sự sẵn sàng. Việc chủ dự án duyệt thiết kế **không tự cho phép** bắt đầu code hoặc merge.

**A. Quy tắc làm việc của nhóm (đọc đủ 3 tài liệu):**

1. [Team Contribution Rules](../team-contribution-rules.md) — ownership, branch/commit, PR, independent human reviewer và điều kiện merge.
2. [Change Control](../change-control.md) — cấp độ L0–L3, quyền ra quyết định, thay đổi Requirements/ADR/API/DB contracts.
3. [Inter-Phase Change Control](../interphase-change-control.md) — phân loại tác động, cảnh báo, hai phía xác nhận và `BLOCKED_INTERPHASE`.

**B. Kiến trúc & mẫu xác nhận:**

- [Kiến trúc GPU-002 đã phê duyệt](../../architecture/phases/phase1b_database_persistence.md) — phạm vi, invariants, status, acceptance gates của Phase này.
- [Inter-Phase Review Template](../../architecture/phases/_interphase_review_template.md) — mẫu bắt buộc dùng khi có thay đổi thực chất ảnh hưởng Phase khác.

**C. Thiết kế / dependency phải đối chiếu theo nhiệm vụ:**

- [Database Design: schema 10/18 bảng và transaction/lock order (§§9,11)](../../design/database-design.md)
- [API Contract: Identity, Listings, Jobs, dữ liệu cần persistence](../../design/api-contract.md)
- [Module Design: data write ownership, repository/UoW interfaces](../../design/module-design.md)
- [Test Design: DBP/DBTX và PostgreSQL integration](../../design/test-design.md)
- [ADR-002: PostgreSQL access boundaries](../../architecture/decisions/ADR-002-postgresql-access-boundaries.md)
- [Phase 1C: consumer Authentication](../../architecture/phases/phase1c_authentication_rbac.md)
- [Phase 1D: consumer Listings](../../architecture/phases/phase1d_gpu_listings.md)
- [Phase 1E: consumer Jobs](../../architecture/phases/phase1e_job_submission_queue.md)

**D. Quy tắc thực hiện và phối hợp:**

- Không tự sửa code/tài liệu ngoài module ownership, không tự đổi quyết định đã duyệt; gặp mâu thuẫn giữa hai nguồn chuẩn thì **dừng phần bị ảnh hưởng và báo nhóm trưởng/chủ dự án**, không tự chọn một phiên bản.
- Trước mỗi thay đổi Markdown **hoặc** code, so sánh trước/sau và phân loại `NO_IMPACT | POTENTIAL_IMPACT | CONFIRMED_IMPACT`. `NO_IMPACT` chỉ dành cho thay đổi không đổi nghĩa kỹ thuật và phải có lý do; hai mức còn lại phải cảnh báo source owner, **từng** affected owner và nhóm trưởng.
- Với `POTENTIAL_IMPACT`/`CONFIRMED_IMPACT`, lập record bằng template; nhận ACK của **source owner + từng consumer owner** (cùng evidence link), xử lý các action/test cần thiết. Thiếu ACK hoặc còn xung đột → `BLOCKED_INTERPHASE`, **không được merge hoặc dùng làm baseline tích hợp**.
- **Quy tắc phối hợp riêng:** Không tự thay đổi schema/transaction contract đã duyệt hoặc bổ sung bảng; mọi thay đổi thực chất ảnh hưởng Identity (TV3), Listings (TV4), Jobs (TV5), shared infrastructure (nhóm trưởng) phải được cảnh báo. Đặc biệt chốt interface users/roles/worker, UoW, Listing-lock, Job idempotency và quyền protected reference trước khi chuyển giao cho các phase phụ thuộc.
- Trước PR/merge: chạy các tests áp dụng được, công bố `PASS | FAIL | BLOCKED | NOT_RUN` trung thực, cung cấp Git SHA/DB revision/commands/evidence; tuân thủ human review độc lập theo cấp độ, không self-approve/self-merge.
- **Trong mô tả PR bắt buộc ghi:** `Mandatory Reading ACK` (đã đọc những file nào, tại commit/revision nào), `Inter-Phase Impact` (kể cả `NO_IMPACT` có lý do), liên kết ACK thật nếu cần và `Test Evidence`. Không coi checklist tự đánh dấu là xác nhận thay người phụ trách khác.

## Mục tiêu giao việc

Tạo lớp lưu trữ PostgreSQL 16 thật cho **đúng 10 bảng nghiệp vụ** Phase 1B (không tính bảng quản lý `alembic_version`), ORM SQLAlchemy 2, Alembic, Repository/UoW và integration tests. Không triển khai Auth, Listings, Jobs API hay Simulator.

## Thứ tự thực hiện

| ID | Công việc | Deliverable và điều kiện review |
|---|---|---|
| `GPU-002-A` | Lập schema matrix từ Database Design §9: 10 bảng, cột, PK/FK (kể cả composite FK), CHECK, UNIQUE, indexes, seed/deletion policy | Matrix khớp nguồn duyệt; trình nhóm trưởng review đặc biệt grants, triggers, quyền xóa |
| `GPU-002-B` | Tạo SQLAlchemy mappings, import metadata vào Alembic, baseline revision và seed 3 role codes | PostgreSQL test DB upgrade thành công; đúng 10 bảng nghiệp vụ; seed idempotent; không migration thêm bảng |
| `GPU-002-C` | Xây Session/UoW/repositories với transaction boundary và query filters phục vụ GPU-003/004/005 | Có interface và ví dụ sử dụng, lỗi DB rollback toàn transaction; không nhúng business flow thuộc module khác |
| `GPU-002-D` | Viết test PostgreSQL thật cho schema, FK, constraints, idempotency uniqueness, rollbacks, access boundary, FIFO persistence | Có PASS/FAIL thực tế cho các tiêu chí áp dụng được; ghi `NOT_RUN/BLOCKED` cho nghiệp vụ chưa có |
| `GPU-002-E` | Regression CI/Compose, migration/rollback, bàn giao interfaces, **inter-phase impact ACK**, PR theo governance | Foundation tests không bị phá, chứng cứ test và từng owner liên quan xác nhận trước merge |

## Các file được phép tập trung thay đổi

```text
backend/src/gpu_marketplace/domain/      # ORM mappings / metadata (không để policy thuần phụ thuộc DB)
backend/src/gpu_marketplace/repositories/ # PostgreSQL adapters, queries, UoW
backend/src/gpu_marketplace/common/       # Chỉ thay đổi DB/session plumbing có review
backend/migrations/                       # Alembic revision, env imports, seed lookup
backend/tests/                            # Unit/integration tests và fixtures
docs/architecture/phases/                 # Phase 1B implementation evidence sau nghiệm thu
```

Không tự sửa API Contract, ADR, Requirements, `api/app.py`, `manager/` hay Simulator. Nếu cần đổi path/config dùng chung, đề xuất nhóm trưởng review trước.

## Ranh giới kỹ thuật quan trọng

1. `jobs.enqueue_seq` là khóa FIFO được cấp theo thứ tự chấp nhận **sau khi khóa Listing**, không lấy UUID hoặc client timestamp thay thế. Phase 1B kiểm tra khả năng lưu trữ và primitives; Manager FIFO scheduler thuộc Phase 2.
2. `jobs` + `simulation_references` cần atomic trong `TX-SUBMIT` (GPU-005). Phase 1B cung cấp mappings/transaction primitives; **không tự sinh seed, outcome hay digest giả**.
3. `simulation_references` là protected oracle. Chỉ trusted backend có quyền truy cập theo use case được phê duyệt. Không trả qua public repositories/JSON responses và không đưa credentials cho Simulator.
4. Phải xem xét tách quyền DB của API/Manager: Compose foundation hiện cấp cùng DB URL. Model ownership **không thay thế** SQL grants, function hoặc immutable-data trigger. Chi tiết cơ chế cần duyệt trước khi viết.
5. Không tạo 6 bảng Phase 2 hay 2 bảng Phase 3. Không thêm Redis, broker, service thứ sáu hoặc public signup.

## Kiểm thử bắt buộc

- Fresh PostgreSQL 16 **test database**: `alembic upgrade head` tạo đúng 10 bảng nghiệp vụ; chạy lại an toàn. Kiểm tra `alembic_version` riêng.
- PostgreSQL catalog/ORM parity: column types/defaults/FK/CHECK/UNIQUE/partial indexes, `DBP-01`, `DBP-02`, `DBP-04` và phần liên quan trong `DBP-03`, `DBP-05`.
- Negative tests: sai role/worker/listing binding, vượt capacity, sai digest format, key bytes không đúng 32, duplicate client idempotency key.
- Transaction test: Job + reference fixture cùng UoW; lỗi một INSERT phải rollback cả hai. Bài test này **không chứng minh** oracle algorithm hoặc `TX-SUBMIT` HTTP hoàn thành.
- Không truy cập DB từ Simulator; không lộ password hash, seed/expected output qua repository public.
- Alembic migration rollback/re-upgrade chỉ trên test DB; giữ nguyên CI foundation, Compose smoke. Ghi rõ test chưa thực thi hoặc bị chặn.

## Quy trình review và kết quả

- **Gate 0:** nhóm trưởng xác nhận phân công coding; thiết kế tổng thể Phase 1B đã được duyệt, nhưng implementation chưa bắt đầu.
- **Gate 1:** review migration SQL thực tế, permissions/immutability, guarded Job deletion trước merge.
- **Gate 2:** gửi PR riêng cho GPU-002; ≥1 independent human reviewer nếu L1, ≥2 nếu L2/L3; tác giả không tự approve/merge.
- **Gate 3:** ghi `IMPLEMENTED` cho GPU-002 **chỉ sau** tests bắt buộc PASS và PR merge; cập nhật Phase 1B document với evidence thật.

**Các việc không được coi là DONE ở GPU-002:** API-AUTH, API-LIST, API-JOB; Manager allocation; Signing/Dispute/Retention; `DEC-P1-04` deterministic generator chưa có test vectors; benchmark 736 VU.

## Điều kiện bổ sung: xác thực liên Phase

> Theo [Inter-Phase Change Control](../interphase-change-control.md) (đường dẫn chuẩn trong repository); đây là **yêu cầu chủ dự án 21/10/2026**, không phải code đã triển khai.

- Trước mỗi PR sửa schema/repositories/UoW/Markdown, **Thành viên 2** so sánh diff với DB Design và contract tiêu thụ; ghi `NO_IMPACT`, `POTENTIAL_IMPACT` hoặc `CONFIRMED_IMPACT` có lý do.
- Nếu ảnh hưởng thật, lập cảnh báo before/after + file/SHA + affected test IDs; trao đổi riêng với **Thành viên 3** cho Identity, **Thành viên 4** cho Worker/Listing, **Thành viên 5** cho Jobs/Reference, **nhóm trưởng** cho shared API/DB runtime — **chỉ những người thực sự bị ảnh hưởng**.
- Hai phía ghi xác nhận bằng văn bản có link: `Thành viên 2 ACK` + `consumer owner ACK_COMPATIBLE | ACK_WITH_ACTIONS`; phải xử lý các action bắt buộc trước tích hợp. Không có ACK → `BLOCKED_INTERPHASE`, không merge.
- Nếu chính Phase 1C/1D/1E đề nghị đổi `users`, FK, `jobs`, reference hoặc repository interface, **Thành viên 2 cũng phải xác nhận** như owner upstream.
- Dual ACK **không thay thế** independent human reviewer; trường hợp L2/L3 vẫn cần thay đổi được chủ dự án phê duyệt qua CR và ≥2 human reviewers.

## Pre-PR Checklist — GPU-002 (chưa xác nhận)

> Checklist phải được chính thành viên phụ trách hoàn thành **trước khi yêu cầu merge** và gắn vào PR. Các ô bên dưới mặc định chưa đánh dấu; tài liệu được duyệt không đồng nghĩa đã hoàn thành các bước.

- [ ] Đã đọc `team-contribution-rules.md`, `change-control.md`, `interphase-change-control.md` và ghi `Mandatory Reading ACK` kèm commit SHA/revision.
- [ ] Đã đọc kiến trúc GPU-002, `docs/design/`/ADR liên quan, và kiểm tra baseline/contract của các Phase phụ thuộc.
- [ ] Đã kiểm tra ownership: chỉ sửa các file đúng trách nhiệm hoặc có xác nhận từ owner của shared file.
- [ ] Đã đánh giá diff Markdown/code: `NO_IMPACT` có lý do hoặc `POTENTIAL_IMPACT` / `CONFIRMED_IMPACT` với Impact Report theo template.
- [ ] Nếu có ảnh hưởng liên Phase, đã thông báo source owner, **từng** affected owner và nhóm trưởng; đã nhận đủ ACK có link thật, xử lý `ACK_WITH_ACTIONS` và không còn `BLOCKED_INTERPHASE`.
- [ ] Nếu thay đổi Requirements/ADR/API Contract/Database Design, đã đi đúng Change Control và nhận quyết định của người có thẩm quyền.
- [ ] Đã chạy các test bắt buộc có thể áp dụng; ghi rõ lệnh, fixture, commit SHA, kết quả và bằng chứng; không ghi PASS cho `NOT_RUN` / `BLOCKED`.
- [ ] Đã cập nhật phase doc, handoff / README cần thiết và kiểm tra Markdown links, bảo đảm status triển khai phản ánh code/PR thật.
- [ ] Đã ghi `Mandatory Reading ACK`, `Inter-Phase Impact`, `Test Evidence` trong PR và yêu cầu **independent human reviewer** theo cấp độ; không tự approve/merge.
