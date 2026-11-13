# HANDOFF TV5 — Phase 2E: Simulator, Finalization & Worker Reputation

**Owner:** TV5 `@NguyenDucThang-tb` — chủ sở hữu Simulator và *nghiệp vụ* Finalization/Reputation (GPU-005).  
**Phiên bản:** `v1.1 — FINAL-DESIGN-ALIGNED / FOR_LEAD_REVIEW`, 2026-11-07.  
**Trạng thái handoff:** `ACK_WITH_ACTIONS / AWAITING_LEAD_APPROVAL`. Khi nhóm trưởng đồng ý: `APPROVED_HANDOFF_CONDITIONAL`, **không phải quyền code**.  
**Thiết kế chuẩn:** `Phase_2E_v1.8.md`, `P2E-GATE-01 = APPROVED_DESIGN_CONDITIONAL` và `P2E-GPU005B-GATE-01 = APPROVED_DESIGN_CONDITIONAL`. Các E-IF, tham số cache, quy trình xử lý lộ khóa, typed-contract vẫn `PENDING_ACK`, `PENDING_PARAMS` hoặc `NEEDS_OWNER_DECISION`.  
**Historical GitHub evidence snapshot (2026-11-07):** the PR #39 status, SHA and failing run described in the original v1.1 snapshot below are historical. Current state and exact-head CI are recorded in the 2026-11-08 addendum at §12; do not use the old snapshot as current status.
**Phạm vi thực hiện lượt này:** **chỉ sửa tài liệu handoff và báo cáo review**. Không sửa GitHub/code/migration, không chạy Phase 2 test, không tự chốt phương án bảo mật còn mở.

## 1. Mục tiêu tổng quát và định nghĩa thành công

TV5 phải (sau khi được cấp coding gate) hoàn thiện **thực thi mô phỏng deterministic**, **ký và gửi Signed Result V1**, đồng thời thiết kế/chứng minh **nghiệp vụ Manager Finalization, giải phóng GPU và Reputation đúng một lần** khi hệ thống gặp lỗi mạng, restart hoặc cạnh tranh đồng thời.

**Bảy kết quả bắt buộc:**

1. **Mô phỏng đúng chuẩn được duyệt:** `simulation_input` chỉ có `{ "workload_profile": "demo-v1" }`; phiên bản `demo-v1-public1`, mock output **đúng 9 trường**, bucket 80/10/10, `work_units=0..999999`, các vector V1–V4 và output digest không sai một byte. Đây là mô phỏng **công khai, dự đoán được**, không phải thực thi GPU thật/anti-cheat.
2. **Dispatch có danh tính bất biến:** một Job có một logical `attempt_id` và một Outbox event bền vững; resend giữ nguyên request bytes, Attempt, event, deadline. Trong khi cache RAM còn, identical resend là idempotent, altered same Attempt => `409 EXECUTION_CONFLICT`. Không tuyên bố phát hiện được xung đột **sau cold restart** khi chưa chốt `P2E-CACHE-GAP-01`.
3. **Worker signing an toàn:** ký **đúng 11 trường Signed Result V1** bằng Ed25519/JCS với khóa riêng Worker được cấp qua secret boundary; public `(worker_id,key_id)` đăng ký và giữ lịch sử; không trao key riêng cho API, Manager hay PostgreSQL.
4. **Callback retry đúng:** một receipt đã tạo dùng **cùng `result_id` và raw HTTP envelope bytes** cho mọi lần retry của chính receipt đó. `202` từ API chỉ là Inbox đã commit (hoặc duplicate), chưa phải Job thành công hoặc chữ ký hợp lệ.
5. **Chỉ Manager được kết thúc Job:** TV3 cung cấp typed verifier result; TV5 xác định policy, TV1 điều phối, TV2 thực thi UoW sau khi tái kiểm tra bằng chứng. Không finalize trực tiếp từ callback hoặc từ thời gian `finished_at` do Worker khai.
6. **Atomic exactly-once business effects:** ở kết quả hợp lệ, cùng một commit ghi accepted `signed_results`, Job terminal, Allocation release, Listing `allocated_gpu_count` giảm đúng số, Inbox state, contribution và Worker aggregate (nếu áp dụng); replay/crash/unknown COMMIT không có hiệu ứng thứ hai.
7. **Deadline, security và restart đúng:** callback đã commit đúng hạn có thể được verify sau deadline; Manager không kết luận `SYSTEM_FAULT` trước khi xét hết candidates đúng hạn; không lộ oracle, token, chữ ký riêng; có bằng chứng PostgreSQL real roles, concurrency barriers và E2E năm service trước merge.

**Definition of Done:** đúng tất cả invariant và test oracle trên commit SHA được review; migration revision, DB-native roles, test fixtures, trước/sau các hàng, CI và independent human ACK được lưu. Không dùng CI Phase 1 để coi các kiểm thử Phase 2 `PASS`.

## 2. Phân công rành mạch — TV5 làm gì, không làm gì?

| Thành phần | TV5 chủ trì | Phụ trách của thành viên khác |
|---|---|---|
| Mock execution | Implement deterministic simulator, `demo-v1`, cache Attempt, output 9 trường, signer và callback client | **TV1:** deployment/Manager dispatch; **TV3:** internal service-auth policy; **TV2:** không cấp DB cho Simulator |
| Dispatch retry | Đảm bảo Simulator chấp nhận stable request, xử lý duplicates/conflicts và deadline hints | **TV1:** Dispatch Loop/HTTP client; **TV2:** Outbox lease 30s/fence, persisted retry và COMMIT; **TV4:** phân biệt RUNNING retry với new allocation |
| Signature | TV5 tạo payload 11 trường, ký bằng private key Worker; test đối chiếu byte với TV3 | **TV3:** strict parser và Ed25519 verifier; **TV2:** public-key registry `(worker_id,key_id)`; **TV1:** secret injection/config |
| Callback API | TV5 gửi raw callback, retry đúng policy; cung cấp fixture và client tests | **TV3:** bảo vệ route `/internal/v1/results/callback`, strict parsing; **TV2:** `TX-INBOX-INGRESS`/duplicate/DB clock; **TV1:** API mounting |
| Accepted result | TV5 lập policy signed claim → Job terminal/reputation, xác nhận candidate winner | **TV3:** typed verification verdict; **TV2:** `TX-FINALIZE`/`TX-DEADLINE-FALLBACK` SQL+UoW; **TV1:** verification/finalization Manager Loop |
| Capacity/FIFO | TV5 xác nhận kết quả release và không tạo allocation thứ hai | **TV4:** FIFO/PAUSED rule; **TV2:** atomic GPU counters; **TV1:** Scheduling Loop |
| Reputation | TV5 quyết định mapping `SUCCESS`, `WORKER_FAULT`, `JOB_FAULT`, `SYSTEM_FAULT` và test oracle | **TV2:** contribution/aggregate persisted once-only; **TV1:** event orchestration. Dispute adjustment là **Phase 3**, không triển khai trong Phase 2 |

