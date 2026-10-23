# GPU-004 — Handoff cho Thành viên 4: GPU Listings Management

> **Phase:** 1D / GPU-004
> **Ngày phê duyệt thiết kế:** 21/10/2026
> **Trạng thái:** `APPROVED DESIGN / IMPLEMENTATION NOT STARTED`
> **Phụ trách:** Thành viên 4 (Listings), nhóm trưởng (shared integration)
> **Baseline thiết kế ban đầu:** `main@c90f540b385c8d11789f994748e4f5441bcb7e1b`
> **Rà soát đồng bộ ngày 23/10/2026:** `main@538802adebeaeb74dcccd0c025f3a7abc81336c0` và handoff tại `ffb17de39d32956087aca187d490bb03c32ee980`; chỉ rà soát tài liệu, không xác nhận dependency đã sẵn sàng hay test ứng dụng đã chạy.
> **Tài liệu:** [Phase 1D — GPU Listings Management](../../architecture/phases/phase1d_gpu_listings.md) — nguồn thiết kế chi tiết đã duyệt; trạng thái code/test được ghi riêng.
> **Nguồn bắt buộc:** API Contract v0.6 §7; Database Design v0.4 §§9,11; Module Design; Test Design; Team Contribution Rules; Inter-Phase Change Control.

## 0. Mandatory Reading & Working Rules — BẮT BUỘC

**Điều kiện trước khi bắt đầu:** người phụ trách phải đọc các tài liệu dưới đây **trên baseline Git mới nhất**, ghi phiên bản/commit SHA đã đọc, kiểm tra sự khác biệt với baseline ghi ở đầu handoff và xác nhận các dependency thực sự sẵn sàng. Việc chủ dự án duyệt thiết kế **không tự cho phép** bắt đầu code hoặc merge.

**A. Quy tắc làm việc của nhóm (đọc đủ 3 tài liệu):**

1. [Team Contribution Rules](../team-contribution-rules.md) — ownership, branch/commit, PR, independent human reviewer và điều kiện merge.
2. [Change Control](../change-control.md) — cấp độ L0–L3, quyền ra quyết định, thay đổi Requirements/ADR/API/DB contracts.
3. [Inter-Phase Change Control](../interphase-change-control.md) — phân loại tác động, cảnh báo, hai phía xác nhận và `BLOCKED_INTERPHASE`.

**B. Kiến trúc & mẫu xác nhận:**

- [Kiến trúc GPU-004 đã phê duyệt](../../architecture/phases/phase1d_gpu_listings.md) — phạm vi, invariants, status, acceptance gates của Phase này.
- [Inter-Phase Review Template](../../architecture/phases/_interphase_review_template.md) — mẫu bắt buộc dùng khi có thay đổi thực chất ảnh hưởng Phase khác.

**C. Thiết kế / dependency phải đối chiếu theo nhiệm vụ:**

- [API Contract §7: 6 Listing endpoints, DTO/error/pagination](../../design/api-contract.md)
- [Database Design §§9,11: gpu_listings, TX-PAUSE-EDIT, Listing locks](../../design/database-design.md)
- [Module Design: Registry and write ownership](../../design/module-design.md)
- [Test Design: API-LIST-01..18, DBTX](../../design/test-design.md)
- [Phase 1B: DB/Repository prerequisites](../../architecture/phases/phase1b_database_persistence.md)
- [Phase 1C: Auth/RBAC prerequisites](../../architecture/phases/phase1c_authentication_rbac.md)
- [Phase 1E: Jobs consumer of Listing status/capacity](../../architecture/phases/phase1e_job_submission_queue.md)

**D. Quy tắc thực hiện và phối hợp:**

