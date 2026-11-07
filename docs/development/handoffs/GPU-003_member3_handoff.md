# GPU-003 — Handoff cho Thành viên 3: Authentication & RBAC

> **Dự án:** GPU Resource Marketplace<br>
> **Phase:** 1C / `GPU-003`<br>
> **Ngày chủ dự án phê duyệt:** 21/10/2026<br>
> **Trạng thái:** `APPROVED DESIGN / IMPLEMENTATION NOT STARTED`<br>
> **Phụ trách:** Thành viên 3; nhóm trưởng phụ trách tích hợp `api/app.py`/shared configuration<br>
> **Baseline đã kiểm tra:** `main@c90f540b385c8d11789f994748e4f5441bcb7e1b`<br>
> **File kiến trúc dự kiến:** `docs/architecture/phases/phase1c_authentication_rbac.md` — bản local đã duyệt, chưa commit trên GitHub.

## 0. Mandatory Reading & Working Rules — BẮT BUỘC

**Điều kiện trước khi bắt đầu:** người phụ trách phải đọc các tài liệu dưới đây **trên baseline Git mới nhất**, ghi phiên bản/commit SHA đã đọc, kiểm tra sự khác biệt với baseline ghi ở đầu handoff và xác nhận các dependency thực sự sẵn sàng. Việc chủ dự án duyệt thiết kế **không tự cho phép** bắt đầu code hoặc merge.

**A. Quy tắc làm việc của nhóm (đọc đủ 3 tài liệu):**

1. [Team Contribution Rules](../team-contribution-rules.md) — ownership, branch/commit, PR, independent human reviewer và điều kiện merge.
2. [Change Control](../change-control.md) — cấp độ L0–L3, quyền ra quyết định, thay đổi Requirements/ADR/API/DB contracts.
3. [Inter-Phase Change Control](../interphase-change-control.md) — phân loại tác động, cảnh báo, hai phía xác nhận và `BLOCKED_INTERPHASE`.

**B. Kiến trúc & mẫu xác nhận:**

- [Kiến trúc GPU-003 đã phê duyệt](../../architecture/phases/phase1c_authentication_rbac.md) — phạm vi, invariants, status, acceptance gates của Phase này.
- [Inter-Phase Review Template](../../architecture/phases/_interphase_review_template.md) — mẫu bắt buộc dùng khi có thay đổi thực chất ảnh hưởng Phase khác.

**C. Thiết kế / dependency phải đối chiếu theo nhiệm vụ:**

- [API Contract: authentication §§3–6,14 và error conventions](../../design/api-contract.md)
- [Database Design: users, roles, user_roles, workers, audit_events](../../design/database-design.md)
- [Module Design: Identity/RBAC và principal](../../design/module-design.md)
- [Test Design: API-AUTH-01..14](../../design/test-design.md)
- [Phase 1B: dependency DB/Repository](../../architecture/phases/phase1b_database_persistence.md)
- [Phase 1D: downstream Listing authorization](../../architecture/phases/phase1d_gpu_listings.md)
- [Phase 1E: downstream Job authorization](../../architecture/phases/phase1e_job_submission_queue.md)

**D. Quy tắc thực hiện và phối hợp:**

