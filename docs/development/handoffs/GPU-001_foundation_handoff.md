# GPU-001 - Foundation / Integration Handoff

> Status: IMPLEMENTED AND MERGED on 2026-10-21.
> Owner: Team Lead.
> Baseline commit: c90f540b385c8d11789f994748e4f5441bcb7e1b.
> PR: https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/3
> Companion architecture: [phase1_project_foundation.md](../../architecture/phases/phase1_project_foundation.md)
> Legacy as-built handoff at historical merged revision: https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/c90f540b385c8d11789f994748e4f5441bcb7e1b/docs/development/foundation-handoff.md

## 0. Mandatory Reading & Working Rules — BẮT BUỘC

**Điều kiện trước khi bắt đầu:** người phụ trách phải đọc các tài liệu dưới đây **trên baseline Git mới nhất**, ghi phiên bản/commit SHA đã đọc, kiểm tra sự khác biệt với baseline ghi ở đầu handoff và xác nhận các dependency thực sự sẵn sàng. Việc chủ dự án duyệt thiết kế **không tự cho phép** bắt đầu code hoặc merge.

**A. Quy tắc làm việc của nhóm (đọc đủ 3 tài liệu):**

1. [Team Contribution Rules](../team-contribution-rules.md) — ownership, branch/commit, PR, independent human reviewer và điều kiện merge.
2. [Change Control](../change-control.md) — cấp độ L0–L3, quyền ra quyết định, thay đổi Requirements/ADR/API/DB contracts.
3. [Inter-Phase Change Control](../interphase-change-control.md) — phân loại tác động, cảnh báo, hai phía xác nhận và `BLOCKED_INTERPHASE`.

**B. Kiến trúc & mẫu xác nhận:**

- [Kiến trúc GPU-001 đã phê duyệt](../../architecture/phases/phase1_project_foundation.md) — phạm vi, invariants, status, acceptance gates của Phase này.
- [Inter-Phase Review Template](../../architecture/phases/_interphase_review_template.md) — mẫu bắt buộc dùng khi có thay đổi thực chất ảnh hưởng Phase khác.

**C. Thiết kế / dependency phải đối chiếu theo nhiệm vụ:**

- [Kiến trúc tổng thể](../../architecture/system-architecture.md)
- [ADR-001: modular monolith](../../architecture/decisions/ADR-001-modular-monolith.md)
- [ADR-002: PostgreSQL access boundaries](../../architecture/decisions/ADR-002-postgresql-access-boundaries.md)
- [ADR-008: technology stack](../../architecture/decisions/ADR-008-technology-stack.md)
- [Module Design](../../design/module-design.md)
- [Test Design](../../design/test-design.md)

**D. Quy tắc thực hiện và phối hợp:**

- Không tự sửa code/tài liệu ngoài module ownership, không tự đổi quyết định đã duyệt; gặp mâu thuẫn giữa hai nguồn chuẩn thì **dừng phần bị ảnh hưởng và báo nhóm trưởng/chủ dự án**, không tự chọn một phiên bản.
- Trước mỗi thay đổi Markdown **hoặc** code, so sánh trước/sau và phân loại `NO_IMPACT | POTENTIAL_IMPACT | CONFIRMED_IMPACT`. `NO_IMPACT` chỉ dành cho thay đổi không đổi nghĩa kỹ thuật và phải có lý do; hai mức còn lại phải cảnh báo source owner, **từng** affected owner và nhóm trưởng.
- Với `POTENTIAL_IMPACT`/`CONFIRMED_IMPACT`, lập record bằng template; nhận ACK của **source owner + từng consumer owner** (cùng evidence link), xử lý các action/test cần thiết. Thiếu ACK hoặc còn xung đột → `BLOCKED_INTERPHASE`, **không được merge hoặc dùng làm baseline tích hợp**.
- **Quy tắc phối hợp riêng:** Đây là handoff **canonical** cho GPU-001 sau khi chuẩn hoá tài liệu; quy tắc mới áp dụng cho **thay đổi tương lai**, không áp dụng hồi tố để sửa kết quả PR #3. Handoff legacy đã được gỡ theo yêu cầu chủ dự án; bản as-built tại merge commit vẫn truy xuất được trong [Git history](https://github.com/SE2026-BC-04/gpu-resource-marketplace/blob/c90f540b385c8d11789f994748e4f5441bcb7e1b/docs/development/foundation-handoff.md). Đọc handoff GPU-002..GPU-005 trước khi sửa `common/`, `api/app.py`, frontend shared client, Compose, CI hoặc Alembic để biết consumer nào phải xác nhận.
- Trước PR/merge: chạy các tests áp dụng được, công bố `PASS | FAIL | BLOCKED | NOT_RUN` trung thực, cung cấp Git SHA/DB revision/commands/evidence; tuân thủ human review độc lập theo cấp độ, không self-approve/self-merge.
- **Trong mô tả PR bắt buộc ghi:** `Mandatory Reading ACK` (đã đọc những file nào, tại commit/revision nào), `Inter-Phase Impact` (kể cả `NO_IMPACT` có lý do), liên kết ACK thật nếu cần và `Test Evidence`. Không coi checklist tự đánh dấu là xác nhận thay người phụ trách khác.