**Cấm tự triển khai:** thêm bảng thứ 19/service thứ sáu, Simulator tự kết nối DB/oracle, tạo `TX-FINALIZE` SQL cạnh tranh với TV2, tự quyết `VERIFIED` thay TV3, đổi 11-field V1/9-field output/80:10:10, mở rộng Phase 3 Dispute, tự approve/merge PR của chính mình. **Một nhánh/PR cho gói công việc TV5 đã duyệt** theo quy trình nhóm, không tạo loạt nhánh nhỏ.

## 3. File và tiêu chuẩn bắt buộc đọc trước

### 3.1. Năm tài liệu FINAL được chốt *ở mức thiết kế có điều kiện*

| File | Nội dung TV5 cần nắm | SHA256 của file FINAL |
|---|---|---|
| **`Phase_2E_v1.8.md`** | `P2E-OPEN-01..04`, GPU005B `DEC-01..07`, 11-field vs 9-field, `E-IF-01..12`, `P2E-DRT-01..20`, `P2E-CACHE-GAP-01` | `90af557a46a0f7bcb663eb9d17de3a2db866c4c0b2f1e5006a9160eed2d6609f` |
| `Phase_2B_v1.3.md` | 6 bảng Phase2, Inbox exact raw bytes, one-UoW Finalize/Deadline, grants và `COMMIT_OUTCOME_UNKNOWN` | `27c59f3e2eddc2584fc9c904aacfc7d45aa323b8745ec77eb5775d59b1af3371` |
| `Phase_2C_v0.9.md` | TV3 service auth, typed verifier, Ed25519/JCS, key registration/rotation, `C-IF-01..11` | `d92901a412aaaaa3a2e601781b3991019de9eeee1f45b891564a64d3fbd33902` |
| `Phase_2A_v0.9.md` | 3 Manager loops, worker pool, circuit/restart/shutdown, HTTP/DB separation | `2168e036203c1370b56c2ffe7e5633d398266f72423a370254df33273f7162a2` |
| `Phase_2D_v0.9.md` | PAUSED RUNNING resend, strict FIFO/allocation, signer key readiness; `reserved_gpu_count` là **erratum**, chỉ dùng cột `allocated_gpu_count` | `fdb7f79a1b89b9ed911fddce67da1763ea88a5417ab946a3121f8701f8758c60` |

### 3.2. Đọc mã nguồn thật trên exact accepted-main SHA sau khi baseline được chốt

- `docs/architecture/decisions/ADR-002-postgresql-access-boundaries.md`, `ADR-003-internal-communication.md`, **`ADR-004-signed-result.md`**, **`ADR-005-retry-timeout-internal-auth.md`**, `docs/design/{api-contract,database-design,test-design}.md` (API §13, DB §§9/11).
- `docs/architecture/phases/phase1e_gpu005_reference_technical_specification.md`: Phase1 `demo-v1-public1`, vectors V1–V4; Phase 2E v1.8's conditional design record is now present on main through PR #44 document intake, while cross-phase ACKs and implementation permission remain separate.
- `backend/src/gpu_marketplace/jobs/{reference,submit,submit_ports,cancel,router}.py`, `backend/src/gpu_marketplace/repositories/{job_submit,jobs,commit_outcome}.py`, `backend/tests/{test_jobs_reference,test_jobs_submit_adapter_postgres,test_jobs_cancel_adapter_faults,test_phase1_runtime_http_postgres_e2e}.py`.
- `simulator/src/gpu_marketplace_simulator/{app,config}.py`: ở PR39 HEAD kiểm tra, Simulator **mới có health/live + health/ready**, chưa có internal dispatch/signer/callback client Phase2.
- `backend/src/gpu_marketplace/manager/service.py`: `_foundation_idle_runner`, chưa có Finalization Loop. `backend/src/gpu_marketplace/api/app.py`: Phase1 Auth/Listings/Jobs routes, chưa có internal callback Phase2.
- Các Phase 2 test **`NOT_RUN`**; PR39 HEAD mới sửa Phase1 mutation audit và Listing↔Submit concurrency tests, song Python CI hiện FAIL do `NameError` trong test PAUSED replay; không tự suy luận đã hoàn tất 2E. Re-review mọi nhận xét còn mở trên **exact HEAD mới**, không dùng review trên commit cũ làm ACK mới.

## 4. Những bất biến đã được owner duyệt — không tự mở lại

### 4.1. Ba chuẩn byte không được lẫn nhau

