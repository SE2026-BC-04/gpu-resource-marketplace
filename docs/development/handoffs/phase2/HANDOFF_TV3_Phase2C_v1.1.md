# HANDOFF TV3 — Phase 2C: Internal Authentication, Signed Result V1 & Security Integration

**Owner:** TV3 — `@giakhanh-hub` (Auth/Security owner; producer strict V1 parser/verifier).  
**Bản review:** `v1.1 — FINAL-DESIGN-ALIGNED — REVIEWED_FOR_OWNER_APPROVAL`, 2026-11-07.  
**Trạng thái:** `SELF_REVIEWED / AWAITING_CROSS_REVIEW` (2026-11-08, TV3 tự review trên nhánh `docs/phase2c-tv3-design`); sau khi review chéo và lead chốt sẽ là `APPROVED_HANDOFF_CONDITIONAL`, **không phải cho phép code**.  
**Thiết kế nguồn:** `Phase_2C_v0.9.md`, đã chốt `APPROVED_DESIGN_CONDITIONAL`; đối chiếu bốn thiết kế FINAL 2A v0.9, 2B v1.3, 2D v0.9, 2E v1.8. Các bổ sung thiết kế được đánh dấu `PROPOSED_FOR_ACK`, `PENDING_PARAMS` hay `NEEDS_OWNER_DECISION` chưa tự động có hiệu lực. Kết quả tự review và các câu hỏi cần chốt: `Phase_2C_v0.9.md` §6.  
**GitHub snapshot (cập nhật 2026-11-08):** PR [#39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) **đã merge vào `main`** (`aff538f`, source head `3482bce`), gồm cả #42. `main` hiện tại: `bee832eaf5463df20f6c6815174322871eb6685a` (sau #44 nhập 5 thiết kế + 5 handoff Phase 2). Alembic head: `0005_listing_d7`. Gate G0 (mục 8) đã đạt.  
**Phạm vi thay đổi lần này:** chỉ tài liệu (file này và `Phase_2C_v0.9.md`); **không sửa source code, config, database hay secret**. Toàn bộ test Phase 2 `NOT_RUN`.

## 1. Mục tiêu: TV3 phải đạt được điều gì?

TV3 xây dựng và kiểm chứng **ranh giới tin cậy của kết quả mô phỏng**: API phải biết callback có đến từ đúng dịch vụ được phép hay không, và Manager phải biết 11 trường Signed Result V1 có thực sự được ký bằng **khóa Ed25519 công khai đã đăng ký của đúng Worker** hay không. Quy tắc này không đồng nghĩa chữ ký chứng minh công việc GPU đã diễn ra, cũng không đồng nghĩa claim đúng oracle.

**Năm kết quả bắt buộc sau khi code được cấp phép, triển khai và kiểm thử:**

1. **Cách ly danh tính:** JWT HS256 của Client/Worker/Admin và hai Bearer nội bộ là ba mục đích riêng; chỉ đúng token **Simulator → API** mới được gọi callback; chỉ đúng token **Manager → Simulator** mới được dispatch. Mất/misconfigure secret phải fail closed, không dùng JWT của người dùng làm service-token.
2. **Chuẩn byte không đổi:** Signed Result V1 đúng 11 trường, UTF-8 RFC 8785 JCS, prefix `GPU-MARKETPLACE:SIGNED-RESULT:V1\n`, Ed25519 64 byte, Base64url unpadded. Parser từ chối duplicate JSON member, extra/missing field, sai UUIDv4/timestamp/enum/digest/signature encoding. Không tự làm lại ADR-004.
3. **Callback bền vững nhưng chưa mặc định đáng tin:** API xác thực dịch vụ và kiểm schema trước, gọi **TV2 Inbox adapter** lưu raw HTTP envelope và `received_at` DB; `202` chỉ sau commit. Manager mới kiểm cryptographic signature và context; signature sai nhưng schema hợp lệ vẫn có thể nhận `202 STORED` rồi bị REJECTED sau đó.
4. **Verifier độc lập, bàn giao an toàn:** TV3 trả `VerifiedV1Receipt | RejectedV1Receipt` bất biến, có provenance tới raw Inbox/key; TV1 gọi nó, TV5/TV2 kiểm tra lại evidence và trạng thái Job/Attempt dưới khóa đúng thứ tự trước một lần Finalization. TV3 **không** quyết định outcome thật, giải phóng GPU hoặc thay đổi Reputation.
5. **Quản trị khóa tin cậy:** TV2 đăng ký/lưu public key, TV5 giữ private signer key trong Simulator, TV3 thiết kế và test key-binding/historical verify; planned K1→K2 chỉ sau khi Worker hết RUNNING theo cơ chế có khóa. Nghi lộ khóa là **sự cố riêng**, chưa có policy owner; không xử lý bằng giả định rotation bình thường.

**Định nghĩa hoàn thành:** có source/test sau khi được duyệt; fixed vector ADR-004, test âm tính và cross-runtime; callback E2E dùng hai login PostgreSQL native, key-retention/rotation, race/deadline; ACK theo SHA của producer và consumer; độc lập human review. Không coi `P2C-GATE-01` là bằng chứng code PASS.

## 2. Ranh giới sở hữu: TV3 không làm thay TV2 hay TV5

| Công đoạn | TV3 chịu trách nhiệm | Owner khác và ranh giới bắt buộc |
|---|---|---|
| Manager → Simulator | Ma trận token purpose, quy định từ chối token sai, negative-test/security review | TV1 dispatch client; TV5 Simulator endpoint/runtime và callback sender |
| Simulator → API | Auth callback dependency, strict HTTP JSON V1 validation, status/error/security tests, tích hợp route theo wiring TV1 | TV2 UoW/Inbox INSERT, raw-byte dedup, DB clock, grants; TV1 API lifecycle/Compose integration |
| Verification | Pure canonicalization/JCS/Ed25519 verifier; chuẩn kiểu typed success/reject; kiểm signer/claim với context tin cậy do caller cung cấp | TV2 public-key read+Job/Attempt context; TV1 orchestrates; TV5 Finalizer rechecks |
| Key registration/rotation | Chốt security policy, lựa chọn K1/K2 đúng ngữ cảnh, regression historical verifier | TV2 SQL/ACL/lock/provisioning; TV5 private signer key và restart; TV4 readiness trước allocation; TV1 runtime coordination |
| Finalization & Reputation | Chỉ đưa ra bằng chứng xác minh/loại từ chối không chứa secret | **TV5** chính sách signed outcome → terminal/reputation; **TV2** transaction atomic; TV1 gọi |
| Ground truth Dispute | Phân biệt claim có chữ ký với sự thật | Không so sánh `simulation_references` để bác claim trong verifier; Phase 3 Dispute mới phân xử |

**Không làm:** không viết SQL transaction thay TV2, không tự chuyển Job `RUNNING → COMPLETED/FAILED`, không cập nhật GPU/Reputation, không tạo bảng thứ bảy hay một service thứ sáu; không đưa private key vào PostgreSQL, không làm auth refresh token, không tự nâng `gpm_api_app` quyền đọc raw Inbox, không đổi Signed Result V1 để chạy test dễ hơn.

## 3. Những file phải đọc TRƯỚC khi làm

### 3.1. Năm bản Phase 2 FINAL đã được nhóm trưởng chốt có điều kiện

| Thứ tự | File | TV3 cần đọc gì? |
|---|---|---|
| 1 | `Phase_2C_v0.9.md` | Toàn bộ: `P2C-DEC-01`, `P2C-OPEN-02/03/04`, `C-IF-01..11`, DR-C, acceptance và 18 test DRT |
| 2 | `Phase_2B_v1.3.md` | `result_inbox`, `worker_public_keys`, immutable bytes, TV2 UoW/ACL, duplicate UNIQUE, Listing→Job locks |
| 3 | `Phase_2E_v1.8.md` | TV5 output schema 9 trường khác Signed Result 11 trường; signing, restart cache, Finalizer recheck, reputation-once |
| 4 | `Phase_2A_v0.9.md` | API callback mount, Manager verification loop, bounded executor, crash/restart/startup preflight |
| 5 | `Phase_2D_v0.9.md` | Scheduler, Worker key readiness, planned rotation vs new allocation; erratum `reserved_gpu_count` không phải cột thật |

**SHA256 của năm file chuẩn được sử dụng trong review này:**

| File | SHA256 |
|---|---|
| `Phase_2A_v0.9.md` | `2168e036203c1370b56c2ffe7e5633d398266f72423a370254df33273f7162a2` |
| `Phase_2B_v1.3.md` | `27c59f3e2eddc2584fc9c904aacfc7d45aa323b8745ec77eb5775d59b1af3371` |
| `Phase_2C_v0.9.md` | `d92901a412aaaaa3a2e601781b3991019de9eeee1f45b891564a64d3fbd33902` |
| `Phase_2D_v0.9.md` | `fdb7f79a1b89b9ed911fddce67da1763ea88a5417ab946a3121f8701f8758c60` |
| `Phase_2E_v1.8.md` | `90af557a46a0f7bcb663eb9d17de3a2db866c4c0b2f1e5006a9160eed2d6609f` |

Các SHA256 trên là của bản trên `main@bee832e` **trước** lần tự review 2026-11-08; `Phase_2C_v0.9.md` sửa trong nhánh docs sẽ có SHA mới, ghi trong PR docs. Tài liệu các Phase có một số mốc GitHub HEAD *lịch sử*. Khi có xung đột giữa status trong bản cũ và quyết định đã được owner chốt sau đó, dùng sổ phê duyệt cuối; nhưng `PENDING_ACK/NOT_RUN` vẫn giữ nguyên.

### 3.2. Các nguồn chuẩn trong GitHub

- `docs/architecture/decisions/ADR-003-internal-communication.md`: Outbox/Inbox, business effect once-only, không phải exactly-once network.
- `docs/architecture/decisions/ADR-004-signed-result.md`: **nguồn bất biến** về V1, signature JCS, public vector, `WIRE-*`, `SIG-*`.
- `docs/architecture/decisions/ADR-005-retry-timeout-internal-auth.md`: hai purpose Bearer ≥256 bits random; timeout, hard deadline và retry classification.
- `docs/design/api-contract.md` §13: dispatch/callback route, body và `202 STORED/DUPLICATE`, `409 RESULT_ID_COLLISION`, `422 INVALID_SIGNED_ENVELOPE`, `401`, `404`.
- `docs/design/database-design.md` §§9/11: `(worker_id,key_id)`, `result_inbox`, `signed_results`, trusted `received_at` và thứ tự khóa.
- `docs/design/test-design.md`: test truthfulness/evidence template và phương pháp hai commit order.
- `backend/src/gpu_marketplace/api/app.py`, `backend/src/gpu_marketplace/common/config.py`: Phase1 API hiện mount **Auth/Listings/Jobs** và 3 secret JWT/cursor; **chưa có callback token/route Phase2** ở HEAD kiểm tra.
- `simulator/src/gpu_marketplace_simulator/{app,config}.py`: Phase1 chỉ có health/ready; **chưa có dispatch/signing endpoint**; TV5 sẽ sở hữu runtime.
- `backend/src/gpu_marketplace/manager/service.py`: Phase1 Manager là **idle loop**, chưa có verification/finalization loop.
- `backend/migrations/versions/0001_phase1b_baseline.py`: `worker_public_keys` đã có trong 10 bảng Phase1; TV3 không tạo lại.
- `backend/tests/{test_api_auth_mount,test_auth_http_postgres,test_api_cors,test_auth_session_browser_e2e}.py`: regression Phase1 Auth, **không thay thế callback/Ed25519 tests**.

**Trạng thái nền (cập nhật 2026-11-08):** PR #39 đã merge vào `main` (`aff538f`), gồm #42; `main` hiện tại `bee832e`. Các mô tả code Phase 1 ở trên (app.py, simulator, manager idle loop) vẫn đúng trên `main` này. CI Phase1 xanh không biến `P2C-DRT-*` thành PASS.

## 4. Các bất biến bảo mật không được thay

### 4.1. Hợp đồng Signed Result V1 (ADR-004)

- **11 trường ký (thứ tự liệt kê không phải thứ tự byte; JCS chuẩn hóa key):** `schema_version`, `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `outcome`, `failure_reason`, `result_digest`, `finished_at`, `key_id`.
- `schema_version` là chuỗi **`"1"`**, còn `schema_version` trong **output mô phỏng của TV5** là `"demo-v1"` (không thay chúng cho nhau).
- V1 signing bytes = `UTF8("GPU-MARKETPLACE:SIGNED-RESULT:V1\n") || UTF8(JCS_RFC8785(payload))` với chính xác một LF (`0x0A`) trước canonical payload. Chữ ký Ed25519 dài **64 raw bytes**, outer `signature` Base64url **86 ký tự**, không padding `=`, `signature_encoding="base64url-no-padding"`.
- `result_id/job_id/attempt_id/worker_id/listing_id/key_id` = UUIDv4 lowercase canonical; `finished_at` đúng `YYYY-MM-DDTHH:mm:ss.ffffffZ`; `result_digest` đúng `sha256:` + 64 chữ hex lowercase.
- `SUCCESS` ↔ `failure_reason=null`; `FAILED` ↔ `WORKER_FAULT` hoặc `JOB_FAULT`; signed `SYSTEM_FAULT` là bất hợp lệ. Unregistered/retired-public-key-only restriction không được tự làm hỏng khả năng verify lịch sử K1.
- Reject JSON duplicate keys ở **cả outer envelope và payload**, unexpected fields, NaN, Infinity, unsupported numeric primitives, invalid UTF-8/I-JSON/JCS, timestamp không có 6 số thập phân hoặc signature encoding sai.
- Không dùng `json.dumps(sort_keys=True)` làm thay thế tổng quát cho RFC8785 JCS; với profile ASCII rất hẹp có thể trùng bytes, **nhưng verifier V1 phải có kiểm thử độc lập cả Unicode/JSON boundary**.
- Public key trust anchor là **byte 32** từ DB registry `(worker_id,key_id)` (TV2 adapter), không lấy từ callback. Valid signature xác nhận **signed claim**, **không chứng minh oracle đúng** và không được tự viết/đọc `simulation_references` để đánh giá truthfulness.

### 4.2. Callback `POST /internal/v1/results/callback`

1. Kiểm tra phương thức, Content-Type JSON/UTF-8, **service Bearer đúng purpose** trước DB read/write hoặc bất kỳ ACK chấp nhận nào; end-user HS256 JWT và `MANAGER_DISPATCH_TOKEN` bị từ chối `401`. Không dùng CORS làm quyền truy cập.
2. Strict parse **bounded raw bytes** (size/depth numerical budget = `PENDING_PARAMS` TV1/TV3/TV5), reject key trùng trong JSON, extra/missing keys/invalid wire; giữ raw body chính xác, không chỉ giữ `jsonb` rồi serialize lại.
3. Phân biệt **wire/schema gate** với **cryptographic gate**. Malformed envelope → `422 INVALID_SIGNED_ENVELOPE`, không có eligible Inbox. Envelope schema hợp lệ nhưng signature Ed25519 sai → **có thể** `202 STORED` sau commit, rồi Manager/TV3 verifier đánh dấu candidate `REJECTED`; tuyệt đối không `422` tại ingress chỉ vì signature sai khi API không phải verifier.
4. TV2 adapter là owner `TX-INBOX-INGRESS`: duplicate retained same `result_id`/same full original bytes → `202 DUPLICATE`, **kể cả Job đã terminal**, không thay `received_at`; cùng ID khác 1 byte (kể cả JSON whitespace/order) → `409 RESULT_ID_COLLISION`. Trường hợp race hai request, UNIQUE loser rollback và đọc lại committed winner, không nhờ RAM cache; callback-context binding không được rò dữ liệu người khác.
5. Candidate mới: DB bắt Listing → Job lock, kiểm RUNNING và Attempt thực, lấy `received_at=clock_timestamp()` **sau Job lock**, yêu cầu `< hard_deadline_at`. Đúng giờ `== deadline` bị từ chối `409 RESULT_NOT_ACCEPTABLE`. Không backdate theo `finished_at` của Worker.
6. `202 STORED` chỉ sau **COMMIT đã xác nhận**. Nếu connection/COMMIT outcome unknown, không nói đã lưu; sender TV5 retry cùng bytes/ID để reconciliation theo unique result; 5xx/503 không phải bằng chứng chưa commit. Không lưu PENDING với unbound/unknown context.
7. Local Compose API callback dùng **existing listener**, có thể truy cập từ tiến trình trên host loopback; không gọi nó network-private chỉ vì path `/internal`. Cần Bearer, safe ingress, no public frontend route. Nếu expose non-loopback/untrusted, cần review ingress/TLS/mTLS trước deployment, **không tự tạo listener/service mới**.

### 4.3. Verification → Finalization: tách quyền

```text
TV5 Simulator signs exact V1 envelope (private key only in Simulator)
  -> TV3 Callback service auth + strict schema parsing (API)
  -> TV2 Inbox TX: raw bytes + immutable received_at + durable commit
  -> HTTP 202 STORED (not signature acceptance)
  -> TV1 Manager loads committed candidate
  -> TV2 trusted public key and Job/Attempt/Listing context
  -> TV3 pure V1 JCS+Ed25519 verification
  -> VerifiedV1Receipt | RejectedV1Receipt (proposal, no DB side effect)
  -> TV5 Finalizer policy through TV2 TX-FINALIZE (re-read under locks)
  -> one terminal Job + one GPU release + eligible Reputation effect
```

**Typed contract `C-IF-06` is PROPOSED_FOR_ACK**, not a frozen Python public API:

```text
VerifiedV1Receipt(
  inbox_row_id, envelope_sha256, result_id, job_id, attempt_id,
  worker_id, listing_id, key_id, outcome, failure_reason,
  result_digest, signed_schema_version='1', signed_payload_fingerprint
)
RejectedV1Receipt(inbox_row_id, rejection_code)
```

- Chỉ immutable typed data/provenance, **không chứa** SQLAlchemy Session, private keys, JWT, nguyên protected reference hay Boolean `verified=true` do JSON/HTTP tự cung cấp.
- Re-verify/compare trusted bytes, signer and Job/Attempt state **trong finalizer UoW** theo Listing→Job→Allocation→Inbox; không truyền locked ORM object giữa transaction/thread; tránh TOCTOU. Mọi V1 context mismatch đều `REJECTED` không làm Job terminal lập tức.
- Inbox nhiều `result_id` của cùng Attempt phải duyệt theo `(received_at,result_inbox.id)` và chấp nhận **candidate hợp lệ đầu tiên**. Candidate invalid → REJECTED, tiếp tục candidate sau. Trước `SYSTEM_FAULT` phải duyệt **hết** on-time Inbox (kể cả multi-batch) sau khi khóa Listing/Job. Không dùng signed `finished_at` làm authoritative time. Nonwinner state cần **TV1/TV2/TV3/TV5 ACK**.

### 4.4. Keys và các quyết định chưa đóng

- TV3 xác nhận security binding; TV2 đăng ký đúng một active public key/Worker theo schema; TV5 nạp private signer key qua secret không track, chứng minh sống qua restart và khớp với public key. Không ghi private key trong DB hoặc commit repository.
- Planned K1→K2: **quiescent rotation** đã duyệt ở mức thiết kế, **không** retire active K1 khi Worker có RUNNING Attempt; lock/serialise với TX-ALLOCATE (TV2/TV4), drain, đổi key có kiểm soát, giữ K1 historical để verify retained receipts sau rotation; no key deletion khi FK còn tham chiếu.
- Khi **nghi private key bị lộ**, không tiếp tục sử dụng/rotate theo planned path. Fail closed với new use, escalate owner incident policy. Cách disposition kết quả ký trước đó, RUNNING và historical evidence là `NEEDS_OWNER_DECISION`; **không** tự giả định key revoked = invalid historical signatures.
- `P2E-CACHE-GAP-01`: Simulator cache RAM không chứng minh `409 EXECUTION_CONFLICT` sau cold restart cùng Attempt/different immutable dispatch. TV3 cần tham gia threat analysis, nhưng **TV5/TV1/lead** sở hữu quyết định design; không tự mở DB access cho Simulator hoặc sửa request V1.

## 5. Nhiệm vụ TV3 — 6 chuẩn bị và 11 triển khai

### A. Giai đoạn 1 (hoàn thiện kiến trúc): 6 việc ở mức tài liệu

Theo thông báo quy trình 2026-11-08, kết quả của 6 việc dưới đây đi vào **PR docs** từ nhánh `docs/phase2c-tv3-design` để review chéo, không còn là tài liệu chỉ để trên máy. Lần tự review đầu ghi trong `Phase_2C_v0.9.md` §6; các artefact tên riêng trong cột "Đầu ra" có thể là mục trong §6 hoặc file riêng, tùy lead chốt.

| ID | Việc phải thực hiện chi tiết | Đầu ra / người cần ACK |
|---|---|---|
| **TV3-P2C-01** | **Đóng băng nguồn V1 và baseline.** Đọc ADR-004 frozen vector, đếm đúng 11 fields, UTF-8/JCS, signature encoding, enum; so với `Phase_2C_v0.9.md` và TV5 draft. Chốt trạng thái #39 sau merge main, phase1 JWT code, không copy false assumptions từ `44579ed`. | `SIGNED_V1_CONTRACT_CHECKLIST.md` + danh sách fixture WIRE/SIG, source SHA + baseline; TV1/TV5 ACK |
| **TV3-P2C-02** | **Lập ma trận auth/threat-model.** Có 3 token purposes (user JWT, dispatch Bearer, callback Bearer); test wrong-direction, missing, bytes leak, invalid header/malformed, local-host listener exposure và host-vs-internal networking. Không quyết định TLS topology mới khi chưa duyệt. | `INTERNAL_AUTH_MATRIX.md`, `THREAT_MODEL_CALLBACK.md`, redaction rule; TV1/TV5 ACK |
| **TV3-P2C-03** | **Freeze HTTP callback + strict parser contract.** Chốt method/path, content-type/UTF8, `body_size_max`, JSON depth, duplicate members/unknown fields, `401/404/409/422/202`, original raw byte ownership; phân biệt parse 422 với sig-invalid-then-202; 202 only after committed Inbox. | `CALLBACK_HTTP_CONTRACT.md`, `WIRE_BOUND_PARAMS.md`; TV1/TV2/TV5 ACK |
| **TV3-P2C-04** | **Freeze Verifier → Finalizer typed port.** Chọn immutable fields/evidence fingerprint, signer read context, `Rejected` error-code enum, concurrency/stale evidence behavior; xác định ai re-read under locks; chính sách multiple-result_id, nonwinner Inbox state và all-on-time scan. Không giao TV3 commit. | `VERIFIED_RECEIPT_PORT.md`, error matrix, anti-TOCTOU recipe; TV1/TV2/TV5 ACK |
| **TV3-P2C-05** | **Freeze key provisioning/rotation/incident gating.** TV5 private key origin/restore, TV2 public key registration, TV4 readiness/allocation guard, TV1 startup & rotation orchestrator; phân biệt planned K1→K2 với suspect compromise. Đề xuất incident options cho lead, không tự duyệt. | `SIGNER_KEY_LIFECYCLE.md`, incident decision request, historical K1 test cases; TV1/TV2/TV4/TV5 ACK và owner decision riêng khi cần |
| **TV3-P2C-06** | **Lập verification/test matrix và kế hoạch nhánh.** Map `P2C-ACC-01..09`, `P2C-DRT-01..18`, `WIRE/SIG/API-INT/COM` vào case/fixture/owner; lập danh sách dependency PostgreSQL/Compose, explicit coding gate, kế hoạch chia task (một task = một nhánh = một PR), hash/CI fields và phân loại skipped/blocked. | `TV3_PHASE2_TEST_MATRIX.md`, `TV3_INTERFACE_ACK.md`, `TV3_CODING_GATE.md`; TV1 approve coding gate riêng |

**Đầu ra PRE_CODE bắt buộc:** 6 artefact hoặc nhóm artefact bên trên; không cần tạo nhánh/PR code để gọi là hoàn tất. Review của TV1 và từng owner consumer phải ghi **cụ thể phiên bản/SHA**, không dùng 'đã xem' chung chung.

### B. Sau khi được nhóm trưởng cấp quyền code: 11 việc triển khai kỹ thuật

| ID | TV3 phải lập trình/kiểm thử chi tiết | Đầu ra và PASS oracle |
|---|---|---|
| **TV3-P2C-07** | **Strict V1 wire parser:** parse raw UTF-8 JSON, chặn member trùng ở hai tầng, nested/value/type errors, enforce đúng 3 outer fields + đúng 11 signed fields + size/depth limits đã ACK; strict UUIDv4/UTC µs/enum/digest/Base64url 86-char. Trả error typed, no secrets. | Parser module/fixture: malformed ⇒ `422` trước Inbox; schema-valid but invalid Ed25519 **không bị parser tự loại vì chữ ký toán học**. |
| **TV3-P2C-08** | **Pure RFC8785-JCS/Ed25519 verifier:** dùng thư viện chuẩn, rebuild prefix+canonical bytes, nhận public key 32 bytes qua tham số trusted do TV1/TV2 reader cấp, verify bằng Ed25519 mà không tự query DB và signature 64 bytes; không đọc DB trực tiếp/Session ngầm; không phỏng đoán oracle. | Frozen ADR-004 public vector PASS trong backend + Simulator TV5; changed byte/prefix/key/encoding FAIL; Unicode boundary được kiểm thử. |
| **TV3-P2C-09** | **Purpose-scoped service-token dependency:** kiểm token callback bằng random CSPRNG secret ≥256 bits, compare constant-time nơi có thể, fail closed nếu unset/invalid, reject user JWT/dispatch token; cung cấp reusable **contract/test fixtures** để TV5 guard dispatch (TV5 owner endpoint). | API-only dependency/config tests: correct token allowed; wrong direction/legacy JWT 401; no DB write/secret in logs. |
| **TV3-P2C-10** | **Callback route handler** `/internal/v1/results/callback` trên existing API listener: preserve raw `request.body()`, auth + strict parsing + typed error mapping; phối hợp TV1 mount vào `create_app`/startup, không tạo listener thứ hai. | Real FastAPI HTTP tests cho `202 STORED`, `202 DUPLICATE`, 401/404/409/422 và redaction; no premature Job terminalization. |
| **TV3-P2C-11** | **Gọi TV2 Inbox port, không tự viết SQL:** với claimed Job/Attempt context và exact raw bytes, nhận typed result `STORED/DUPLICATE/COLLISION/NOT_ACCEPTABLE/NOT_FOUND/UNAVAILABLE`; `202` chỉ sau confirmed commit, unknown COMMIT không false ACK; test unique collision concurrency do TV2 cung cấp. | API maps DB outcomes to exact API Contract; a schema-valid bad-signature callback stores a candidate but no accepted signed_results. |
| **TV3-P2C-12** | **Context/key validation:** đối chiếu Worker/Listing/Job/Attempt với trusted DB rows, `worker_public_keys(worker_id,key_id)` từ TV2; respect archived K1 key for historical proof, unknown/mismatched keys fail closed. | Negative test signed but wrong `worker_id/listing_id/attempt_id/key_id`: rejected typed, 0 business mutation. |
| **TV3-P2C-13** | **Immutable typed verification output** `VerifiedV1Receipt/RejectedV1Receipt`: include raw Inbox ID/hash, canonical signed-payload fingerprint, V1 fields and stable redacted reason; TV1 Manager reads it, TV5 Finalizer re-reads under Listing→Job locks. | Shared port contract tests + direct integration, no boolean spoof, no Session transfer, no TV3 business write. |
| **TV3-P2C-14** | **Security verification for key lifecycle:** test K1→K2 planned rotate with TV2/TV5, historical K1 retained while FK in use, missing-key fail-closed and cold Simulator restart reloading private signer; inspect rotation/allocation race with TV4. | `P2C-KEY-*`, `P2C-DRT-11/12/14` evidence; emergency compromise only fail-closed/escalation until owner policy. |
| **TV3-P2C-15** | **Negative security suite:** malformed JSON/duplicate keys/invalid I-JSON and huge payload, wrong-direction token, impersonation, replay/collision, signature tampering, forged key, logs/headers, client-facing route exposure. | Test matrix covers accepted design `WIRE/SIG/API-INT/P2C-*`, each result has SHA/fixture/oracle; no leaked private key, token or oracle. |
| **TV3-P2C-16** | **Cross-owner PG/HTTP concurrency & crash tests:** cùng TV2/TV5 ép hai callback same-ID đến đồng thời; deadline exact µs, post-terminal duplicate, two `result_id`, Manager crash before/after finalization, invalid-first-valid-later across multiple batches. | Real restricted-role PostgreSQL + HTTP + Docker Compose/Simulator E2E; guaranteed 1 signed result/Job, one release/reputation; evidence both lock/commit orders. TV3 chỉ owner security assertions, TV2/TV5 owner DB/business fixtures. |
| **TV3-P2C-17** | **Review/handoff theo từng PR:** mỗi task 07–16 là một nhánh và một PR riêng vào `main`; PR cuối tổng hợp delivery report, cập nhật module docs/trace, chạy relevant unit/PG/Compose CI, kiểm secret scanning, ghi exact HEAD SHA và giao TV1, TV2, TV5, TV4 phần key readiness. | `TV3_DELIVERY_REPORT.md`, CI links, `P2C-ACC` results, signed config checklist, producer+consumer ACK, independent human review before merge. |

**Thứ tự phụ thuộc đề xuất:** `07,08` có thể bắt đầu sau coding gate và contract V1; `09,10,11` cần TV1 route wiring + TV2 Inbox port; `12,13` cần TV2 trusted key/context read + TV5 Finalizer type ACK; `14,16` cần TV4/TV5 runnable runtime và PostgreSQL. Không vượt qua interface gate bằng cách dùng fake repository làm bằng chứng PG pass.

## 6. Mười một interface cần ký ACK đúng SHA (`C-IF-01..11`)

| Interface | Phải freeze trước phần code phụ thuộc | Producer → consumer / người ACK | Status |
|---|---|---|---|
| `C-IF-01` | Manager dispatch token vs Simulator callback token vs JWT, startup failure semantics | TV3 security + TV1 runtime + TV5 simulator | `PENDING_ACK` |
| `C-IF-02` | Callback HTTP route, size/depth, strict JSON, 202/401/404/409/422, raw error/log redaction | TV3 API handler + TV1 app wiring + TV5 sender | `PENDING_ACK/PARAMS` |
| `C-IF-03` | Inbox exact original raw compare, same-ID collision, SELECT ACL and unknown COMMIT | TV2 DB producer + TV3 HTTP/TV5 client | `PENDING_ACK` |
| `C-IF-04` | `received_at` clock after Listing/Job lock, duplicate post-terminal, exact deadline | TV2 UoW + TV3 ingress + TV1 fallback | `PENDING_ACK` |
| `C-IF-05` | Trusted `(worker_id,key_id)` lookup, RFC8785+Ed25519 fixed bytes, signer semantic | TV2 key read + TV3 verifier + TV5 signer | `PENDING_ACK` |
| `C-IF-06` | `VerifiedV1Receipt/RejectedV1Receipt` fields, provenance, stale recheck, stable rejection reasons | TV3 producer + TV1 caller + TV2 UoW + TV5 finalizer | `PENDING_ACK` |
| `C-IF-07` | One active Worker key, private/public registration, secret delivery and cold-restart recovery | TV3 security + TV2 public key + TV5 private key + TV1 startup | `PENDING_ACK` |
| `C-IF-08` | Planned K1→K2 quiescent rotation vs allocation/resume | TV3 policy + TV2 transaction + TV4 FIFO + TV5 signer + TV1 coordination | `PENDING_ACK` |
| `C-IF-09` | Emergency key compromise classification: new use stops, retained evidence/running job disposition | TV3/TV5 + TV1 lead decision | `NEEDS_OWNER_DECISION` |
| `C-IF-10` | Distinct `result_id`/attempt, ordered candidates, multi-batch on-time before fallback, nonwinner state | TV2 Inbox + TV3 verifier + TV5 finalizer + TV1 Manager | `PENDING_ACK` |
| `C-IF-11` | Phase1 merged base, native runtime roles/grants, #42 impact, code authorization | TV1 group lead + TV2 DB + TV3 security | `PENDING_BASELINE/CODING_GATE` |

**Mẫu ACK mỗi owner:** `Producer/consumer; design file+SHA; port methods/params/return/status/error; test IDs and evidence; code SHA; ACK_COMPATIBLE|ACK_WITH_ACTIONS|BLOCK; reviewer link`. Không chấp nhận 'đã thấy/CI xanh' chung chung. Trước khi thay đổi chuẩn ADR đã chốt phải review owner + downstream affected-owner theo đúng interphase change control.

## 7. Các bài kiểm thử bắt buộc và tiêu chí PASS

**Những ID dưới đây là đề xuất thiết kế đã được review, không phải test đã chạy.** Với mỗi test ghi `Git SHA`, DB migration revision, fixture/setup seed, thời gian/clock setup, exact stimulus, observed HTTP/DB values, oracle, PASS/FAIL/BLOCKED/NOT_RUN và CI URL; không dùng CI Phase1 giả làm Phase2.

| ID | Bài thử | Chứng cứ PASS bắt buộc | Owner phối hợp |
|---|---|---|---|
| `P2C-DRT-01` | callback đúng Bearer / missing / JWT / opposite token | Chỉ callback Bearer đúng mới có write; others 401/no DB effect | TV3/TV1/TV5 |
| `P2C-DRT-02` | duplicate/extra/malformed JSON, invalid UUID/time/I-JSON | Mọi bad envelope 422, không có PENDING eligible | TV3 |
| `P2C-DRT-03` | frozen ADR-004 Ed25519 vector giữa two runtimes | Same JCS/prefix bytes; valid verify PASS, tamper FAIL | TV3/TV5 |
| `P2C-DRT-04` | exact same raw result_id after terminal | 202 DUPLICATE; 1 row, original received_at unchanged | TV2/TV3 |
| `P2C-DRT-05` | same ID but raw whitespace/order changed | 409 COLLISION, original bytes intact | TV2/TV3 |
| `P2C-DRT-06` | concurrent duplicate/collision two DB sessions | UNIQUE winner; loser rollback/re-read; no new row | TV2/TV3 |
| `P2C-DRT-07` | callback COMMIT completed but HTTP ACK lost | retry exact bytes/id returns duplicate, no false ack | TV2/TV3/TV5 |
| `P2C-DRT-08` | wrong Ed25519 signature, schema otherwise valid | 202 STORED; Manager REJECTED; 0 terminal/reputation | TV3/TV2/TV5 |
| `P2C-DRT-09` | signed wrong worker/listing/job/attempt/key | Context reject and 0 accepted Signed Result | TV3/TV2 |
| `P2C-DRT-10` | ingress deadline-1us vs deadline exact; delayed process | On-time eligible; exact cutoff rejected; no false SYSTEM_FAULT | TV2/TV3/TV1 |
| `P2C-DRT-11` | K1 archived, K2 active, held signed evidence | Historical K1 verify; FK RESTRICT prevents needed deletion | TV2/TV3/TV5 |
| `P2C-DRT-12` | rotation/allocation race and Simulator restart | No stale mismatched signer; safe serialization/secret reload | TV2/TV3/TV4/TV5 |
| `P2C-DRT-13` | two distinct result IDs same Attempt | First valid ordered candidate effect once, nonwinner no effect | TV1/TV2/TV3/TV5 |
| `P2C-DRT-14` | missing/compromised key, absent token, ingress exposure | Fail closed, no secret leak; incident remains decision-gated | TV1/TV3/TV5 |
| `P2C-DRT-15` | correctly signed but mismatches protected oracle | TV3 reports valid claim, does not adjudicate truth or reputation | TV3/TV5 |
| `P2C-DRT-16` | oversized/nested body, multi-batch on-time backlog | Resource bound; no hidden valid receipt skipped before fallback | TV1/TV2/TV3 |
| `P2C-DRT-17` | actual native API/Manager PostgreSQL logins, Simulator isolation | Least privilege; no Simulator SQL identity; no read oracle | TV2/TV3/TV5 |
| `P2C-DRT-18` | crash before/after finalize COMMIT, retry same/different ID | Exactly one accepted result/release/eligible contribution | TV1/TV2/TV3/TV5 |

**Tình trạng:** toàn bộ `P2C-DRT-01..18 = NOT_RUN`, các `P2C-ACC-01..09` chưa có evidence runtime; test vector authoring/self-check trong ADR không phải product PASS. Native-DB/Compose/cross-runtime crash tests phải dùng DB **disposable có safety marker và teardown cluster-wide credentials**; trên `main`, `backend/tests/test_phase1_runtime_http_postgres_e2e.py` đã bọc `bootstrap_roles(..., rotate_password=True)` bằng fixture `restored_e2e_role_credentials` (dùng `role_credentials.restored_login_role_credentials` từ #42); test Phase 2 nào đổi mật khẩu role phải dùng lại helper này.

## 8. Công việc nhóm trưởng phải chốt để TV3 không bị kẹt

| Gate/decision | Trạng thái cần làm rõ | Owner |
|---|---|---|
| `G0` | **Đã đạt 2026-11-08:** PR #39 merge vào `main` (`aff538f`); base hiện tại `main@bee832e`, Alembic head `0005_listing_d7`; roles theo `0002_phase1b_grants` | TV1 (đã merge) |
| `G1` | `C-IF-01..11` có source+consumer ACK, size/depth budgets, key bootstrap và typed verifier fields được freeze | TV1 + TV2/TV3/TV4/TV5 |
| `G1-INCIDENT` | Key compromise incident policy đối với new signing, pending Inbox, RUNNING, retained signatures | Lead L2 security decision; chưa được phê duyệt |
| `G1-CACHE` | `P2E-CACHE-GAP-01` dispatch conflict after cold restart: enforce via valid owner-approved design or L2 change-control | TV5+TV1+TV3, chưa được phê duyệt |
| `G2` | Theo thông báo 2026-11-08: code chỉ bắt đầu sau khi PR docs Phase 2C được review chéo, lead chốt và merge; sau đó từng task code có nhánh/PR riêng, phụ thuộc của task phải đã ACK. Lead xác nhận thông báo này có thay cho bản ghi G2 riêng hay không | TV1 |
| `G3` | Phân phối test Docker/PG; không rotate password ở shared/persistent DB; native role proofs; signed vector + HTTP + crash barriers | TV2+TV3+TV5 |
| `G4` | Independent human review, impacted owner ACKs tại exact SHA, CI Phase2 PASS; xét merge riêng | TV1 + TV2/TV3/TV4/TV5 |

**Không đổi** số giây ADR-005 (Outbox scan 2s, lease 30s, callback/dispatch backoff 2/4/8/16/30, hard deadline `finish_due_at+120s`), không tự mở rộng Phase1 `/health/ready` (CR L2 chưa quyết), không thêm JWT refresh hay key-management service.

## 9. Checklist bàn giao và file giao người dùng cuối

- [ ] `SIGNED_V1_CONTRACT_CHECKLIST.md` có frozen 11 fields, vector và ADR-004 SHA.
- [ ] `INTERNAL_AUTH_MATRIX.md` và `THREAT_MODEL_CALLBACK.md` có token purpose, local loopback ingress, redaction, incident escalation.
- [ ] `CALLBACK_HTTP_CONTRACT.md` và `WIRE_BOUND_PARAMS.md` được TV1/TV2/TV5 ACK.
- [ ] `VERIFIED_RECEIPT_PORT.md` với immutable fields, error enum, anti-TOCTOU proof được TV1/TV2/TV5 ACK.
- [ ] `SIGNER_KEY_LIFECYCLE.md` + plan K1/K2; private-key provisioning TV5 và registered public key TV2 đã có đường kỹ thuật; incident vẫn `NEEDS_OWNER_DECISION` nếu chưa chốt.
- [ ] `TV3_PHASE2_TEST_MATRIX.md` cho 18 case, đúng status và fixture.
- [ ] Khi code được duyệt: parser, JCS/Ed25519, callback dependency/route, typed verifier, suite negative, integrated PG/HTTP/Compose và exact evidence.
- [ ] `TV3_DELIVERY_REPORT.md` có Git HEAD/base, schema revision, CI links, từng test verdict, raw evidence digests (không có secret), ACK và reviewer độc lập.

```text
[TV3 Phase2C delivery]
Design: Phase2C v0.9 SHA256 / exact source docs:
Git branch/PR, reviewed HEAD SHA, base main SHA, migration revision:
Pre-code ACK: C-IF-01..11, owner decision refs (incident, cache conflict):
API callback/token auth/status matrix + request bounds:
Verifier types / signed V1 vector IDs / retained key registry:
Parser/Ed25519 test IDs and verdicts:
PostgreSQL races/COMMIT recovery/cold restart results:
Protected oracle/secret/SQL credential leakage checks:
Full CI URLs, human reviewer, ACK by consumer and merge disposition:
Outstanding blockers and next responsible owner:
```

**Quy trình nhánh (cập nhật theo thông báo 2026-11-08, thay cho quy tắc "một nhánh thống nhất" trước đây):** Giai đoạn 1 dùng một nhánh docs `docs/phase2c-tv3-design` và một PR docs vào `main` để review chéo; chỉ merge khi không còn vấn đề chặn, đủ review và lead chốt. Giai đoạn 2: **một task = một nhánh = một PR** từ `main` mới nhất, có test và CI, review chéo, merge từng PR khi đủ điều kiện, không chờ hết Phase. Không push trực tiếp `main`, không tự merge PR của mình, không đẩy source code hoặc cấp quyền runtime trước khi docs và phụ thuộc của task được duyệt.