Đây là **GPU-001 handoff canonical** tại `docs/development/handoffs/GPU-001_foundation_handoff.md`. Tài liệu bổ sung governance sau merge, **không thay đổi hồi tố** PR #3 hoặc tự nhận có independent human review lịch sử.

### 2.2. Thành phần và quyền hạn

| Service | Công nghệ | Trách nhiệm ở Phase 1 | Kết nối |
|---|---|---|---|
| `frontend` | React 19, TypeScript, Vite, Node 24 | Placeholder UI; Vite production build, static server và SPA fallback | Host `127.0.0.1:5173`; không có DB access |
| `api` | Python 3.12, FastAPI, Pydantic 2 | `/health/live`, `/health/ready`, CORS, config/logging | Host `127.0.0.1:8000`; DB nội bộ |
| `manager` | Python 3.12, shared backend package | DB readiness, idle lifecycle, graceful shutdown | DB nội bộ; không public HTTP port |
| `simulator` | Python project và Docker image riêng | Health endpoints; runtime tách biệt | `app` network; không có DB credentials/driver/port |
| `postgres` | PostgreSQL 16 | Database service + volume lâu dài; chưa có business tables | Nội bộ + host `127.0.0.1:5432` cho local tools |

## 5. Kết quả và bằng chứng nghiệm thu GPU-001