- Không tự sửa code/tài liệu ngoài module ownership, không tự đổi quyết định đã duyệt; gặp mâu thuẫn giữa hai nguồn chuẩn thì **dừng phần bị ảnh hưởng và báo nhóm trưởng/chủ dự án**, không tự chọn một phiên bản.
- Trước mỗi thay đổi Markdown **hoặc** code, so sánh trước/sau và phân loại `NO_IMPACT | POTENTIAL_IMPACT | CONFIRMED_IMPACT`. `NO_IMPACT` chỉ dành cho thay đổi không đổi nghĩa kỹ thuật và phải có lý do; hai mức còn lại phải cảnh báo source owner, **từng** affected owner và nhóm trưởng.
- Với `POTENTIAL_IMPACT`/`CONFIRMED_IMPACT`, lập record bằng template; nhận ACK của **source owner + từng consumer owner** (cùng evidence link), xử lý các action/test cần thiết. Thiếu ACK hoặc còn xung đột → `BLOCKED_INTERPHASE`, **không được merge hoặc dùng làm baseline tích hợp**.
- **Quy tắc phối hợp riêng:** Việc đồng bộ nhãn `DEC-P1-03` trong API Contract phải làm rõ đây là quyết định chủ dự án đã duyệt; không tự điều chỉnh profile JWT, normalization hay Auth error contract. Cảnh báo TV2/TV4/TV5 và nhóm trưởng nếu interface principal, credentials, frontend auth client, repository hoặc router bị ảnh hưởng; không thay owner ACK bằng lời xác nhận của AI.
- Trước PR/merge: chạy các tests áp dụng được, công bố `PASS | FAIL | BLOCKED | NOT_RUN` trung thực, cung cấp Git SHA/DB revision/commands/evidence; tuân thủ human review độc lập theo cấp độ, không self-approve/self-merge.
- **Trong mô tả PR bắt buộc ghi:** `Mandatory Reading ACK` (đã đọc những file nào, tại commit/revision nào), `Inter-Phase Impact` (kể cả `NO_IMPACT` có lý do), liên kết ACK thật nếu cần và `Test Evidence`. Không coi checklist tự đánh dấu là xác nhận thay người phụ trách khác.

## 1. Nhiệm vụ

Tích hợp Authentication & Role-Based Access Control với PostgreSQL thật để Client/Worker/Admin có thể Login, xem danh tính qua `/me` và Logout trên React UI; cung cấp backend `AuthenticatedPrincipal` và role guards tái sử dụng cho GPU-004/GPU-005.

**Ranh giới:** không đăng ký công khai, refresh/session table, OAuth/SSO, đăng ký Worker, thay đổi role, Login giả/hardcoded, Listings/Jobs APIs, dashboard nghiệp vụ, Scheduler/Simulator execution hoặc thêm bảng/service.

## 2. Công việc theo thứ tự