- Không tự sửa code/tài liệu ngoài module ownership, không tự đổi quyết định đã duyệt; gặp mâu thuẫn giữa hai nguồn chuẩn thì **dừng phần bị ảnh hưởng và báo nhóm trưởng/chủ dự án**, không tự chọn một phiên bản.
- Trước mỗi thay đổi Markdown **hoặc** code, so sánh trước/sau và phân loại `NO_IMPACT | POTENTIAL_IMPACT | CONFIRMED_IMPACT`. `NO_IMPACT` chỉ dành cho thay đổi không đổi nghĩa kỹ thuật và phải có lý do; hai mức còn lại phải cảnh báo source owner, **từng** affected owner và nhóm trưởng.
- Với `POTENTIAL_IMPACT`/`CONFIRMED_IMPACT`, lập record bằng template; nhận ACK của **source owner + từng consumer owner** (cùng evidence link), xử lý các action/test cần thiết. Thiếu ACK hoặc còn xung đột → `BLOCKED_INTERPHASE`, **không được merge hoặc dùng làm baseline tích hợp**.
- **Quy tắc phối hợp riêng:** Xác nhận ảnh hưởng với TV2 (DB/UoW), TV3 (role/authorization), nhóm trưởng (router/UI), đặc biệt với TV5 khi sửa ACTIVE/PAUSED, capacity admission, Listing locks/DTO. Các race tests cần Manager/Jobs chưa triển khai phải giữ `BLOCKED/NOT_RUN`, không ghi PASS nhờ mock.
- Trước PR/merge: chạy các tests áp dụng được, công bố `PASS | FAIL | BLOCKED | NOT_RUN` trung thực, cung cấp Git SHA/DB revision/commands/evidence; tuân thủ human review độc lập theo cấp độ, không self-approve/self-merge.
- **Trong mô tả PR bắt buộc ghi:** `Mandatory Reading ACK` (đã đọc những file nào, tại commit/revision nào), `Inter-Phase Impact` (kể cả `NO_IMPACT` có lý do), liên kết ACK thật nếu cần và `Test Evidence`. Không coi checklist tự đánh dấu là xác nhận thay người phụ trách khác.

## 1. Mục tiêu và ranh giới

Triển khai 6 Listings endpoints, server-side Worker ownership, Listing metadata/status/capacity guards và React Listings UI tối thiểu dùng PostgreSQL + Auth thật. Kế thừa GPU-002 Account/Worker/Listing/Job repositories và GPU-003 `AuthenticatedPrincipal` / JWT guard.

**Không triển khai:** public Worker signup, GPU/Job allocation, Scheduler, Job Submit/Cancel, Simulator signing, Disputes, bảng mới, service mới, billing và real GPU.

## 2. Nhiệm vụ

| ID | Nội dung / owner | Deliverable và dependency |
|---|---|---|
| `GPU-004-A` | TV4 đối chiếu DB/Auth/API §7, xác định interface, tạo impact matrix | Có baseline upstream và rà soát tác động với TV2/TV3/TV5/leader trước thay đổi thật |
| `GPU-004-B` | TV4 triển khai 6 Listing endpoints + validated DTO | GET catalogue/detail; POST create; PATCH update; POST pause/resume; pagination, errors, owner guard |
| `GPU-004-C` | TV4 triển khai `TX-PAUSE-EDIT` | Listing lock đầu tiên; hardware/capacity guard, no partial write, idempotent pause/resume |
| `GPU-004-D` | TV4 triển khai React Listings UI | Client catalogue; Worker create/edit/mine/pause/resume; Admin all read-only; Auth reuse |
| `GPU-004-E` | TV4 kiểm thử PostgreSQL/HTTP/UI | `API-LIST-01..18` phần khả thi, source-aware test oracles, test reports thật |
| `GPU-004-F` | TV4 bàn giao + nhóm trưởng tích hợp | README/phase evidence, cross-phase ACK nếu có impact, PR có human review độc lập |

**UI tối thiểu** theo Phase 1D §2.5: danh sách/chi tiết Listing, form tạo/sửa, pause/resume, phân trang và trạng thái loading/rỗng/lỗi theo role. Khi đang gửi thao tác, khóa nút tương ứng để tránh bấm lặp. Không tự động gửi lại `POST` tạo Listing khi chưa biết kết quả: API Contract §7.6 chưa có creation idempotency, nên cùng body gửi hai lần có thể tạo hai Listing.

## 3. Hợp đồng API và bất biến

| Method | Path | Quyền / success |
|---|---|---|
| `GET` | `/api/v1/gpu-listings` | CLIENT/WORKER/ADMIN; 200; marketplace ACTIVE, mine Worker, all Admin |
| `GET` | `/api/v1/gpu-listings/{listing_id}` | CLIENT/WORKER/ADMIN; 200; PAUSED vẫn xem detail được |
| `POST` | `/api/v1/gpu-listings` | WORKER; 201; `worker_id` lấy từ principal→workers DB, allocated=0 |
| `PATCH` | `/api/v1/gpu-listings/{listing_id}` | Owner WORKER; 200; metadata allowlist |
| `POST` | `/api/v1/gpu-listings/{listing_id}/pause` | Owner WORKER; 200; ACTIVE→PAUSED/no-op |
| `POST` | `/api/v1/gpu-listings/{listing_id}/resume` | Owner WORKER; 200; PAUSED→ACTIVE/no-op |