**Baseline:** [`main@c90f540b`](https://github.com/SE2026-BC-04/gpu-resource-marketplace/commit/c90f540b385c8d11789f994748e4f5441bcb7e1b) — merge ngày **21/10/2026**.<br>
**CI:** [GitHub Actions run #39554208291](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/39554208291).

| Hạng mục | Kết quả quan sát được |
|---|---|
| `python` CI job | **PASS**; Backend + topology **23 tests**; Simulator **2 tests** |
| `frontend` CI job | **PASS**; Vitest **3 tests**, typecheck và build |
| `compose` CI job | **PASS**; cả **5 services healthy** |
| Host → PostgreSQL | **PASS**; loopback TCP và truy vấn `SELECT 1` |
| API + Manager → PostgreSQL | **PASS**; readiness / healthcheck |
| Host → Frontend / API | **PASS**; production index, JS bundle, SPA fallback, API health |
| Simulator isolation | **PASS**; Simulator gọi được API nội bộ nhưng không resolve/connect trực tiếp PostgreSQL |
| Concurrent Compose stacks | **PASS**; stack local và smoke stack chạy cùng lúc |
| Smoke cleanup isolation | **PASS**; smoke resources bị xóa, container/network/volume IDs của local stack giữ nguyên |

**Giới hạn của bằng chứng:** Docker smoke được xác nhận trên **Linux GitHub Actions**; không có kết quả Docker local độc lập trên Windows. Cảnh báo Starlette/httpx deprecation không làm tests thất bại. Các bài kiểm thử DB nghiệp vụ, Auth, Listings, Jobs, Signed Results, E2E đầy đủ và benchmark 736 VU **chưa chạy**; không được ghi PASS.

### 5.1. Đối chiếu mục tiêu — kết quả

| Mục tiêu §1 | Kết quả | Trạng thái |
|---|---|---|
| 5 services chạy và healthy | Compose runtime smoke | **DONE** |
| Runtime isolation | Simulator không truy cập trực tiếp DB | **DONE** |
| Source/module boundaries | Các package và entrypoints được tạo | **DONE** |
| Build/tests/CI | 3 CI jobs PASS tại merge commit | **DONE** |
| Business API/data thực tế | Cố ý chưa triển khai trong GPU-001 | **DEFERRED** |

**Kết luận kỹ thuật:** **GPU-001 = IMPLEMENTED / MERGED**, không đồng nghĩa Marketplace MVP đã hoàn thành.

## 7. Lộ trình tiến hóa và bàn giao

| Kiến trúc | Task | Deliverable chính | Trạng thái |
|---|---|---|---|
| **Phase 1** | GPU-001 | 5 services, module boundaries, health/readiness, Docker/CI | **IMPLEMENTED** |
| Phase 1B | GPU-002 | 10 business tables, models, Alembic, persistence + DB tests | PLANNED |
| Phase 1C | GPU-003 | Login/Me/Logout, JWT/RBAC, Login UI | PLANNED |
| Phase 1D | GPU-004 | Listings APIs, ownership/Pause/Resume, Listings UI | PLANNED |
| Phase 1E | GPU-005 | Submit/Read/Cancel Jobs, `QUEUED`, atomic reference, Jobs UI | PLANNED; oracle spec needed |
| Phase 2 | Các nhiệm vụ sẽ lập sau | Scheduling, execution, Signed Results, +6 tables | FUTURE |
| Phase 3 | Các nhiệm vụ sẽ lập sau | Dispute/Retention, +2 tables | FUTURE |

**Bộ 10 bảng Phase 1B:** `users`, `roles`, `user_roles`, `workers`, `worker_public_keys`, `gpu_listings`, `jobs`, `simulation_references`, `worker_reputation_aggregates`, `audit_events`.

**6 bảng Phase 2:** `execution_attempts`, `allocations`, `execution_outbox`, `result_inbox`, `signed_results`, `job_reputation_contributions`.

**2 bảng Phase 3:** `disputes`, `retention_exceptions`.

**Thứ tự tích hợp:** Foundation → Database → Auth → Listings → Jobs → E2E Phase 1. Các thành viên có thể làm việc trên branches riêng bằng interfaces/mocks, nhưng không được merge trái dependency, migration hoặc contract.

### 7.1. Kiểm soát thay đổi từ Foundation sang các Phase khác (bổ sung 21/10/2026)

Chủ dự án yêu cầu **cảnh báo và xác nhận giữa 2 người phụ trách** khi một cập nhật thực chất trong Markdown/code của GPU-001 gây ảnh hưởng đến Phase khác. Quy tắc áp dụng cho những thay đổi **sau** quyết định này; không áp dụng hồi tố để thay đổi kết quả PR #3. Chi tiết tại [Inter-Phase Change Control](../interphase-change-control.md).

| Thành phần GPU-001 có thể thay đổi | Phase phải rà soát **khi có tác động thực tế** | Hai phía cần xác nhận |
|---|---|---|
| `compose.yaml`, DB URL/network, Alembic bootstrap | GPU-002, GPU-003/004/005 nếu phụ thuộc | Nhóm trưởng + owner Phase bị ảnh hưởng |
| `api/app.py`, shared `common/`, CORS/error/router | GPU-003/004/005 | Nhóm trưởng + từng owner đang dùng interface |
| Frontend API client, shell, build-time config | GPU-003/004/005 | Nhóm trưởng + owner UI bị ảnh hưởng |
| Simulator boundary hoặc shared domain/repository import | GPU-002/005 và Phase 2 (nếu liên quan) | Nhóm trưởng + owner consumer |

**Gate:** người thay đổi đánh giá diff thành `NO_IMPACT`/`POTENTIAL_IMPACT`/`CONFIRMED_IMPACT`. Nếu có tác động, ghi cảnh báo kèm before/after, ảnh hưởng contract/tests và `ACK` hai phía trong PR/biên bản trước khi merge/tích hợp; thiếu xác nhận → `BLOCKED_INTERPHASE`. Chỉ đổi chính tả/định dạng không đổi nghĩa thì ghi `NO_IMPACT` và không bắt buộc lấy ACK. Quy tắc này **bổ sung**, không thay độc lập reviewer L0/L1 (≥1), L2/L3 (≥2) và change control gốc.

## Current next-phase handoff state

| Slice | Owner | Status | Main integration need |
|---|---|---|---|
| GPU-002 / Phase 1B | Member 2 | APPROVED DESIGN; NOT IMPLEMENTED | PostgreSQL schema, models, migrations, repository and tests |
| GPU-003 / Phase 1C | Member 3 | APPROVED DESIGN; NOT IMPLEMENTED | JWT, authenticated principal, Login UI, database integration |
| GPU-004 / Phase 1D | Member 4 | APPROVED DESIGN; NOT IMPLEMENTED | Listing API/UI, ownership, Listing-first transactions |
| GPU-005 / Phase 1E | Member 5 | APPROVED DESIGN; NOT IMPLEMENTED | Jobs API/UI, atomic reference, queue admission/cancel |

**Inter-phase gate:** any actual Foundation/shared-file change affecting downstream phases must be classified and acknowledged by the Team Lead as source owner and by EACH affected downstream owner, theo [Inter-Phase Change Control](../interphase-change-control.md). Independent PR reviews remain mandatory. No such future diff is approved by packaging these files.

## Pre-PR Checklist — GPU-001 (chưa xác nhận)

> Checklist phải được chính thành viên phụ trách hoàn thành **trước khi yêu cầu merge** và gắn vào PR. Các ô bên dưới mặc định chưa đánh dấu; tài liệu được duyệt không đồng nghĩa đã hoàn thành các bước.

- [ ] Đã đọc `team-contribution-rules.md`, `change-control.md`, `interphase-change-control.md` và ghi `Mandatory Reading ACK` kèm commit SHA/revision.
- [ ] Đã đọc kiến trúc GPU-001, `docs/design/`/ADR liên quan, và kiểm tra baseline/contract của các Phase phụ thuộc.
- [ ] Đã kiểm tra ownership: chỉ sửa các file đúng trách nhiệm hoặc có xác nhận từ owner của shared file.
- [ ] Đã đánh giá diff Markdown/code: `NO_IMPACT` có lý do hoặc `POTENTIAL_IMPACT` / `CONFIRMED_IMPACT` với Impact Report theo template.
- [ ] Nếu có ảnh hưởng liên Phase, đã thông báo source owner, **từng** affected owner và nhóm trưởng; đã nhận đủ ACK có link thật, xử lý `ACK_WITH_ACTIONS` và không còn `BLOCKED_INTERPHASE`.
- [ ] Nếu thay đổi Requirements/ADR/API Contract/Database Design, đã đi đúng Change Control và nhận quyết định của người có thẩm quyền.
- [ ] Đã chạy các test bắt buộc có thể áp dụng; ghi rõ lệnh, fixture, commit SHA, kết quả và bằng chứng; không ghi PASS cho `NOT_RUN` / `BLOCKED`.
- [ ] Đã cập nhật phase doc, handoff / README cần thiết và kiểm tra Markdown links, bảo đảm status triển khai phản ánh code/PR thật.
- [ ] Đã ghi `Mandatory Reading ACK`, `Inter-Phase Impact`, `Test Evidence` trong PR và yêu cầu **independent human reviewer** theo cấp độ; không tự approve/merge.