| ID | Công việc giao | Output bắt buộc | Review/Dependency |
|---|---|---|---|
| `GPU-003-A` | Đồng bộ `DEC-P1-03` đã được duyệt vào API Contract §§4.5/14.3 và oracle test liên quan | PR tài liệu phân biệt owner approval với implementation; không sửa chính sách | Theo `docs/development/change-control.md`; không tự merge |
| `GPU-003-B` | Xây login name normalizer, password verifier và HS256 JWT codec | Unit tests về Unicode/case, bad password, typ/iss/aud/sub/iat/exp, 900s cutoff chính xác microsecond | Chốt password-hash/provisioning algorithm và JWT serialization/library trong technical review |
| `GPU-003-C` | Auth service, reusable principal/role guard, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` | FastAPI routes theo v0.6; DB-driven account/role/status; generic errors/no-store; no public registration | Phụ thuộc migration + Account/Role repository từ GPU-002 |
| `GPU-003-D` | React Login UI, Auth API client và volatile token state | Login → Me → Logout, 3 role identities; refresh không khôi phục token; loading/error/expiry | Trưởng nhóm phối hợp tích hợp router, CORS, shared app shell |
| `GPU-003-E` | Backend integration + frontend + HTTP/security tests | PostgreSQL-backed pytest, Vitest, minimal browser/user journey, redaction; evidence cho phần test khả thi | GPU-002 đã tích hợp; test downstream chuyển handoff |
| `GPU-003-F` | CI regression, runbook, docs và **cross-phase impact ACK** trước PR merge | Git SHA, migration revision, lệnh/test logs, action/owner ACK, review độc lập | Không đổi `IMPLEMENTED` trước merge và tests PASS |

## 3. Contract không được tự thay đổi

**API:**

| Route | Success | Error/authorization |
|---|---|---|
| `POST /api/v1/auth/login` | `200`, `{access_token, token_type:'Bearer', expires_in:900, user:{id,login_name,role}}` | Sai/disabled: `401 INVALID_CREDENTIALS` cùng thông điệp; bad schema `400/422` theo contract |
| `GET /api/v1/auth/me` | `200`, `{id,login_name,role}` lấy từ DB authoritative | Missing/tampered/expired JWT, disabled/missing role: `401` |
| `POST /api/v1/auth/logout` | `204`, no body; không revoke JWT phía server | Missing/invalid bearer: `401`; frontend xóa token trong memory |

**JWT & Unicode (`DEC-P1-03` đã owner-approved):** JWT `HS256`, API-only secret tối thiểu 256 bits; `iss='gpu-marketplace-api'`, `aud='gpu-marketplace-web'`, header `typ='JWT'`, `sub=UUID`; `iat`/`exp` dùng NumericDate 6 chữ số thập phân, `exp=iat+900s`, no leeway, so sánh microseconds không truncation. Login chỉ trim ASCII SP/HT/LF/CR ở đầu/cuối; case-sensitive; không NFC/NFD/casefold, không trim U+00A0; dùng chung quy tắc với provisioning. Không trim password.

**RBAC:** chỉ `CLIENT`, `WORKER`, `ADMIN`. Mỗi protected request luôn xác nhận `users.status='ACTIVE'` và role hiện hành từ `user_roles`, không tin claim vai trò do client gửi. Admin read-only theo thiết kế, không phải Manager. Object ownership nằm trong server-side query của module chủ sở hữu. Không dùng token nội bộ Manager/Simulator như JWT người dùng.

**Secrets:** token chỉ tồn tại trong volatile frontend memory; không localStorage/sessionStorage/IndexedDB/cookie/URL/service-worker; response private/auth `Cache-Control: no-store`, logs/audit redacted, secret không nằm frontend build.

## 4. File/module ownership

```text
backend/src/gpu_marketplace/identity/        # Chủ sở hữu Thành viên 3
backend/tests/test_identity_*.py             # Auth unit/API/integration fixtures
frontend/src/api/                             # Auth DTO/client + tests (phối hợp shared client)
frontend/src/ui/                              # Login/logout UI + tests (phối hợp App shell)
backend/src/gpu_marketplace/api/app.py        # Nhóm trưởng tích hợp/router
backend/src/gpu_marketplace/common/config.py # Shared config; chỉ thay đổi khi leader review
backend/src/gpu_marketplace/repositories/     # Thuộc GPU-002; không viết ORM model thứ hai
```

**Không tự sửa:** Requirements/ADR, API contracts khác quyết định đã duyệt, Database Design/migrations của Thành viên 2, Manager/Simulator modules. Nếu phải thay contract hoặc schema: lập CR và xin duyệt L2/L3 theo quy định.

## 5. Kiểm thử và nghiệm thu

| Gate | Điều kiện đạt |
|---|---|
| `P1C-AC-01` | C1/W1/A1 Login qua real DB, đúng role; non-existent/wrong password/disabled cùng generic `401` |
| `P1C-AC-02` | Tampered JWT, wrong signature/algorithm/issuer/audience/header/sub bị `401`, không lộ identity |
| `P1C-AC-03` | Fake clock T0: `+899.999999s` valid, `+900.000000s` expired; JSON NumericDate microsecond được bảo toàn |
| `P1C-AC-04` | ASCII SP/HT/LF/CR trimmed, U+00A0 preserved, case-sensitive, no NFC/NFD; provisioning đồng nhất với Login |
| `P1C-AC-05` | Disable user/đổi role sau phát hành được phản ánh bởi DB trên request kế tiếp; role thiếu/không hợp lệ bị deny |
| `P1C-AC-06` | HTTP contract 3 endpoint, error format, `X-Request-ID`, `no-store`, không có public signup/role-changing API |
| `P1C-AC-07` | UI dùng real API, Login→Me→Logout; token không persist sau reload; không leak password/token vào console/build/storage |
| `P1C-AC-08` | pytest/PostgreSQL integration, Vitest, CI/Compose foundation smoke vẫn PASS; ghi rõ những checks chưa thể chạy |
| `P1C-AC-09` | PR có evidence đầy đủ, human review độc lập, merge hợp lệ và tài liệu phase cập nhật trạng thái thực tế |

**Trace:** `API-AUTH-01..08`, `12`, `14` phải có kết quả runtime trực tiếp. `API-AUTH-09` (cross-role routes), `10` (private Job ownership), `11` (internal route token isolation), `13` (cross-service artifact leaks) chỉ chốt phần test có thể chạy trong Phase 1C; phần còn lại giữ `BLOCKED/NOT_RUN` đến GPU-004/005 hoặc Phase 2. Không đánh dấu cả test case `PASS` khi chưa đủ assertions.

## 6. Các việc cần technical review trước coding

1. **Password-hashing/provisioning:** Database Design chỉ yêu cầu `password_hash`, chưa duyệt thuật toán/verifier và cách seed password demo. Thành viên 2/3 đề xuất một interface thống nhất để duyệt.
2. **JWT tooling:** xác nhận thư viện Python, định dạng serialize và kiểm tra NumericDate microsecond/no leeway phù hợp exact contract.
3. **Shared integration:** nhóm trưởng duyệt thay đổi `api/app.py`, middleware/errors, config/CI; không phá `/health/live` và `/health/ready`.
4. **Document synchronization:** sync phê duyệt `DEC-P1-03` vào `docs/design/api-contract.md`/test descriptions trước khi triển khai các quy tắc đó; tuân thủ change control/human reviewers.

## 7. Điều kiện mở công việc và review Git

Đây là **handoff tài liệu** theo thiết kế vừa được chủ dự án duyệt, chưa phải lệnh bắt đầu code. Khi nhóm trưởng giao implementation rõ ràng, Thành viên 3 mở branch riêng từ `main` mới nhất (ví dụ `feat/gpu-003-auth-rbac`) và chia PR theo scope phù hợp. PR L0/L1 cần ≥1 reviewer người độc lập, L2/L3 cần ≥2; không tự approve/self-merge; Codex không thay thế human approval.

**Trạng thái cuối:** `GPU-003 APPROVED DESIGN / NOT IMPLEMENTED`; `GPU-002 APPROVED DESIGN / NOT IMPLEMENTED` tại baseline đã kiểm tra. Không suy diễn có test PASS hoặc PR merge cho Phase 1B/1C chỉ từ việc duyệt tài liệu.

## 8. Điều kiện bổ sung: xác thực liên Phase

> Theo [Inter-Phase Change Control](../interphase-change-control.md) trong repository. Yêu cầu mới đã được chủ dự án chấp thuận; không tự suy ra code/PR đã được review.

- Trước thay đổi `DEC-P1-03` docs sync, Auth policy, `AuthenticatedPrincipal`, Login UI/API client hay JWT serializer, **Thành viên 3** phải ghi `NO_IMPACT` hoặc cảnh báo `POTENTIAL_IMPACT/CONFIRMED_IMPACT` với old/new và version phụ thuộc.
- **Thành viên 2** xác thực cùng TV3 nếu ảnh hưởng account/role schema, password hash/provisioning hay repositories; **Thành viên 4** khi ảnh hưởng Listings role guards hoặc shared UI; **Thành viên 5** khi ảnh hưởng Client Job role guards/Bearer; **nhóm trưởng** khi thay `api/app.py`, shared config, CORS hoặc shell.
- Một thay đổi ảnh hưởng cả GPU-004 và GPU-005 phải nhận **hai consumer ACK tách biệt**; phải có cả nguồn TV3 xác nhận nội dung thay đổi. `ACK_WITH_ACTIONS` phải có người nhận và kết quả xử lý; im lặng hoặc test chưa chạy không là PASS.
- Nếu TV3 cần TV2 sửa schema/repository, phải làm ngược lại: cảnh báo, owner DB + owner Auth xác thực trước merge. Thiếu xác nhận → `BLOCKED_INTERPHASE`.
- PR GitHub vẫn tuân thủ ≥1 reviewer độc lập cho L0/L1, ≥2 cho L2/L3 và change control; không thay thế reviewer bằng 2 người tự ký checklist.

## 9. GPU-003-D: frontend session contract cho GPU-004/005 (`XPH-GPU-003-D`)

> Ghi nhận theo action của [owner re-review](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/26#pullrequestreview-5638977208) và hai consumer ACK trên PR #26. Đây là interface frontend đã được consumer chấp nhận, **không** đổi API Contract và **không** chứng minh integration đã chạy.

**Nguồn:** PR #26 (`frontend/src/api/session.ts`, `frontend/src/api/authorizedFetch.ts`). Các ACK được đưa ra trên HEAD `d877384`; commit `e97cb77` sửa P2 của TV5 (`cache: "no-store"` không bị caller ghi đè).

**Session store (`createSessionStore`, một instance cho mỗi lần tải trang, tạo ở `main.tsx`):**

| Thành phần | Ngữ nghĩa |
|---|---|
| `getAccessToken(): string \| null` | Đọc token lúc gửi request. Trả `null` khi chưa đăng nhập hoặc đã tới deadline bảo thủ (`thời điểm trước khi gửi Login + 900 s`); khi đó store tự về `signed-out` với lý do `expired` |
| `handleUnauthorized(sentToken: string)` | Chỉ xoá phiên khi `sentToken` trùng token hiện tại; 401 của token cũ không xoá phiên mới |
| `getState()` / `subscribe()` | `{ status: "signed-in", user: { id, loginName, role } }` (đã xác nhận qua `/auth/me`) hoặc `{ status: "signed-out", reason? }` |
| `signOut()` | Xoá token local trước, rồi gọi Logout best-effort; JWT không bị thu hồi ở server (API Contract section 4.4) |

**`createAuthorizedFetch(session)` → `(path, init?) => Promise<Response>`:** `path` tương đối với API base. Hàm tự đặt `Authorization: Bearer`; `credentials: "omit"` và `cache: "no-store"` được đặt sau `init`, nên caller không ghi đè được. Chưa đăng nhập thì không gửi request; 401 → `handleUnauthorized(tokenĐãGửi)`; 403 giữ phiên.

**Quy tắc cho consumer:** không lưu, log hay đưa token vào URL, Web Storage hay cookie; không coi role ở frontend là kiểm tra quyền (server luôn kiểm tra lại); dùng **cùng một** session instance với shell.

| Consumer | Phương án | ACK |
|---|---|---|
| TV4 / GPU-004 Listings (PR #17 `8ed7814`) | Giữ `createListingsApi(getAccessToken, onUnauthorized)`, kèm guard `getAccessToken() === token` ở `listings.ts:131`. Bridge: `onUnauthorized = () => { const t = session.getAccessToken(); if (t !== null) session.handleUnauthorized(t); }`. `ListingsPage.session = signed-in ? { userId: user.id, role: user.role } : null` | [`ACK_WITH_ACTIONS` 2026-10-25](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/26#issuecomment-6387480528) |
| TV5 / GPU-005 Jobs (PR #15 `aa56d94`) | (a) `createAuthorizedFetch(session)`; giữ nguyên `Idempotency-Key` khi retry một submission | [`ACK_WITH_ACTIONS` 2026-10-24](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/26#issuecomment-6386845588) |
| Nhóm trưởng (shell `App.tsx` / `main.tsx`) | Shell Login-first `App({ session })` | [`ACK_WITH_ACTIONS` 2026-10-24](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/26#pullrequestreview-5638977208) |

**Actions còn mở (không đóng bằng mục này):**
- **TV3:** sửa P2 cache của TV5 (`e97cb77`), xin xác nhận lại trên HEAD mới.
- **Nhóm trưởng + TV4/TV5 khi mount:** cùng một session cho shell và các protected client; giữ API instance ổn định và view Listings/Jobs; `session=null` khi signed-out.
- **Nhóm trưởng:** CORS cho `Authorization`, expose `X-Request-ID`; mount router Auth với `AccountReader` thật (PR #25).
- **Tất cả:** browser + API + PostgreSQL E2E (P1C-AC-07, GPU-003-E) vẫn `NOT_RUN` tại thời điểm PR #26; cập nhật ở mục 10.

## 10. GPU-003-E2/E3: evidence P1C-AC-07 và P1C-AC-08

> Baseline: nhánh tích hợp `feat/gpu-int-01-runtime-integration` (PR #39) tại `44579ed`. Mục này ghi evidence của TV3 cho phần Auth; **không** ghi `IMPLEMENTED` (P1C-AC-09 yêu cầu merge trước) và **không** thay cho review độc lập của PR #39.

### 10.1 E2 — P1C-AC-07 (browser)

**Test:** `backend/tests/test_auth_session_browser_e2e.py` dựng cluster PostgreSQL tạm (hàng rào `db_safety`) → bootstrap role → Alembic head → 3 tài khoản tạm (CLIENT, WORKER có hồ sơ Worker, CLIENT không phụ thuộc để khóa giữa phiên) → API production chạy bằng login native `gpm_api_app` → build + preview frontend production → `frontend/e2e/auth-session.spec.ts` trên Chromium (config `frontend/e2e/auth-session.config.ts`). Mật khẩu, secret và DSN sinh mới mỗi lần chạy; output lỗi được che. Env của mọi tiến trình con được dựng tường minh: bỏ toàn bộ biến kế thừa `GPU_MARKETPLACE_*`, `GPM_*`, `PG*`, `DATABASE_URL` và mọi biến có giá trị chứa credential bị cấm, rồi chỉ cấp lại đúng biến cần thiết. Chỉ API nhận DSN runtime `gpm_api_app`; build, preview và Playwright không nhận DSN nào, không tiến trình con nào nhận DSN/mật khẩu owner (`test_child_environments_never_receive_owner_credentials`). Mật khẩu của `gpm_api_app`/`gpm_manager_app` là trạng thái toàn cluster, schema reset không trả lại được: fixture `owner_engine_with_restored_roles` dùng `backend/tests/role_credentials.py` chụp đúng verifier cũ trong `pg_authid` trước khi đổi, khôi phục và đọc lại ở teardown dù test PASS hay FAIL; khôi phục lỗi → teardown ERROR, không in verifier (`test_role_credentials_restore.py`). Luồng chung Worker → Listing → Client → Job thuộc `test_phase1_runtime_http_postgres_e2e.py`, không lặp lại ở đây.

| ID | Kiểm | Oracle |
|---|---|---|
| E2-01 | Login qua form | Panel hiện đúng login + role từ DB; đúng 1 `POST /auth/login`, sau đó `GET /auth/me` |
| E2-02 | Sai mật khẩu / không tồn tại / tài khoản DISABLED | Cùng một thông báo; ô mật khẩu bị xóa |
| E2-03 | Bearer | Login không có `Authorization`; `/me`, `/gpu-listings`, `/jobs` đều mang đúng token của response Login |
| E2-04 | Reload | Về form; không request nào mang token sau reload |
| E2-05 | Tab mới | Chưa đăng nhập |
| E2-06 | Storage khi đăng nhập, sau Logout, sau reload | Token và mật khẩu không có trong Web Storage, `document.cookie`, cookie jar của context (gồm cookie HttpOnly), key/value của mọi object store IndexedDB, CacheStorage, service worker, URL, history state. Chỉ trả boolean, không in credential |
| E2-06b | Tự kiểm bộ dò E2-06 | Canary ngẫu nhiên đặt vào cookie HttpOnly và một record IndexedDB lồng nhau phải bị phát hiện đúng hai chỗ đó |
| E2-07 | Console + pageerror | Không chứa token hay mật khẩu |
| E2-08 | Logout | Đúng 1 request Logout, mang đúng Bearer của phiên; 204; UI về form; token đã sao chép vẫn dùng được tới `exp` (section 4.4, không revoke) |
| E2-09 | Request ID qua CORS thật của Chromium | `X-Request-ID` đọc được, là UUID, trùng `error.request_id` |
| E2-10 | Khóa tài khoản giữa phiên rồi bấm "Tải lại" | 401; UI về form với lý do `unauthorized`; không lộ trạng thái tài khoản |
| E2-11 | `page.clock` tua quá 900 s | UI về form với lý do `expired`; không request nào gửi token cũ |
| E2-12 | Đổi WORKER → CLIENT | Sau khi đổi, không request nào mang token cũ; không còn hiện tài khoản cũ |
| E2-13 | Build có biến secret server trong env (giá trị canary ngẫu nhiên, không phải credential thật) | Không canary hay secret nào lọt vào `frontend/dist` |
| E2-14 | `Cache-Control` | `no-store` trên Login 200/401, `/me`, Logout |
| — | Log API | Không chứa secret, mật khẩu hay chuỗi dạng JWT |

**Mutation** (sửa tạm trên worktree, không commit; mỗi mutation phải làm test FAIL):

| Mutation | Kết quả | Check bắt được |
|---|---|---|
| Lưu token vào `sessionStorage` | KILLED | E2-06 |
| Bỏ `Authorization` ở `/me` | KILLED | E2-01 (đăng nhập không được xác nhận) |
| Ghi token ra console | KILLED | E2-07 |
| Bỏ `expose_headers` khỏi CORS | KILLED | E2-09 |
| Bỏ timer hết hạn phía client | KILLED | E2-11 |
| Bỏ qua 401 của Listings/Jobs | KILLED | E2-10 |
| Lưu token vào một record IndexedDB (review #42 P2-02) | KILLED | E2-06 (`indexedDB: true`, cả khi đăng nhập và sau reload) |
| Harness trả `_child_environment` về cách cũ (copy `os.environ`, chỉ bỏ 4 biến) (review #42 P2-01) | KILLED | `test_child_environments_never_receive_owner_credentials` |
| Bỏ bước khôi phục mật khẩu role trong `restored_login_role_credentials` (re-review #42 P2) | KILLED | 4/5 test `test_role_credentials_restore.py` (output chỉ có boolean) |

**Kết quả local** (Windows 11, PostgreSQL 16.15 cluster tạm, Python 3.12.15, Node 24.21.0, Playwright 1.64.1 / Chromium build 1248): 6/6 check PASS; chạy 4 lần liên tiếp trên cùng HEAD, cả 4 PASS (19–22 s mỗi lần); 6/6 mutation KILLED. Sau review #42 (rev 2): 7/7 test Playwright PASS, test env PASS, thêm 2 mutation KILLED (8/8). Rev 3: khôi phục mật khẩu role, 5 test mới PASS, mutation thứ 9 KILLED (9/9). Evidence CI: chờ CI của PR #39 sau khi PR này vào nhánh.

### 10.2 E3 — P1C-AC-08 (DB mới + hồi quy)

Hai việc giao cho E3 sau review PR #35 đã có trên nhánh tích hợp: API kết nối bằng login native `gpm_api_app` riêng (không `SET ROLE`) và app production mount đầy đủ.

| ID | Kiểm | Kết quả | Evidence |
|---|---|---|---|
| E3-01 | DB mới → bootstrap role → Alembic | PASS | `alembic heads` = `0005_listing_d7`; fixture `migrated_database_with_teardown`; CI dùng `tools/verify_alembic_head.py`, `tools/verify_runtime_roles.py` |
| E3-02 | `pytest backend/tests tests` | PASS | Cluster tạm local; CI run [#42350954394](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42350954394) trên `44579ed`: 1.203 passed. Local trên HEAD này (thêm test E2, test env và test khôi phục role): **1.210 passed, 0 failed, 0 skipped**, gồm cả hai test browser |
| E3-03 | Vitest / typecheck | PASS | Local: 158 passed (10 file), `npm run typecheck` sạch (gồm `e2e/`) |
| E3-04 | Compose smoke, gồm Auth fail-closed trước migrate và 401 chung sau migrate | PASS (CI) | Job `compose` của run trên; local `NOT_RUN` (máy không có Docker) |
| E3-05 | Provisioning dùng chung `normalize_login_name` + `ScryptPasswordHasher` | PASS | `test_local_demo_accounts.py` (insert + login thật, trùng tên không đổi dòng cũ, rollback giữa chừng) |
| E3-06 | Login **thành công** qua cổng Compose | `NOT_RUN` | Smoke chỉ kiểm fail-closed/401; login thành công trên stack thật được E2 kiểm (không qua Docker) |

### 10.3 Runbook: chạy E2 trên máy local

1. Cluster PostgreSQL tạm có marker `db_safety` và các biến `GPU_MARKETPLACE_TEST_DATABASE_URL`, `GPU_MARKETPLACE_ALLOW_DESTRUCTIVE_DB_TESTS=1`, `GPU_MARKETPLACE_TEST_CLUSTER_TOKEN` (giống CI; xem `backend/tests/db_safety.py`). Không trỏ vào DB thật.
2. `npm ci` trong `frontend/`, rồi `npx playwright install chromium`. Muốn để trình duyệt ngoài ổ hệ thống: đặt `PLAYWRIGHT_BROWSERS_PATH` trước cả hai lệnh cài và lệnh chạy test.
3. `uv run --project backend --locked --group dev pytest backend/tests/test_auth_session_browser_e2e.py -rs`.
4. Thiếu biến DB → test `SKIPPED` (`NOT_RUN`), không phải PASS. Thiếu `node_modules` → test FAIL ngay ở bước kiểm tra điều kiện.
5. Config Playwright của test này tắt trace/screenshot/video, vì chúng sẽ lưu mật khẩu test và token lên đĩa.

**Giới hạn còn lại:** C1 (tải/hiệu năng Login với scrypt `N=2^15, r=8, p=3`) vẫn `NOT_RUN / PENDING` theo Option A, là điều kiện trước khi triển khai Auth production, không thuộc mục này.

## Pre-PR Checklist — GPU-003 (chưa xác nhận)

> Checklist phải được chính thành viên phụ trách hoàn thành **trước khi yêu cầu merge** và gắn vào PR. Các ô bên dưới mặc định chưa đánh dấu; tài liệu được duyệt không đồng nghĩa đã hoàn thành các bước.

- [ ] Đã đọc `team-contribution-rules.md`, `change-control.md`, `interphase-change-control.md` và ghi `Mandatory Reading ACK` kèm commit SHA/revision.
- [ ] Đã đọc kiến trúc GPU-003, `docs/design/`/ADR liên quan, và kiểm tra baseline/contract của các Phase phụ thuộc.
- [ ] Đã kiểm tra ownership: chỉ sửa các file đúng trách nhiệm hoặc có xác nhận từ owner của shared file.
- [ ] Đã đánh giá diff Markdown/code: `NO_IMPACT` có lý do hoặc `POTENTIAL_IMPACT` / `CONFIRMED_IMPACT` với Impact Report theo template.
- [ ] Nếu có ảnh hưởng liên Phase, đã thông báo source owner, **từng** affected owner và nhóm trưởng; đã nhận đủ ACK có link thật, xử lý `ACK_WITH_ACTIONS` và không còn `BLOCKED_INTERPHASE`.
- [ ] Nếu thay đổi Requirements/ADR/API Contract/Database Design, đã đi đúng Change Control và nhận quyết định của người có thẩm quyền.
- [ ] Đã chạy các test bắt buộc có thể áp dụng; ghi rõ lệnh, fixture, commit SHA, kết quả và bằng chứng; không ghi PASS cho `NOT_RUN` / `BLOCKED`.
- [ ] Đã cập nhật phase doc, handoff / README cần thiết và kiểm tra Markdown links, bảo đảm status triển khai phản ánh code/PR thật.
- [ ] Đã ghi `Mandatory Reading ACK`, `Inter-Phase Impact`, `Test Evidence` trong PR và yêu cầu **independent human reviewer** theo cấp độ; không tự approve/merge.