- Response DTO giữ `worker.reputation`, `gpu_model`, `vram_gb`, `total_gpu_count`, `allocated_gpu_count`, `available_gpu_count`, `status`, `accepting_jobs`, giá mock `numeric(12,2)` biểu diễn string `"12.50"` hoặc null, timestamps UTC microsecond.
- `available_gpu_count` là snapshot, **không phải** việc giữ chỗ hoặc guarantee Job scheduling.
- API tạo Listing với `allocated_gpu_count=0`; sau khởi tạo, **Manager là writer duy nhất** cập nhật counter khi cấp phát/giải phóng GPU. Listing API chỉ sửa metadata/status và luôn bảo toàn `0 <= allocated_gpu_count <= total_gpu_count` theo API Contract §7.1 và Database Design `DB-INV-01`.
- `status` chỉ `ACTIVE|PAUSED`; `accepting_jobs` chỉ dựa vào status. Pause không cancel QUEUED và không dừng RUNNING.
- Create nhận `gpu_model`, `vram_gb`, `total_gpu_count`, optional `mock_price_per_hour`; PATCH cho phép đúng 4 field đó. Client không bao giờ ghi `worker_id`, `allocated_gpu_count`, `status` qua PATCH hay timestamps.
- `TX-PAUSE-EDIT`: khóa `gpu_listings` **trước** Job. Đổi model/VRAM khi có QUEUED/RUNNING → 409; giảm total dưới allocated hoặc dưới yêu cầu lớn nhất QUEUED → 409; metadata/no-op xử lý theo API Contract.
- Owner mutation W2→W1 Listing phải 404 (không leak ownership); non-WORKER mutations 403. Kết quả 400/401/403/404/409/422 theo contract, không lộ secret.
- Phân trang bằng keyset `(created_at DESC,id DESC)`, `limit` 1..100; cursor chống giả mạo và ràng buộc scope, filter và actor thích hợp.

## 4. Ranh giới ownership

```text
backend/src/gpu_marketplace/listings/   — TV4
backend/src/gpu_marketplace/repositories/ — TV2; TV4 chỉ đề xuất phần giao diện còn thiếu
backend/src/gpu_marketplace/identity/    — TV3; không sửa tùy tiện JWT/role guard
backend/src/gpu_marketplace/api/app.py   — nhóm trưởng phối hợp tích hợp
frontend/src/api/, frontend/src/ui/       — TV4 + TV3/leader phối hợp shared client/shell
backend/tests/, frontend/src/**/*.test.* — tests do TV4 chịu trách nhiệm trong slice
```

## 5. Kiểm thử / nghiệm thu

`P1D-AC-01..09` theo tài liệu chính. Bắt buộc chứng minh bằng PostgreSQL + API + UI thật: scopes, authenticated read, owner isolation, validation, capacity + hardware guard, pause/resume và regression của Foundation/Auth/DB.

Phân tách dependency của race tests theo API Contract §7.10:

- `API-LIST-13` nhánh pause-versus-submit và `API-LIST-15` nhánh capacity PATCH-versus-submit chờ GPU-005 (`TX-SUBMIT`).
- `API-LIST-13` nhánh pause-versus-allocation, `API-LIST-14` resume/FIFO và `API-LIST-15` nhánh PATCH-versus-allocation chờ Phase 2 Manager (`TX-ALLOCATE`).
- Ghi kết quả từng nhánh thực sự đã chạy; phần chưa sẵn sàng giữ `BLOCKED`/`NOT_RUN`. Không ghi toàn bộ test `PASS` khi mới chạy một nhánh hoặc dùng mock thay luồng submit/allocation thật.

Evidence trong PR: commit SHA, DB revision, fixture IDs, HTTP requests/responses đã redacted, command, actual PASS/FAIL và CI link; độc lập với PASS của GPU-001.

## 6. Inter-Phase Impact & Dual Acknowledgement — BẮT BUỘC