| Phân lớp | Chuẩn phải tuân thủ |
|---|---|
| **Input dispatch** Manager→Simulator | `POST /internal/v1/executions`; 10 key ở API Contract §13.1: `outbox_event_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `gpu_count`, `duration_seconds`, `simulation_input`, `finish_due_at`, `hard_deadline_at`. `simulation_input` chính xác `{"workload_profile":"demo-v1"}`. Không gửi `simulation_references`, seed, expected digest, private key, service token trong JSON body. |
| **Deterministic mock output** | Chính xác **9 trường**: `schema_version="demo-v1"`, `job_id`, `listing_id`, `requested_gpu_count` (= dispatch `gpu_count`), `duration_seconds`, `workload_profile="demo-v1"`, `work_units`, `outcome`, `failure_reason`. Digest = `sha256:` + SHA256(UTF8(JCS_RFC8785(9-field output))) ở hex lowercase. `work_units=0..999999`. Bucket: 0..79 `SUCCESS/null`; 80..89 `FAILED/WORKER_FAULT`; 90..99 `FAILED/JOB_FAULT`. |
| **Signed Result V1** | Payload **11 trường**: `schema_version="1"`, `result_id`, `job_id`, `attempt_id`, `worker_id`, `listing_id`, `outcome`, `failure_reason`, `result_digest`, `finished_at`, `key_id`. Byte ký: ASCII `GPU-MARKETPLACE:SIGNED-RESULT:V1\n` (một LF thật) + UTF8(JCS_RFC8785(payload)); Ed25519 64 byte, `signature` base64url unpadded 86 ký tự; outer `signature_encoding="base64url-no-padding"`. `finished_at` `YYYY-MM-DDTHH:mm:ss.ffffffZ` là **Worker claim**; không quyết định deadline/terminal/retention. |

`demo-v1-public1` deterministic reference ở TX-SUBMIT dùng domain `GPU-MARKETPLACE:SIM-REFERENCE:PUBLIC-V1\n`, SHA256/domain counter uint32 BE/rejection sampling; 4 vector V1–V4 đã được cố định trong thiết kế (bao gồm V4 nhánh rejection sampling). **Không** suy diễn `json.dumps(sort_keys=True)` của domain ASCII/uint32 hạn chế thành RFC8785 JCS tổng quát cho mọi JSON. Chuẩn ký/fixture phải được kiểm tra liên runtime bằng thư viện phù hợp.

### 4.2. Chính sách cache, dispatch, callback

- **Đã duyệt:** cache RAM có giới hạn, concurrency-safe, keyed `attempt_id`/immutable dispatch fingerprint; trạng thái `IN_FLIGHT` và `FINISHED` là **nội bộ RAM**, không phải Job status. Cùng Attempt+bytes khi cache retained -> `202` không có mock execution thứ hai; cùng Attempt nhưng body khác -> `409 EXECUTION_CONFLICT`, không ghi đè cached state.
- **Còn mở `P2E-CACHE-GAP-01`:** sau cache eviction/cold restart, Simulator không thể tự chứng minh cùng Attempt đã có body khác trước đó. Phương án kiểm tra bằng persisted Outbox qua đường giao thức tin cậy hoặc thay đổi phạm vi `409` cần **quyết định riêng** của lead + TV1/TV3/TV5. Không tự tạo DB/storage của Simulator, không tự tuyên bố global 409 đã được bảo đảm.
- **Còn mở cache budgets:** max entry/byte, TTL so với `hard_deadline_at`, không xóa `IN_FLIGHT` bừa, concurrent duplicate waiters, shutdown/cancellation, timeout và overload -> TV1/TV5 chốt. Cần test bound memory/CPU và không leak raw signed secret.
- **Callback retry của cùng receipt:** giữ **nguyên toàn bộ envelope bytes**, `result_id`, `finished_at`, chữ ký; `202 STORED` hoặc `202 DUPLICATE` là thành công transport. Nếu cached receipt mất do cold restart, mock có thể re-execute **cùng Attempt**, sinh **result_id mới** và một Inbox candidate riêng; không đồng nghĩa có Job/Allocation mới.
- **Service tokens:** Manager→Simulator dùng riêng `MANAGER_DISPATCH_TOKEN`; Simulator→API dùng `SIMULATOR_CALLBACK_TOKEN`, đều random entropy ≥256-bit, không dùng user JWT. Error/timeout theo ADR-005: HTTP connect 2s, total 5s, retry 2,4,8,16,30...s capped, 401/403 recovery throttle ≥30s, claim 30s, missing-result probe `finish_due_at+10s`, hard deadline `finish_due_at+120s`. Không gửi thêm lệnh mới sau deadline; không dùng local timer làm DB admission clock.
- **Phase1 PAUSED replay khác Phase2 RUNNING redelivery:** cùng Client/key/normalized request đã lưu => HTTP 200 Job cũ ngay cả Listing PAUSED (owner đã duyệt trên [PR39 #6690901724](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39#issuecomment-6690901724)); changed body 409, new-key submit cần ACTIVE. Khi đã RUNNING, Listing chuyển PAUSED **không** ngăn Manager retry dispatch Attempt cũ; **không cấp Allocation mới**.

### 4.3. Manager Finalization và danh tính kết quả

1. API do TV3 bảo vệ bằng callback Bearer; TV2 lưu **exact raw envelope bytes** vào `result_inbox` sau Listing→Job lock và dùng DB `clock_timestamp()` **sau Job lock**, chỉ new candidate khi `received_at < hard_deadline_at`, `==` là muộn.
2. Same retained result_id + exact full bytes + same trusted context => `202 DUPLICATE`, kể cả sau terminal; same ID/body altered => `409 RESULT_ID_COLLISION`. `202` chỉ sau COMMIT xác nhận; unknown COMMIT phải retry original bytes/ID để reconciliation, không tự đổi UUID/timestamp. Two concurrent inserts: unique loser rollback/re-read winner rồi đối chiếu **exact bytes**, SHA không đủ.
3. TV3 kiểm chứng persisted V1 envelope và trả kiểu *đề xuất* `VerifiedV1Receipt`/`RejectedV1Receipt` có Inbox ID, raw SHA, context, key/version. **Tên field/Python type chưa freeze:** `P2E-VERDICT-CONTRACT-01=PENDING_ACK`.
4. TV1 gọi TV5 finalization policy **trong TV2 UoW**. Sau mọi kiểm tra chữ ký ngoài lock, transaction khóa **Listing → Job → Attempt/Allocation → Inbox → Contribution → Aggregate**, SELECT mới dưới `READ COMMITTED`, kiểm Job RUNNING, Attempt active, key trusted, Inbox identity/bytes/context, deadline, chưa có accepted result. Verdict stale không được tự tạo business effect.
5. Nhiều `result_id` đúng hạn của một Attempt là **nhiều Inbox candidates riêng**; xử lý đúng `(received_at, inbox_id)`, reject invalid rồi xét tiếp, **candidate verified eligible đầu tiên** mới commit. Sau terminal, những candidate khác phải được đóng bằng trạng thái hiện hữu `REJECTED`/housekeeping sau khi ACK; **không tự thêm enum `SUPERSEDED`**.
6. Sau hard deadline, **quét hết** pending candidates đã commit đúng hạn, theo nhiều batch bounded nếu cần, rồi mới `TX-DEADLINE-FALLBACK`; valid on-time Inbox có thể xử lý sau deadline khi Manager restart. `finished_at` không thể backdate ingress.
7. Kết quả hợp lệ và timeout fallback dùng **một COMMIT** cho Job terminal, `signed_results` nếu có, Allocation `ACTIVE→RELEASED`, Listing `allocated_gpu_count` decrement, Inbox processed, contribution và lifetime aggregate nếu có. Lỗi trước COMMIT rollback; ambiguous COMMIT đọc/truy vấn lại theo Job/Attempt/unique keys, không execute lại mù.

### 4.4. Reputation mapping — binary oracle

| Kết quả | Job | `signed_results` | `job_reputation_contributions` | `worker_reputation_aggregates` |
|---|---|---|---|---|
| V1 `SUCCESS`, `failure_reason=null` | `COMPLETED` | 1 accepted | `SUCCESS` 1 row/Job | `successful_jobs +1` |
| V1 `FAILED/WORKER_FAULT` | `FAILED` | 1 accepted | `WORKER_FAULT` 1 row/Job | `worker_fault_jobs +1` |
| V1 `FAILED/JOB_FAULT` | `FAILED` | 1 accepted | `NONE` 1 row/Job | **không đổi** |
| Manager `FAILED/SYSTEM_FAULT` | `FAILED` | **không có** | **không có** | **không đổi, không phạt Worker** |
| Client `CANCELLED` khi QUEUED | `CANCELLED` | không có | không có | không đổi; không Allocation |
| Sai signature/context, late/new-after-terminal | Không có terminal effect | không tăng | không tăng | không đổi |

Đây là chính sách **mô phỏng**; `WORKER_FAULT` không đánh giá GPU thật. Phase 3 Dispute có thể sửa `effective_category` theo transaction được duyệt sau này nhưng **không** sửa lịch sử signed proof, `initial_category` hoặc tự tái áp dụng contribution trong Phase 2. `worker_reputation_aggregates` là bảng Phase 1 đã có; `job_reputation_contributions` là một trong **6 bảng mới Phase 2**.

## 5. Sáu nhiệm vụ chuẩn bị TRƯỚC coding gate (chỉ phân tích/ACK/tài liệu)

| ID | Mục tiêu công việc và thao tác cụ thể | Đầu ra TV5 phải nộp / điều kiện chốt |
|---|---|---|
| **TV5-P2E-01** | **Baseline Phase1 và mốc PR39:** đối chiếu Jobs Submit/Cancel, generator `reference.py`, V1–V4, audit/Submit↔Pause/Resize/role tests; xác nhận merged #39, exact accepted head/CI evidence, `alembic heads`, phân biệt Phase1 approval với Phase2 conditional design. | `TV5_BASELINE.md`: commit/migration/CI/review evidence; open issues/deferrals; rule same-key PAUSED 200 đã duyệt; không ghi PR39 Draft là main-approved |
| **TV5-P2E-02** | **Đóng băng generator và wire:** độc lập tính 4 vector, hash-domain/rejection sampling, 9-output schema, 11 V1 payload, map `gpu_count`→`requested_gpu_count`; đối chiếu `API Contract §13`/ADR004; vạch ranh giới không có oracle trong Simulator. | `TV5_WIRE_AND_REFERENCE.md`: sample byte exact hash, field allowlist, 2-runtimes JCS fixture, negative cases, `P2E-VEC/SCHEMA/WIRE` mapping; TV3 ACK |
| **TV5-P2E-03** | **Simulator cache & conflict decision:** mô tả identity/fingerprint, simultaneous duplicate, in-flight/finished, retry vs regenerate, bound cache/TTL/evict/shutdown; đưa `P2E-CACHE-GAP-01` thành hai phương án trade-off để lead quyết định qua change-control, không tự chọn. | `TV5_CACHE_AND_DISPATCH.md`, capacity/time budgets chờ TV1+TV5 ACK; biên bản owner quyết định cho cross-restart `409` hoặc scope-change trước code |
| **TV5-P2E-04** | **Signing key custody & service-auth:** chốt Worker↔`key_id`↔32-byte public key registry, private-key injection/recovery/restart, planned K1→K2 quiescence; phân biệt compromised key incident `NEEDS_OWNER_DECISION`; cùng TV3/TV1 chốt dispatch/callback Bearers và log redaction. | `TV5_SIGNING_KEY_RUNBOOK.md` (không có secret), ACK TV1/TV2/TV3/TV4; owner quyết định incident policy riêng trước phần code bị ảnh hưởng |
| **TV5-P2E-05** | **Callback/replay, typed verdict và nhiều receipt IDs:** chốt raw envelope stable retry, `202 STORED/DUPLICATE`, `409` collision, timeout/COMMIT-unknown, `(received_at,inbox_id)` candidate order, typed `VerifiedV1Receipt`→Finalizer re-read; không đụng SQL trực tiếp. | `TV5_RECEIPT_FINALIZER_CONTRACT.md`, `P2E-VERDICT-CONTRACT-01` TV1/TV2/TV3/TV5 ACK, error/no-double-effect table, exact preconditions/outcomes |
| **TV5-P2E-06** | **Chốt finalization/reputation, acceptance và release gates:** xác nhận bảng phân loại 4 paths, one-UoW transaction, Inbox drain deadline, unknown COMMIT, rollback; chốt 20 DRT test oracle, PG barriers, 5-services E2E; thu thập `E-IF-01..12` ACK người tạo/người dùng. | `TV5_TEST_AND_RELEASE_PLAN.md`, bảng test setup/expected results, danh sách BLOCKED/NOT_RUN và ACK; **coding gate quyết định riêng bởi lead** |

**Không yêu cầu TV5 phải chạy Phase2 runtime tests trước coding gate**; test execution chỉ có thể `PASS` sau khi implementation được cho phép. Nhưng mọi `NEEDS_OWNER_DECISION` có ảnh hưởng contract, chứng cứ baseline và giao diện phải chốt **trước khi viết code phụ thuộc**.

## 6. Mười ba nhiệm vụ triển khai SAU khi được cấp phép code Phase2

| ID | Công việc TV5 trực tiếp làm hoặc phối hợp | Bằng chứng/acceptance (cần test, không chỉ đọc code) |
|---|---|---|
| **TV5-P2E-07** | **Simulator dispatch endpoint:** xây trong service **Simulator hiện hữu** `POST /internal/v1/executions`, validate JSON/10-key allowlist, Bearer đúng hướng (policy TV3), UUID/`simulation_input`/deadline hints; không nhận oracle/đường chạy code người dùng. | `202` đúng immutable request; sai service token `401`, invalid input `422`, xung đột cached `409`; port chỉ internal, không DB URL |
| **TV5-P2E-08** | **Bounded concurrent Attempt cache:** trong RAM duy trì atomic `IN_FLIGHT→FINISHED`, immutable fingerprint, coalesce duplicate khi đang chạy, giữ signed receipt bytes cho retry, giới hạn TTL/entry/memory/eviction, shutdown; **chỉ triển khai cross-restart policy đã được lead duyệt**. | DRT-01..04; 2 simultaneous identical => 1 in-process mock execution nếu retained; altered same Attempt => 409; không claim toàn cục sau restart khi chưa có quyết định |
| **TV5-P2E-09** | **Deterministic workload:** triển khai đúng `demo-v1-public1`, output 9 fields, SHA256/JCS, domain/rejection sampling từ dữ liệu Job/Listing/Worker/trusted immutable dispatch; không đọc `simulation_references` hay seed DB. | V1–V4 byte/hash, 80/10/10 mapping, `work_units` range, same Job after restart same output/digest; independent two-runtime oracle |
| **TV5-P2E-10** | **Signer & Worker key loading:** cấp đúng K1/K2 private key từ secret runtime, sign 11-field V1 bằng Ed25519/JCS, canonical 86-char signature, `key_id` gắn Worker; fail closed nếu thiếu/key mismatch. | ADR-004 WIRE/SIG, tamper negative, no log/DB of private key; planned K1→K2 verification and restart recovery; incident policy riêng |
| **TV5-P2E-11** | **Simulator callback client:** gửi exact raw envelope tới existing Backend API callback, token riêng; ghi retry/backoff, handle 202/408/429/5xx, 401/403 rate-limit, 409/422 permanent, lost ACK same bytes/ID; không gọi DB. | DRT-09..11; `202 DUPLICATE` không đổi raw/timestamp; unknown COMMIT chỉ gửi lại original receipt, không tạo result ID mới |
| **TV5-P2E-12** | **Cold restart/reexecution recovery:** bootstrap lại private key/callback credentials và xử lý immutable resend; cho phép mock chạy lại với **new `result_id`** khi cache cũ mất; giữ stable Attempt/deadlines; guard contradictory cold dispatch theo owner-approved design. | DRT-03..06; original nine-field output/digest khớp, không tạo Allocation/Attempt thứ hai; `DRT-04` không thể PASS trước owner decision |
| **TV5-P2E-13** | **Pure Finalization policy:** mapping typed TV3 `VerifiedV1Receipt` thành domain acceptance/classification; tách `RejectedV1Receipt`/stale/unbindable; **không** đọc raw callback và tự tạo `verified=True`, không tự commit DB. | Unit/domain tests cho enum/claim mismatch, không release/counter vì lỗi signature, JOB_FAULT → NONE, SYSTEM_FAULT không dùng signed V1 |
| **TV5-P2E-14** | **Manager Finalizer integration với TV1/TV2:** áp dụng policy khi TV1 gọi TV2 `TX-FINALIZE`; TV2 one-UoW locks/recheck Inbox evidence, Job RUNNING, Attempt/key, release và contribution; TV5 review backend state changes, no independent commit. | DRT-12/17/18; Exactly one accepted result/terminal/release/contribution; zero extra effect khi replay/crash/unknown COMMIT |
| **TV5-P2E-15** | **Inbox multi-candidate/business winner:** phối hợp TV2/TV3 xét `(received_at,inbox.id)` mọi candidate đúng hạn theo batch, reject invalid rồi tiếp candidate valid, không thêm enum `SUPERSEDED`, không chặn hợp lệ ở batch sau. | DRT-12/13/16; first verified eligible wins, non-winner 0 business effect, invalid-first valid-second pass |
| **TV5-P2E-16** | **Timeout/System Fault policy:** cùng TV1/TV2 chỉ fallback sau DB hard deadline và đã vét hết on-time pending, không trust Worker `finished_at`; release một lần và 0 reputation penalty. | DRT-14/15/16/18; `received_at=deadline-1µs` có thể finalize sau restart; equality muộn; SYSTEM_FAULT không có signed_results/contribution |
| **TV5-P2E-17** | **Reputation & role-safe read compatibility:** TV5 xác nhận contribution initial/effective category và lifetime aggregation không double; khi có Results/Job projection chỉ expose an toàn, không oracle/private bytes; **không xây Dispute Phase3**. | SUCCESS +1 success, WORKER_FAULT +1 fault, JOB_FAULT NONE 0, SYSTEM_FAULT no row 0; snapshot role-filtered không lộ secret; retention test Phase3 ghi BLOCKED_PHASE3 |
| **TV5-P2E-18** | **Comprehensive tests & fault injection:** Simulator cache/restart/HTTP, JCS+Ed25519 two runtimes, PostgreSQL native roles, 2 session commit-order barriers, crash at all finalization boundaries, 5-service Compose E2E cùng TV1–TV4. | DRT-01..19 relevant fixtures thực thi `PASS`; CI exact SHA, DB revision, 2 commit orders, deadline fake DB-clock, redacted logs, no skipped mandatory; DRT-20 Phase3 scope remains blocked |
| **TV5-P2E-19** | **PR/handoff & independent human review:** bàn giao 1 branch/PR TV5 đã duyệt, source-owned file map, migration dependency, stable artifact SHA, 12 interface ACKs, screenshots/log/redacted test evidence, rollback/feature-disable plan. | Review trên HEAD mới; own PR không self-approve; Phase1 PR39 acceptance và Phase2 integration gates rõ; chỉ đề xuất merge khi mandatory tests thực sự PASS và blockers closed |

## 7. Giao diện liên thành viên phải được ACK chính thức (`E-IF-01..12`)

| ID | Producer → consumer chính | Cần chốt cụ thể trước khi viết code phụ thuộc | Trạng thái |
|---|---|---|---|
| `E-IF-01` | TV1/TV2 Outbox → TV5 Simulator | Immutable 10-key dispatch, Event/Attempt IDs, payload fingerprint, no oracle | `PENDING_ACK` |
| `E-IF-02` | TV1/TV3/TV5 + lead | Same-Attempt altered request **sau cold restart**: enforceable verified path hay approved contract qualification | **`NEEDS_OWNER_DECISION`** |
| `E-IF-03` | TV5 cache ↔ TV1 runtime | TTL/entry/memory/batch/concurrent capacity, eviction in-flight, graceful shutdown/restart | `PENDING_PARAMS` |
| `E-IF-04` | TV3 key policy + TV2 registry → TV5 signer + TV1 runtime | Worker/key_id ownership, secret injection/recovery, K1/K2 planned rotation, incident policy | `PENDING_ACK / OWNER_DECISION` |
| `E-IF-05` | TV5 signer → TV3 verifier | 9 output vs 11 V1, exact prefix/JCS/Ed25519, V1–V4+ADR004 vectors | `PENDING_ACK` |
| `E-IF-06` | TV5 callback sender ↔ TV3 ingress + TV1 API wiring | Purpose Bearer, raw envelope/size budget, 202/401/409/422/5xx, redaction | `PENDING_PARAMS / ACK` |
| `E-IF-07` | TV3 ingress → TV2 Inbox, TV5 consumer | Exact full bytes/context, UNIQUE loser, commit-unknown result, native GRANT | `PENDING_ACK` |
| `E-IF-08` | TV3 typed verifier → TV5 Finalizer + TV2 UoW + TV1 caller | Immutable `VerifiedV1Receipt` provenance/inbox ID/key/sha, DB recheck, stale verdict rejection | `PENDING_ACK` |
| `E-IF-09` | TV2 Inbox candidate cursor → TV3 verify/TV5 Finalizer | Deterministic ordering, batch completeness, rejection/housekeeping after terminal | `PENDING_ACK` |
| `E-IF-10` | TV5 policy → TV2 Finalization UoW/TV1 Manager | One commit: signed row, Job terminal, release GPU, contribution+aggregate/no-op | `PENDING_ACK` |
| `E-IF-11` | TV2+TV4 Phase1 Submit/Allocation ↔ TV5 | Owner-approved replay-on-PAUSED 200 and RUNNING re-dispatch under PAUSED, distinct rules | `PENDING_ACK / TEST` |
| `E-IF-12` | TV1–TV5 (Phase 1 gate) | Accepted-main SHA, Alembic head/role/CI, PR39 review impact, Phase2 coding authorization | `PENDING_PHASE1_GATE` |

**ACK hợp lệ:** mỗi owner/consumer xác nhận version+SHA source và consumer, concrete DTO fields/error code/DB transaction owner, test oracle và quyết định `ACK_COMPATIBLE / ACK_WITH_ACTIONS / BLOCKED`; không lấy ACK của nhóm trưởng thay human test evidence, không lấy review của PR39 trên SHA cũ thay review HEAD mới.

## 8. Sơ đồ luồng xử lý và truth tables

### 8.1. Chuỗi thực thi an toàn

```text
Client POST Job (Phase1; protected reference lưu riêng trong PG)
  → TV4 FIFO + TV2 TX-ALLOCATE (Job RUNNING, Allocation, Attempt, Outbox atomic)
  → TV1 Dispatch Loop (lease/fence SQL qua TV2; HTTP sau commit)
  → TV5 Simulator (MANAGER_DISPATCH_TOKEN, immutable request, bounded cache)
  → TV5 mock output 9-field → TV5 sign V1 11-field → callback exact raw bytes
  → TV3 API auth+strict parse → TV2 TX-INBOX-INGRESS (COMMIT) → HTTP 202
  → TV1 Manager Inbox Loop → TV3 typed independent VERIFIER
  → TV5 finalizer policy → TV2 TX-FINALIZE (ONE COMMIT, lock/recheck)
  → Job terminal + GPU released + contribution/aggregate as applicable
