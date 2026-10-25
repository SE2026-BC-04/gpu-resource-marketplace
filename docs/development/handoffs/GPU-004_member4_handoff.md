# GPU-004 — Handoff cho Thành viên 4: GPU Listings Management

> **Phase:** 1D / GPU-004
> **Ngày phê duyệt thiết kế:** 21/10/2026
> **Trạng thái:** `APPROVED DESIGN / IN_PROGRESS / INTEGRATION_BLOCKED` — core/router/UI và helper nối Auth thật có trên branch; chưa nghiệm thu PostgreSQL/shared app/E2E
> **Phụ trách:** Thành viên 4 (Listings), nhóm trưởng (shared integration)
> **Baseline thiết kế ban đầu:** `main@c90f540b385c8d11789f994748e4f5441bcb7e1b`
> **Rà soát đồng bộ ngày 23/10/2026:** `main@538802adebeaeb74dcccd0c025f3a7abc81336c0` và handoff tại `ffb17de39d32956087aca187d490bb03c32ee980`; chỉ rà soát tài liệu, không xác nhận dependency đã sẵn sàng hay test ứng dụng đã chạy.
> **Đối chiếu upstream ngày 24/10/2026:** `main@21071549937888c997b250625607a16a97a20419`; Phase 1D §2.1/§3.2 đã ghi điều kiện nhận DB/Auth và dùng chung fixture. Schema matrix GPU-002-A revision 3 vẫn `PROPOSED`, D1–D12 và `XPH-GPU-002-01` chưa đóng; không coi bản cập nhật này là ACK hoặc dependency đã triển khai.
> **Baseline coding hiện tại:** `main@7fa6afc23542f508c9bc8f32b38f43ffbc35e909` (25/10/2026): code dependency từ `6434ee3` (#27 D1/#26 session UI); merge #19 mới hơn chỉ thêm docs GPU-005. Listing UoW/D7, account adapter #25 và shared wiring còn chờ; evidence ở Phase 1D §3.7. Không duyệt thay quyết định còn mở.
> **Tài liệu:** [Phase 1D — GPU Listings Management](../../architecture/phases/phase1d_gpu_listings.md) — nguồn thiết kế chi tiết đã duyệt; trạng thái code/test được ghi riêng.
> **Nguồn bắt buộc:** API Contract v0.9 §7; Database Design v0.4 §§9,11; Module Design; Test Design; Team Contribution Rules; Inter-Phase Change Control.

## 0. Mandatory Reading & Working Rules — BẮT BUỘC

**Điều kiện trước khi bắt đầu:** người phụ trách phải đọc các tài liệu dưới đây **trên baseline Git mới nhất**, ghi phiên bản/commit SHA đã đọc, kiểm tra sự khác biệt với baseline ghi ở đầu handoff và xác nhận các dependency thực sự sẵn sàng. Việc chủ dự án duyệt thiết kế **không tự cho phép** bắt đầu code hoặc merge.

**A. Quy tắc làm việc của nhóm (đọc đủ 3 tài liệu):**

1. [Team Contribution Rules](../team-contribution-rules.md) — ownership, branch/commit, PR, independent human reviewer và điều kiện merge.
2. [Change Control](../change-control.md) — cấp độ L0–L3, quyền ra quyết định, thay đổi Requirements/ADR/API/DB contracts.
3. [Inter-Phase Change Control](../interphase-change-control.md) — phân loại tác động, cảnh báo, hai phía xác nhận và `BLOCKED_INTERPHASE`.

**B. Kiến trúc & mẫu xác nhận:**

- [Kiến trúc GPU-004 đã phê duyệt](../../architecture/phases/phase1d_gpu_listings.md) — phạm vi, invariants, status, acceptance gates của Phase này.
- [Implementation README](../../../backend/src/gpu_marketplace/listings/README.md) — code slice, consumption ports, cách nối dependency thật và giới hạn của test doubles; cần TV2/TV3/nhóm trưởng review trước tích hợp.
- [Inter-Phase Review Template](../../architecture/phases/_interphase_review_template.md) — mẫu bắt buộc dùng khi có thay đổi thực chất ảnh hưởng Phase khác.

**C. Thiết kế / dependency phải đối chiếu theo nhiệm vụ:**

- [API Contract §7: 6 Listing endpoints, DTO/error/pagination](../../design/api-contract.md)
- [Database Design §§9,11: gpu_listings, TX-PAUSE-EDIT, Listing locks](../../design/database-design.md)
- [Module Design: Registry and write ownership](../../design/module-design.md)
- [Test Design: API-LIST-01..18, DBTX](../../design/test-design.md)
- [Phase 1B: DB/Repository prerequisites](../../architecture/phases/phase1b_database_persistence.md)
- [GPU-002-A revision 3: schema matrix, grants/trigger/test harness đang đề xuất](../../architecture/phases/phase1b_gpu002a_schema_matrix.md) — đối chiếu Phase 1D §2.1 và §3.2; chỉ dùng phần đề xuất sau khi có quyết định/ACK cần thiết.
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

**Cập nhật coding slice 24/10/2026:** `IN_PROGRESS / INTEGRATION_BLOCKED`, branch `feat/gpu-004-listings` trên `main@f9124f7`, bàn giao bằng Draft PR. Backend/core/router và frontend component/client đã được viết; 154 backend tests đạt (102 Listings với doubles), 58 upstream PostgreSQL tests skipped do thiếu cluster test, 27 frontend tests và TypeScript/build đạt trong phạm vi Phase 1D §3.5. Consumption interfaces chưa có ACK TV2/TV3/nhóm trưởng cho diff implementation (`XPH-GPU-004-01`, `POTENTIAL_IMPACT / AWAITING_CROSS_PHASE_ACK`); adapter DB/Auth và shared wiring chưa có. Không gọi đây là full Phase 1D PASS hoặc `IMPLEMENTED`.

**Cập nhật 25/10/2026:** nhánh đã sync `main@028c355`; helper `create_authenticated_listing_router` dùng dependency GPU-003 thật. Có **491 backend tests pass / 58 PostgreSQL tests skipped**, gồm **201** Listings tests (**65** real-Auth/persistence-double cases và **32** UUID-path regression cases); frontend **27 pass**, TypeScript/build **PASS**. Đã sửa P2 để 4 routes từ chối UUID không canonical bằng 422 trước Listing UoW. Terminal Job guard dùng đúng `COMPLETED/FAILED/CANCELLED` của schema; chưa phải DB fixture đầy đủ. Lệnh và giới hạn chi tiết ở Phase 1D §3.6/README.

**Auth coordination:** PR #18/#23/#26 đã merge, API Contract v0.9 ghi profile `DEC-P1-03`; [ACK #13](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/13#issuecomment-6372588314) là lịch sử, [ACK `XPH-GPU-003-05`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/23#issuecomment-6382291607) và [ACK session #26](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/26#issuecomment-6387480528) còn actions. Đã tiêu thụ dependency/SessionStore thật; account adapter #25 vẫn Draft/unmerged. Consumer tests không thay PostgreSQL account/UoW hoặc mounted-app evidence.

**DB coordination:** [TV4 ACK_WITH_ACTIONS cho D1 #27 tại `ab32545`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/27#issuecomment-6387610827); #27 đã merge tại baseline mới. [Kiểm kê TV4 #22](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/22#issuecomment-6387611172) đã nhận xác nhận người dùng chưa từng dùng DB/Alembic cho dự án, không cần D1 recovery theo lịch sử báo cáo. Docker engine stopped, local DB tests `BLOCKED`; chưa live query revision/kiểm kê volume hay bootstrap/migrate/downgrade.

**Gate giữ nguyên:** [owner review R1–R4 của #17](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6380470641) chưa đóng. Chờ PostgreSQL adapters/grants/timestamps, shared router/UI/config/correlation/audit, DB/race/E2E tests, ACK/actions và independent human re-review trên HEAD cuối. Không coi consumer ACK là human approval hoặc full Phase 1D `PASS`.

## Pre-PR Checklist — GPU-004 (chưa xác nhận)

**Bàn giao tiếp sau #26/#27 merge (25/10/2026):** đã đồng bộ main, thêm `createSessionListingsApi`/`SessionListingsPage` dùng chung session thật theo handoff TV3 §9, chưa mount shared shell. TV2 [ACK ports/service](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6388130749), TV3 [xác nhận backend Auth](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6389075737), TV5 [ACK_WITH_ACTIONS/HOLD](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/17#issuecomment-6389243659) trên `f7d3c0d`; cần xử lý actions/re-review diff mới, không coi ACK là human approval.

Request-ID trusted-state correlation, early reject body pause/resume và parser RecursionError đã sửa. POST/PATCH vẫn chờ nhóm trưởng duyệt raw body/depth bounds, không tự áp 16 KiB/depth 8 của Auth. R1 chờ TV2 Listing UoW/D7; #25 vẫn Draft. Actual tests: **537 backend passed / 132 PostgreSQL skipped**, gồm **238 Listings** (37 HTTP cases mới); frontend **102 pass**, gồm 9 real-session consumer cases; TypeScript/build/Ruff PASS. PG/race/browser E2E/audit vẫn BLOCKED/NOT_RUN; không mở rộng quyền DB hoặc sửa phần người khác để đi vòng blocker. Chi tiết/lệnh ở Phase 1D §3.7/README.

Lịch sử DB TV4 đã được người dùng xác nhận: chưa từng dùng DB/Alembic cho dự án, D1 recovery không cần theo lịch sử báo cáo. Docker local vẫn stopped; không khởi động/apply migration trong lượt này. Giữ HOLD, chưa yêu cầu merge.

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