| Nguồn ↔ Consumer | Khi nào phải cảnh báo và xác nhận |
|---|---|
| TV2 ↔ TV4 | DB schema, Listing/Job repositories, UoW, transaction/permission contract ảnh hưởng GPU-004 |
| TV3 ↔ TV4 | JWT principal/role guards, browser auth client, identity mapping ảnh hưởng GPU-004 |
| Nhóm trưởng ↔ TV4 | Shared API router, CORS, app shell, Compose, CI changes |
| TV4 ↔ TV5 | Listing DTO/state, capacity/admission, ownership hoặc Listing row-lock semantics ảnh hưởng `TX-SUBMIT` |
| TV4 ↔ Phase 2 owner (khi được giao) | Manager future allocation hoặc PAUSED/FIFO integration bị thay đổi |

Với **thay đổi thật**, ghi old→new SHA/contract, ảnh hưởng thực tế, `NO_IMPACT|POTENTIAL_IMPACT|CONFIRMED_IMPACT`, người nhận cảnh báo, source owner ACK và mỗi affected owner ACK (`ACK_COMPATIBLE|ACK_WITH_ACTIONS|REJECTED`) có link. Thiếu một ACK hoặc còn conflict → `BLOCKED_INTERPHASE`, không merge. Thay đổi spelling/format không đổi nghĩa kỹ thuật có thể là `NO_IMPACT`, không yêu cầu dual ACK.

**Hai bên xác nhận không thay thế PR review độc lập**: L0/L1 ≥1 người, L2/L3 ≥2 người; không tự approve/merge, không tự sửa Requirements/ADR/API Contract.

## 7. Điều kiện chốt

- Đã duyệt **thiết kế**, chưa có code GPU-004 trên `main` tại thời điểm đối chiếu.
- Trước khi triển khai cần explicit assignment/authorization, dependency GPU-002/003 có evidence thật, và technical review shared changes.
- `IMPLEMENTED` chỉ được ghi khi tất cả test áp dụng được đã chạy đúng phạm vi, PR review/merge hoàn tất và cross-phase gate không còn blocker.

**Tình trạng khi giao file:** `APPROVED DESIGN / NOT IMPLEMENTED`. Chưa có ACK thực tế đối với diff code/contract vì chưa phát sinh.

## Pre-PR Checklist — GPU-004 (chưa xác nhận)

> Checklist phải được chính thành viên phụ trách hoàn thành **trước khi yêu cầu merge** và gắn vào PR. Các ô bên dưới mặc định chưa đánh dấu; tài liệu được duyệt không đồng nghĩa đã hoàn thành các bước.

- [ ] Đã đọc `team-contribution-rules.md`, `change-control.md`, `interphase-change-control.md` và ghi `Mandatory Reading ACK` kèm commit SHA/revision.
- [ ] Đã đọc kiến trúc GPU-004, `docs/design/`/ADR liên quan, và kiểm tra baseline/contract của các Phase phụ thuộc.
- [ ] Đã kiểm tra ownership: chỉ sửa các file đúng trách nhiệm hoặc có xác nhận từ owner của shared file.
- [ ] Đã đánh giá diff Markdown/code: `NO_IMPACT` có lý do hoặc `POTENTIAL_IMPACT` / `CONFIRMED_IMPACT` với Impact Report theo template.
- [ ] Nếu có ảnh hưởng liên Phase, đã thông báo source owner, **từng** affected owner và nhóm trưởng; đã nhận đủ ACK có link thật, xử lý `ACK_WITH_ACTIONS` và không còn `BLOCKED_INTERPHASE`.
- [ ] Nếu thay đổi Requirements/ADR/API Contract/Database Design, đã đi đúng Change Control và nhận quyết định của người có thẩm quyền.
- [ ] Đã chạy các test bắt buộc có thể áp dụng; ghi rõ lệnh, fixture, commit SHA, kết quả và bằng chứng; không ghi PASS cho `NOT_RUN` / `BLOCKED`.
- [ ] Đã cập nhật phase doc, handoff / README cần thiết và kiểm tra Markdown links, bảo đảm status triển khai phản ánh code/PR thật.
- [ ] Đã ghi `Mandatory Reading ACK`, `Inter-Phase Impact`, `Test Evidence` trong PR và yêu cầu **independent human reviewer** theo cấp độ; không tự approve/merge.