```

**Không bao giờ:** từ HTTP `202` → Job terminal ngay; từ `finished_at` → deadline; từ protected reference → Simulator payload; từ `FAILED/JOB_FAULT` → Worker penalty; từ `PAUSED` → hủy RUNNING Attempt.

### 8.2. Ma trận tình huống cần kiểm tra bằng PostgreSQL hoặc HTTP thực

| Tình huống | Thứ tự/phạm vi test | Kết quả hợp lệ cần chứng minh |
|---|---|---|
| Manager dispatch cùng Attempt 2 lần khi cache RAM còn | Đồng thời; cùng bytes / bytes khác | Cùng bytes 202 + 1 in-flight work, khác bytes 409; không tạo Job/Allocation mới |
| Cache cũ mất, cold restart và resend | Simulator restart trước retry; callback cũ có thể còn Inbox | Same immutable logical attempt; reexecute deterministic; new result ID **được phép**; one terminal effect |
| Callback 202 bị mất | Callback COMMIT rồi ACK mất; resend identical bytes | `202 DUPLICATE`, original Inbox row/hash/received_at giữ nguyên |
| Một `result_id`, 2 request khác bytes | Transaction A thắng rồi B đọc lại hoặc ngược lại | 1 winner, altered loser 409, không overwrite |
| R1 invalid trước R2 valid, cùng Attempt | Đảo thứ tự callback và đảo thứ tự xử lý candidate có kiểm soát | R1 rejected; R2 vẫn xét, đầu hợp lệ được chấp nhận 1 lần |
| Finalize thắng timeout fallback | Cùng Listing→Job lock, cả hai commit orders trên fixtures khác nhau | Một trạng thái terminal duy nhất; release và Reputation đúng tương ứng winner |
| Callback commit trước deadline nhưng verify sau | DB clock `Tdeadline - 1us`, Manager restart tới `Tdeadline+...` | Valid committed Inbox vẫn eligible, không SYSTEM_FAULT sai |
| Callback bắt Job lock tại deadline | DB clock `==Tdeadline` / sau | New callback bị từ chối; fallback chỉ sau drain old candidates |
| Crash trước/vào/sau COMMIT | Barrier inject at SQL before and after commit ACK | Trạng thái hoặc rollback toàn bộ hoặc commit đúng một lần; không blind retry unknown |
| Worker private key thiếu/rotated | Key K1/K2, signer restart và historical evidence | Fail closed on missing; retained K1 verifies; no secret leakage |
| Listing PAUSED | PAUSED trước NEW allocation / PAUSED sau RUNNING | NEW allocation không được tạo; dispatch repair Attempt đã RUNNING vẫn hợp lệ |

## 9. Bộ 20 test thiết kế Phase 2E và oracle nghiệm thu

> Các `P2E-DRT-*` dưới đây là **test design đã được mô tả trong Phase_2E_v1.8**, không phải test đã chạy. Trạng thái hiện tại **`NOT_RUN`**; riêng `DRT-04` bị chặn bởi `P2E-CACHE-GAP-01` và `DRT-20` chạm Phase 3. Không cần dựng code Phase3 để nghiệm thu công việc Phase2 được cấp phép.

| Test | Mục tiêu | Tiêu chí PASS ngắn gọn |
|---|---|---|
| `P2E-DRT-01` | identical dispatch concurrently | Một running cache execution per retained Attempt, ACK idempotent |
| `P2E-DRT-02` | altered same Attempt while retained | `409 EXECUTION_CONFLICT`, không thay job/work |
| `P2E-DRT-03` | cold restart original immutable dispatch | Same 9-field output/digest, stable Attempt, once-only business effects |
| `P2E-DRT-04` | cold restart contradictory immutable request | **BLOCKED_BY_DESIGN_DECISION** đến khi contract được lead chốt; không giả PASS |
| `P2E-DRT-05` | missing/invalid signing key | Fail closed, no forged signed result, no private key leakage |
| `P2E-DRT-06` | planned K1→K2 & historical key | Quiescent rotation; retained K1 receipt vẫn verify |
| `P2E-DRT-07` | V1–V4/9-field output across runtimes | Canonical bytes + SHA/digest/output exact match |
| `P2E-DRT-08` | ADR004 fixed V1, tampering variants | Chữ ký đúng verify, altered/wrong-key/invalid-wire reject |
| `P2E-DRT-09` | wrong/missing/opposite Bearer/JWT | 401; 0 dispatch/Inbox accepted |
| `P2E-DRT-10` | callback lost 202 and replay after terminal | Exact bytes/ID replay, one Inbox, 202 duplicate |
| `P2E-DRT-11` | concurrent same result ID identical/altered | UNIQUE winner, exact match 202 vs altered 409 |
| `P2E-DRT-12` | multiple valid receipt IDs same Attempt | First trusted on-time eligible verified candidate wins, one finalization |
| `P2E-DRT-13` | invalid candidate then valid | Rejected first, valid second accepted; no early timeout |
| `P2E-DRT-14` | on-time Inbox, Manager delayed after deadline | Valid persisted callback vẫn finalizes |
| `P2E-DRT-15` | callback starts lock at exact deadline | 409 late, no newly eligible Inbox |
| `P2E-DRT-16` | Inbox candidates > bounded batch | Iterate all eligible batches before fallback |
| `P2E-DRT-17` | crash before/after unknown Finalize COMMIT | No partial/double GPU release or contribution |
| `P2E-DRT-18` | SUCCESS/WORKER/JOB/SYSTEM outcome | Deltas `+1 success`, `+1 fault`, `NONE/0`, `no-row/0` |
| `P2E-DRT-19` | native-role grants / oracle & secret leakage | No Simulator DB; API/Manager least privilege; no oracle/private bytes in output/log |
| `P2E-DRT-20` | 23d purge with OPEN Dispute hold | **BLOCKED_BY_PHASE_3** for Phase3-specific implementation; lifetime aggregate not decremented by legitimate Phase2 operation |

**Gắn thêm suites chuẩn:** `P2E-SIM-01..05`, `P2E-VEC-01..05`, `P2E-SCHEMA-01..05`, `P2E-VERSION-01..06`, `P2E-VER-01..06`, `P2E-REP-01..08`, `P2E-ACL-01..06`, `P2E-DIST-01..04`, `ADR004 SIG/WIRE/ENUM`, `ADR005 RT/AUTH`, `API-INT-01..12`, `DBTX-07..12`, 5-services E2E. Test names here are *traceability*; do not equate code in `test_jobs_reference.py` (Phase 1) with phase2-signer/interop/finalization PASS.

**Evidence của từng test thực thi:** (1) exact source/consumer SHA và PR; (2) revision `alembic_version`; (3) DB role `current_user/session_user` và cluster disposable marker; (4) authenticated HTTP request ID (redacted) / sample wire hash, no secrets; (5) frozen fake DB time + both commit order barriers when race; (6) expected vs actual row counts/deltas (`jobs`, `allocations`, `execution_attempts`, `execution_outbox`, `result_inbox`, `signed_results`, `job_reputation_contributions`, `worker_reputation_aggregates`); (7) test verdict and CI artifact; (8) human independent review.

## 10. Coding/merge gates và thứ tự công việc

| Gate | Điều kiện | Thẩm quyền/Trạng thái hiện tại |
|---|---|---|
| **G0 — Phase1 accepted baseline** | PR39 thực sự được review/merge/accept trên main, xác định SHA/migrations/CI; đóng Python CI `NameError` và kiểm xem commit mới giải quyết Phase1 audit/concurrency/tests chưa; tình trạng READY/Scrypt và role credential nếu còn pending thì recorded actions/deferral | TV1 lead và affected owners; **PENDING**, PR39 Draft |
| **G1 — Pre-code design** | Chốt `P2E-CACHE-GAP-01` (global conflict), incident lộ signing key; 12 E-IF ACK, typed verdict, native role grants, cache/pool/HTTP bounds và key provisioning. Nếu còn design thay đổi, dùng interphase change control | TV1/2/3/5 + lead; **PENDING**, không auto-closing |
| **G2 — Explicit coding permission** | Nhóm trưởng đưa ra phê duyệt riêng về phạm vi và nhánh TV5 sau khi G0/G1 đạt hoặc có ngoại lệ được ghi rõ | **NOT_AUTHORIZED** |
| **G3 — Implementation + PR review** | TV5 code sau G2, không sửa PR39 Phase1 ngoài scope; test trên fixed baseline, producers/consumers ACK; 1 PR/branch cho work package TV5 | **NOT_RUN** |
| **G4 — Merge acceptance** | Relevant DRT/SIG/WIRE/DBTX/API-INT/5-services E2E thực sự PASS; native PG + bounded cache/fallback, exact HEAD CI/human re-review, no P0/P1/P2 blocking | **NOT_RUN / NO_MERGE_APPROVAL** |
| **G5 — Release** | Secrets/ingress assumptions, crash/recovery, retention and operational monitoring, separate release approval; không nhầm Phase3 dispute với Phase2 | **NOT_AUTHORIZED** |

**Thứ tự khuyến nghị:** G0/G1 → TV5 simulator dispatch/cache/wire/sign → callback client → TV3 verifier + TV2 Inbox ACK → TV5 finalizer policy & TV2 atomic UoW → Manager TV1 integration → test barriers + five-service E2E → human PR review. Không đẩy Phase2 vào PR39 Draft trước khi chốt base và branch policy.

## 11. Checklist bàn giao mẫu để TV5 điền sau khi làm

```text
[HANDOFF TV5 PHASE 2E]
Owner / GitHub account: @NguyenDucThang-tb
Accepted main SHA + actual Alembic heads/version:
Phase 2 branch / PR / reviewed HEAD SHA:
Five FINAL design SHA references:
Decision CACHE-GAP-01 / compromised key + review links:
ACK E-IF-01..12 (producer/consumer and exact SHA):
Simulator execution route + payload allowlist + cache budgets:
Vector V1..V4 / output9 / signed11 independent canonical evidence:
Signer key provisioning/rotation/restart/secret redaction:
Callback same original bytes / duplicate / unknown commit evidence:
Typed verifier contract and Inbox candidate selection:
TX-FINALIZE / timeout one UoW and row-count evidence:
Reputation matrix, no-double-counter before/after snapshots:
P2E-DRT / ADR004/005 / API-INT / DBTX / five-service E2E report:
Remaining NOT_RUN/BLOCKED/FAIL and mitigations:
CI link / independent reviewer / rollback plan:
Disposition: ACK_COMPATIBLE | ACK_WITH_ACTIONS | BLOCKED
```

**Bảo vệ quyết định:** Handoff này **chưa** sửa lại trạng thái 5 design FINAL, không tự nhận ACK của thành viên khác, không tự tuyên bố test đã chạy, không cho phép code/GitHub writes. Mỗi thay đổi tương lai ảnh hưởng producer/consumer phải thông báo và được **hai phía xác nhận** theo quy trình nhóm.

## 12. Repository status and workflow addendum — 2026-11-08

The PR #39 and source-sync statements above reflect the handoff's earlier snapshot. Current `main` is `bee832eaf5463df20f6c6815174322871eb6685a`; [PR #39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39) is CLOSED/MERGED (head `3482bce3cc9726543b9345a5224d8db1b9fc6454`, merge `aff538f79997c6e2bfcf359b176a82f2cd9ecc53`), with exact-head [CI run 42385995533](https://github.com/SE2026-BC-04/gpu-resource-marketplace/actions/runs/42385995533) SUCCESS. [PR #44](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/44) merged Phase 2 documentation sources into main. These facts update repository traceability only; they do not mean Phase 2 runtime exists, all Phase 2 design is approved, or coding is authorized.

Current related review PRs: [#45](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/45) OPEN/Draft; [#46](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46) OPEN/Ready; [#47](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/47) OPEN/Draft. Their contents are not merged contracts and do not constitute TV1–TV4 ACKs for this handoff. PR #46's conversation requests TV5 decisions on dispatch payload, signed evidence storage, aggregate creation/update, and reference access; these remain open.

The source-only command `alembic -c backend/alembic.ini heads` reports one head, `0005_listing_d7` (system Alembic 1.13.1). The `uv`-managed command was blocked by pinned dependency DNS resolution; no live PostgreSQL check was run. Record source head as verified and live DB as `NOT_RUN`.

The statement in §4 that a Phase 2E design approval exists only locally is superseded as a repository-availability statement by PR #44's merged doc intake. Its design-status meaning is not changed: Phase 2 files retain conditional/pre-code status, and coding remains a separate lead authorization.

**Workflow sync proposal — `PROPOSED — PENDING_LEAD_ACK`:** use one docs branch and one docs PR for Phase 2E design review; after coding gate, use one implementation task per topic branch/PR and allow a qualifying task to merge independently. TV5-P2E-19's one branch/PR wording is retained as historical text pending lead confirmation. This proposal does not amend active Team Contribution Rules or authorize implementation.

Current pre-code deliverables are under [`tv5-p2e-precode/`](tv5-p2e-precode/). The package preserves approved design choices and leaves outstanding ACKs, decisions and runtime tests explicit; see `TV5_BASELINE.md` and `TV5_INTERFACE_ACK_MATRIX.md`.

The historical “no GitHub writes” sentence describes the earlier handoff-only review scope. This documentation review task authorizes its docs branch/PR workflow only; it does not authorize implementation, migration, merge, or deployment.

---

## 13. Bàn giao đồng bộ Phase 2E — 2026-11-13 (đề xuất, chưa ACK)

Nguồn hiện tại trên GitHub: [TV2 #46 @ ba63466](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/46), [TV3 #49 @ 9b337f5](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/49), TV4 #48 @ b8be725; tất cả **chưa merge**. Main vẫn bee832e. Bổ sung này không thay đổi quyết định thiết kế đã được phê duyệt.

| Giao diện | Nội dung TV5 cần thống nhất trước code |
|---|---|
| Dispatch/Outbox | Chính xác 10 khóa, demo-v1, không oracle; TV5 ưu tiên P1 full immutable payload; P2 fallback; TV1/lead chốt D-05/D-13 |
| Rotation | D-18 Worker advisory shared/exclusive, 2 active keys làm quiesce marker, expected K1/K2, rollback K1, K1 public row giữ để verify; E-C3/D4 L2 chờ quyết định |
| Signer proof | TV5 ưu tiên G1 nonce proof riêng, G2 chưa có cold Manager bootstrap an toàn. Simulator secret bundle + startup self-check không đủ để chứng minh active DB key |
| Allocation | TV2 đề xuất SignerReadiness(worker_id,key_id,public_key_fingerprint,proof_expires_at) *nội bộ*; dưới Worker+Listing locks đối chiếu sole active key/fingerprint và DB expiry; sai ⇒ Blocked(SIGNER_NOT_READY), không tạo Job/GPU/Outbox; P2B-DRT-29 NOT_RUN |
| Callback | 202 STORED/DUPLICATE, 401, 404, 409 (collision/not-acceptable), 422, 503; cùng raw envelope/result_id khi retry; stored received_at quyết định deadline; D-01/E-C1, D-02/E-C2 chờ lead |
| Verifier → Finalizer | TV3 full immutable VerifiedV1Receipt/RejectedV1Receipt, 4 mã rejection; TV5/TV3 ưu tiên V-OUT + TV2 locked recheck/extractor, chưa chốt E-C4 |
| Terminal/UoW | PrecedingPending; deadline fallback fresh DB scan, không tin caller proof; one UoW signed evidence/Job/release/Listing/Inbox/reputation, SYSTEM_FAULT không phạt Worker |

**Quy trình:** giữ **một nhánh thiết kế docs/phase2e-tv5-design**, **một Draft PR #50**. Sau G1 docs gate và quyền code G2 riêng của nhóm trưởng, mỗi nhiệm vụ triển khai dùng branch/PR độc lập từ main mới nhất, không đưa mã vào PR docs. Chưa có quyền merge hoặc triển khai. TV3 đã comment ACK_WITH_ACTIONS tại SHA #50 cũ 7b5ee16; TV5 đã review #46 @ ed19a51 và #49 @ 9b337f5 (đều ACK_WITH_ACTIONS), không tự chuyển ACK sang SHA mới. Cần TV1/TV2/TV3/TV4/lead và người thật độc lập xác nhận **exact producer/consumer SHA**, hợp đồng, test oracle; mọi test PostgreSQL native-role/concurrency/crypto/5-service E2E Phase 2 đều **NOT_RUN**.
