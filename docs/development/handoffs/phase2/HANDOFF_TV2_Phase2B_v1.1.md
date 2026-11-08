# HANDOFF TV2 — Phase 2B: PostgreSQL Persistence, Atomic Transactions & Database Security

**Phụ trách:** TV2 — `@TranVu2005` (Database owner)  
**Phiên bản:** `v1.1 — FINAL-DESIGN-ALIGNED — REVIEWED_FOR_OWNER_APPROVAL`  
**Ngày review:** 2026-11-07  
**Trạng thái handoff:** `ACK_WITH_ACTIONS / READY_FOR_OWNER_REVIEW`; **chưa phải coding gate**  
**Thiết kế nguồn:** `Phase_2B_v1.3.md`, đã chốt `APPROVED_DESIGN_CONDITIONAL`; các đề xuất `P2B-DR` và interfaces chưa ACK vẫn là `PROPOSED_FOR_ACK`. Đối chiếu cả `Phase_2A_v0.9.md`, `Phase_2C_v0.9.md`, `Phase_2D_v0.9.md`, `Phase_2E_v1.8.md`.  
**GitHub snapshot:** PR [#39](https://github.com/SE2026-BC-04/gpu-resource-marketplace/pull/39), HEAD `6788505cbb68e09ad08ea2b96728bc6c69e8a32e`, base `main@1d8b1b2c52b759d99a072c3d0d889b375083a8c4`, **Draft/open/unmerged** tại thời điểm kiểm tra. PR #42 đã merge **vào nhánh #39**, **chưa phải** merge #39 vào `main`. CI #39 xanh cho Phase 1, **không phải Phase 2 DB PASS**.  
**Nguyên tắc:** Không thay đổi GitHub/code/database vì việc review này; không chạy migration, không cấp thêm quyền và không dùng DB persistent để thử nghiệm.

## 1. MỤC TIÊU — TẠI SAO TV2 CẦN LÀM PHẦN NÀY?

Nhiệm vụ TV2 là tạo **lớp tin cậy bền vững** của Phase 2 cho bốn owner còn lại. Sau khi Phase 2 được triển khai và kiểm thử, PostgreSQL phải là nguồn sự thật về trạng thái Job/Attempt/Allocation, Outbox/Inbox, Signed Result và Reputation.

**Năm kết quả bắt buộc:**

1. **Cấp phát không sai và không vượt sức chứa:** quyết định FIFO của TV4 được thực hiện trong một transaction khóa đúng Listing → Job; một lần cấp phát hợp lệ sinh **một** Allocation, **một** Attempt và **một** Outbox; thất bại thì không có hiệu ứng một phần.
2. **Giao vận không mất dữ liệu và có thể retry:** Outbox có claim/lease/fencing; HTTP ACK mất hoặc Manager restart không tạo Job/Allocation/Attempt mới. Inbox lưu nguyên bytes và timestamp tin cậy để tiếp tục xử lý sau crash.
3. **Kết quả và danh tiếng chỉ có hiệu lực đúng một lần:** Signed Result được nhận theo bằng chứng đã xác minh; Job terminal, GPU release, Inbox processed, Contribution và lifetime aggregate là một commit, không thể tăng reputation hai lần.
4. **Phân quyền DB nghiêm ngặt:** API và Manager dùng đúng login `gpm_api_app` / `gpm_manager_app` và nhóm grant của mình; Simulator không có PostgreSQL DSN, account, ORM/session hay quyền đọc protected reference. Dữ liệu chữ ký gốc và oracle không rò rỉ qua public DTO.
5. **Khôi phục đúng khi lỗi:** lost HTTP ACK, rollback, lỗi PostgreSQL, COMMIT outcome unknown, async cancellation và kết quả đến sát deadline đều có bằng chứng kiểm thử trên PostgreSQL thật.

**Định nghĩa hoàn thành:** Schema/ACL chính xác + các transaction/UoW có contract được owner/consumer ACK + test PostgreSQL hai connection có barrier + CI trên HEAD cụ thể + handoff code/migration/rollback rõ + human review. Không đồng nhất `APPROVED_DESIGN_CONDITIONAL` với `PASS` hoặc cho phép merge.

## 2. TV2 LÀM GÌ VÀ KHÔNG LÀM GÌ?

| Phạm vi | Người quyết định nghiệp vụ | Phần TV2 trực tiếp sở hữu |
|---|---|---|
| Chọn Job FIFO để cấp phát | TV4 | Truy vấn/khóa Job đầu thực tế, atomic `TX-ALLOCATE`, dữ liệu trả về cho TV1 |
| Vòng lặp Scheduler/Dispatcher/Finalizer | TV1 | Port DB, UoW, due-query, lease/CAS, transaction/result typing |
| Auth callback, parser, chữ ký | TV3 | Lưu raw envelope, trusted key lookup, unique Inbox, clock/ACL; không tự xác minh Ed25519 |
| Chạy mô phỏng và ký | TV5 | Không viết Simulator; chỉ DB/Outbox/Inbox integration boundary |
| Quy tắc Completed/Failed/Reputation | TV5 | `TX-FINALIZE` và `TX-DEADLINE-FALLBACK` atomic theo policy TV5; không tự đổi phân loại |
| Quyết định key compromise và cold restart conflict | Nhóm trưởng, TV3/TV5 | Góp ý schema/ACL/test; **không tự phê duyệt chính sách mới** |

**Không thuộc TV2:** viết ba Manager loops thay TV1, tự sửa chính sách FIFO của TV4, tự sửa ADR-004 V1 của TV3, viết Simulator/Result Finalizer policy của TV5, thêm bảng thứ bảy, làm Phase 3 Disputes/Retention, tạo service/broker mới, mở rộng `/health/ready` Phase 1 khi chưa có owner L2 decision.

## 3. NGUỒN PHẢI ĐỌC VÀ HIỆN TRẠNG CODE

### 3.1. Nguồn chuẩn được nhóm trưởng chốt

Chỉ dùng các file `Phase2_FINAL_5_FILES_2026-11-07/Phase_2A_v0.9.md` đến `Phase_2E_v1.8.md`, cụ thể Phase 2B §§2.1–2.9, Appendix `PR39-B` và `P2B-DR`; đối chiếu Database Design §§9/11, ADR-002/003/004/005, API Contract §13 và báo cáo `REVIEW_CROSS_PHASE_CONSISTENCY_v1.0.md`.

**Lưu ý trạng thái:** các đoạn văn lịch sử trong tài liệu Phase 2 có thể dùng chữ `OPEN` cũ; quyết định đã được chốt có điều kiện ở register của phiên bản mới nhất chiếm ưu tiên. Không tự đóng `PENDING_ACK` chỉ vì nhóm trưởng đã duyệt cấp thiết kế.

### 3.2. Source code Phase 1 hiện có trên PR #39, KHÔNG làm lại

| Đường dẫn trên repository | Cần TV2 kiểm tra/tái sử dụng |
|---|---|
| `backend/migrations/versions/0001_phase1b_baseline.py` | 10 bảng nền; `jobs.enqueue_seq`, `worker_public_keys`, `worker_reputation_aggregates`, `audit_events`, `simulation_references` |
| `backend/migrations/versions/0002_phase1b_grants.py` | Hai nhóm quyền `gpm_api_rw`, `gpm_manager_rw`; logins tương ứng; không cấp PUBLIC quyền rộng |
| `backend/migrations/versions/0003_phase1b_jobs_guard_update.py` | Job lifecycle trigger D2; phải bảo tồn và kiểm thử Manager transitions mới |
| `backend/migrations/versions/0004_phase1b_jobs_guard_delete.py` | Guard xóa lịch sử D3; Phase 3 phải mở rộng có kiểm soát, không tự vô hiệu hóa |
| `backend/migrations/versions/0005_listing_d7.py` | Listing guard D7; **HEAD quan sát** hiện có revision này, **không hard-code làm Phase 2 parent** |
| `backend/src/gpu_marketplace/repositories/{jobs,job_submit,listings,commit_outcome}.py` | Native-role UoW, Listing-first SQL, rollback/unknown COMMIT phân loại; tránh copy logic sai/khác |
| `backend/src/gpu_marketplace/common/{database,db_roles}.py` | Pool, native DB login, role bootstrap; không dùng DB owner trong runtime |
| `backend/tests/test_phase1_runtime_http_postgres_e2e.py` | Phase 1 E2E; còn `bootstrap_roles(... rotate_password=True)` mà chưa thấy sử dụng helper restore ngay trong file này |
| `backend/tests/{role_credentials,test_role_credentials_restore,test_auth_session_browser_e2e}.py` | Phần được PR #42 thêm vào nhánh #39; Auth browser E2E có `restored_login_role_credentials`, **chưa chứng minh tất cả test cũ đã dùng helper** |
| `tools/{verify_alembic_head,verify_runtime_roles}.py` | Preflight Alembic head và proof role ở môi trường phù hợp |

**GitHub baseline gate:** PR #39 vẫn Draft; `main` chưa nhận PR #39. Chỉ lấy **accepted main SHA/head** làm migration parent sau khi đủ điều kiện, hoặc ngoại lệ được nhóm trưởng phê duyệt riêng. Không chạy tự động sau khi thấy PR CI xanh.

## 4. PHẠM VI SCHEMA — ĐÚNG 6 BẢNG MỚI

| Bảng | Dữ liệu và ràng buộc bắt buộc | Writer / reader |
|---|---|---|
| `execution_attempts` | `attempt_id` UUIDv4 PK; `UNIQUE(job_id)`, ràng buộc FK/composite; `started_at`, `finish_due_at`, `hard_deadline_at = finish_due_at+120s` | Manager INSERT, API đọc giới hạn để bind callback |
| `allocations` | `UNIQUE(job_id)`, FK Job↔Listing, `gpu_count>0`, `ACTIVE → RELEASED` đúng một lần, `released_at` iff RELEASED | Manager INSERT + UPDATE hạn chế |
| `execution_outbox` | `(attempt_id,event_type)` unique, `event_id`, immutable payload, `lease_owner`, `lease_until`, `lease_version`, due/retry/ACK timestamps | Manager only; CAS/fenced writes |
| `result_inbox` | Unique nonnull `result_id`, bound pair FK, exact `original_envelope_raw bytea`, hash 32 bytes, `received_at` DB after Job lock, `PENDING/ACCEPTED/REJECTED` | API durable INSERT; Manager processing state |
| `signed_results` | `UNIQUE(job_id)`, historical public key `(worker_id,key_id)` FK RESTRICT, immutable original envelope + JCS bytes + signature 64 bytes | Manager INSERT only; API chỉ safe projection đã duyệt |
| `job_reputation_contributions` | PK `job_id`, category `SUCCESS/WORKER_FAULT/NONE`; Phase 2 `correction_version=0`, `corrected_by_dispute_id IS NULL`, `effective=initial` | Manager INSERT once; dispute correction **Phase 3** |

**Tổng dự án:** 18 logical tables = 10 Phase 1 + 6 Phase 2 + 2 Phase 3. `gpu_listings`, `jobs`, `worker_public_keys`, `worker_reputation_aggregates`, `simulation_references`, `audit_events` đã tồn tại: **không tạo lại**. `disputes` và `retention_exceptions` **không tạo sớm**.

**Đặc biệt về FK Phase 3:** để `job_reputation_contributions.corrected_by_dispute_id` nullable **không có FK** sang bảng chưa tồn tại, nhưng đặt CHECK tạm:
`correction_version=0 AND corrected_by_dispute_id IS NULL AND effective_category=initial_category`. Phase 3 mới thay CHECK có kiểm soát và gắn composite FK.

## 5. CÔNG VIỆC TV2 — CÓ THỨ TỰ, ĐẦU RA CỤ THỂ

### A. Sáu nhiệm vụ trước khi code (`PRE_CODE`)

| ID | Mục tiêu và thao tác phải thực hiện | Đầu ra phải nộp / người ACK |
|---|---|---|
| **TV2-P2B-01** | **Đóng băng Phase 1 baseline.** Xác nhận PR #39 trên `main`, accepted SHA, `alembic heads`, `alembic_version`, kiểm tra D1/D2/D3/D7, cùng roles/ACL thực tế. Nếu chưa merge: `BLOCKED` hoặc ngoại lệ baseline được lead duyệt. | `DB_BASELINE.md` gồm SHA/main, migration graph, current_user/session_user, CI links; **TV1 + TV2 ACK** |
| **TV2-P2B-02** | **Chốt thiết kế sáu bảng.** Lập ma trận cột/type/NULL/default/index/PK/FK/UQ/CHECK, thứ tự phụ thuộc, Phase3 FK deferred, transition constraints; so với ORM existing và Database Design §9. | `PHASE2_SCHEMA_MATRIX.md`, `MIGRATION_DEPENDENCIES.md`; **TV1/3/4/5 ACK** đúng cột tiêu thụ |
| **TV2-P2B-03** | **Chốt quyền và triggers.** Lập exact role/table/column grant; chứng minh API duplicate-read không thể hiểu lầm SELECT-column là SELECT-row. Quyết định đường so raw-byte `result_id` hạn chế: function có scope được review hoặc boundary đọc được phê duyệt. Nêu trigger tối thiểu; không cấp rộng để ORM dễ chạy. | `PHASE2_ROLE_GRANTS.md`, `INBOX_DUPLICATE_PRIVILEGES.md`, `GUARDS_TRIGGER_PLAN.md`; **TV3+TV5** cho Inbox, **TV1** cho activation |
| **TV2-P2B-04** | **Đóng băng toàn bộ transaction ports.** Định nghĩa inputs/typed outputs, transaction owner, lock order, duplicate/error/unknown-commit semantics cho `TX-ALLOCATE`, `OUTBOX`, `INGRESS`, `FINALIZE`, `FALLBACK`; không cho repository tự commit. | `P2B_UOW_INTERFACES.md`, 9 interface `B-IF-01..09`; **TV1/3/4/5 ACK theo vai trò** |
| **TV2-P2B-05** | **Xác nhận phụ thuộc an toàn chưa giải quyết.** TV4+TV2 sửa lỗi `reserved_gpu_count` thành **`allocated_gpu_count` trong pseudocode** (bằng errata có review, không sửa schema). TV3/TV5 chốt key readiness/rotation, receipt type, cold restart policy; lead xử lý X-02/X-03. TV2 ghi blocked items, không tự quyết định. | `OPEN_DECISION_REGISTER.md`, errata X-01; ACK TV1/3/4/5 và lead khi đúng thẩm quyền |
| **TV2-P2B-06** | **Thiết kế test và tài nguyên.** Chọn PostgreSQL disposable one-shot hoặc fixture restore credentials có bằng chứng, barrier 2+ sessions cho cả hai commit orders, lock/statement timeout, pool/executor budget với TV1, test IDs+PASS oracle; phân biệt Phase 1 PASS với Phase 2 NOT_RUN. | `P2B_TEST_MATRIX.md`, `DB_TEST_ISOLATION.md`, `RUNTIME_BUDGET.md`; TV1+TV2 ACK |

**Gate:** A1–A6 chỉ là công việc lập kế hoạch/tài liệu, không phải quyền sửa GitHub/DB. Nhóm trưởng phải cho phép code Phase 2B **bằng quyết định riêng** ghi scope, branch, base SHA và reviewers.

### B. Mười một nhiệm vụ triển khai (`IMPLEMENT_AFTER_AUTH`, chỉ sau coding gate)

| ID | TV2 phải code gì chính xác? | PASS oracle / sản phẩm |
|---|---|---|
| **TV2-P2B-07** | Viết **một Alembic schema revision** tạo đúng 6 bảng theo dependency, lấy `down_revision` từ accepted `main` head. Ràng buộc CHECK, FK, unique/index; migration phải atomic. Tài liệu hóa safe upgrade/downgrade trên DB disposable, không rollback hủy dữ liệu thật tùy tiện. | 6 bảng đúng, không có `disputes`; một schema revision, không drift, fresh upgrade / guarded downgrade PASS |
| **TV2-P2B-08** | Triển khai GRANT/REVOKE theo cột và guard/trigger cần thiết trong revision chính hoặc revision bảo vệ kế tiếp đã được review. Kiểm tra SQLAlchemy `RETURNING`, server defaults và sequence rights dưới role đăng nhập thật; chặn runtime khi schema/ACL chưa đồng bộ. | API INSERT Inbox nhưng không raw oracle SELECT; Manager only có quyền cần thiết; không owner-role/superuser runtime; các write trái quyền fail |
| **TV2-P2B-09** | Viết các **transaction-scoped UoW** dùng một `Session`/logical transaction, `READ COMMITTED`, native-role check, rollback/close an toàn và typed errors. Không chia một UoW qua thread; không commit trong repository. Kế thừa phân loại `commit_outcome.py`, finite conflict retry và reconcile unknown COMMIT. | Không dirty partial data; cancellation không bỏ dở sync SQL; `40003`/mất kết nối không trigger duplicate mutation |
| **TV2-P2B-10** | Triển khai **`TX-ALLOCATE`**: khóa Listing, lấy **FIFO-head thật** bằng `enqueue_seq` và `FOR UPDATE` (không `SKIP LOCKED` Job); kiểm `ACTIVE`, capacity; một commit ghi Job RUNNING + Listing counter + Allocation + Attempt + immutable Outbox. | Khi J1 không vừa, J2 không được vượt; khi 2 Manager race, 1 Allocation/Attempt/Outbox; `allocated_gpu_count` đúng |
| **TV2-P2B-11** | Triển khai **`TX-OUTBOX-CLAIM/ACK/RETRY`**: scan due bounded, Outbox-only claim 30s, stable `event_id/attempt_id/payload`, `lease_version` fencing CAS; lưu ACK/next retry đúng thời điểm; không giữ DB lock qua HTTP. | Stale lease UPDATE = 0 rows; 202 ACK không terminalize; retry RUNNING trên PAUSED vẫn hợp lệ, không tạo Allocation mới |
| **TV2-P2B-12** | Triển khai **`TX-INBOX-INGRESS` adapter** cho TV3: token auth ngoài UoW; strict envelope bounded; lookup duplicate đã lưu theo đúng raw bytes và bound context; cho new candidate khóa Listing → Job, lấy `clock_timestamp()` sau khóa; chỉ INSERT khi `received_at < hard_deadline_at`; commit trước HTTP 202. UNIQUE loser rollback + re-read winner ở transaction mới. | Cùng `result_id`+cùng bytes/context => 202 DUPLICATE; body khác => 409; late/exact deadline không được nhận; replay cũ sau terminal không đổi timestamp |
| **TV2-P2B-13** | Triển khai **candidate query/state UoW**: locator không khóa, recheck theo Listing → Job → Allocation → Inbox; thứ tự `(received_at,id)`; xử lý nhiều `result_id` cùng Attempt; batch bounded nhưng có bằng chứng đã quét hết candidate đúng hạn trước fallback; sau terminal có housekeeping non-winner đã ACK. | Valid candidate ở batch sau không bị timeout sai; không lock Inbox trước Listing; non-winner không tạo business effects |
| **TV2-P2B-14** | Triển khai **`TX-FINALIZE`** dựa trên verified receipt TV3 và policy TV5, tái kiểm tra DB row/bytes/context/Job RUNNING dưới lock. Một commit ghi Signed Result, Job terminal, Allocation release, Listing decrement, Inbox processed, contribution và Worker lifetime aggregate. | `SUCCESS` +1 successful; `WORKER_FAULT` +1 fault; `JOB_FAULT` category NONE và 0 counters; replay/crash vẫn một hiệu ứng |
| **TV2-P2B-15** | Triển khai **`TX-DEADLINE-FALLBACK`** và reconciliation: sau hard deadline, kiểm hết Inbox on-time đã commit; nếu không có valid result mới `FAILED/SYSTEM_FAULT`, một lần release, không Signed Result/contribution; phân biệt rejected receipt với thiếu receipt. | Timeout không ghi đè result hợp lệ, không phạt Worker; crash trước/sau COMMIT khôi phục đúng |
| **TV2-P2B-16** | Viết và chạy **PostgreSQL thật** test migration/GRANT/constraints, two-session barriers cho race, failure injection trước/sau COMMIT, role credentials, pool/queue limits, key historical FK. Có CI trên exact reviewed SHA và observable fixtures. | Tất cả test mandatory PASS (không skipped/xfail nhầm), report Git SHA/DB revision/role/2 commit orders; Phase 1 regressions vẫn xanh |
| **TV2-P2B-17** | **Bàn giao có review:** source, migration graph, exact grants, typed ports, tested SQLSTATE handling, restart/rollback plan, CI, performance evidence, owner/consumer ACK và independent human review; scope một branch/work-package. | `TV2-P2B HANDOFF` hoàn chỉnh, `ACK_COMPATIBLE` hoặc `ACK_WITH_ACTIONS` trung thực; không tự merge hay duyệt PR mình viết |

**Không yêu cầu TV2 làm thay:** TV1 viết Supervisor/HTTP call; TV3 ký/xác minh Ed25519; TV4 tính chính sách FIFO/fairness; TV5 deterministic simulator, business category và Reputation policy. TV2 chỉ hiện thực transaction atomic đáp ứng policy đã ACK.

## 6. ĐẶC TẢ GIAO DỊCH — CÁC LỖI NGHIÊM TRỌNG PHẢI TRÁNH

### 6.1. `TX-ALLOCATE` — 1 Listing, 1 Job đầu, 1 commit

```text
BEGIN READ COMMITTED (Manager role)
  LOCK Listing L FOR UPDATE
  if L.status != ACTIVE: no-op
  SELECT oldest QUEUED Job by enqueue_seq for L
    ORDER BY enqueue_seq LIMIT 1 FOR UPDATE  # NO SKIP LOCKED for head
  if free_gpu < head.requested_gpu_count: no-op, do not skip head
  trusted_start = DB clock after locks
  UPDATE gpu_listings.allocated_gpu_count += gpu_count
  UPDATE jobs SET status=RUNNING, started_at=trusted_start
  INSERT allocations ACTIVE(job_id UNIQUE)
  INSERT execution_attempts(attempt_id stable, job_id UNIQUE, due, deadline)
  INSERT execution_outbox(event_id stable, attempt_id, payload, due)
COMMIT
# only after COMMIT may TV1/Simulator HTTP dispatch run
```

**Đổi tên đúng:** `gpu_listings.allocated_gpu_count`, **không có** `reserved_gpu_count`. Chỉ sửa qua errata X-01 có TV2+TV4 ACK, không thêm cột.

### 6.2. `TX-INBOX-INGRESS` — 202 = dữ liệu đã commit, không phải đã verified

- Auth token đúng direction và parse bounds **trước** khi gọi DB port.
- Retained exact `result_id` duplicate nên được nhận biết ngay cả sau khi Job terminal; so sánh **full original raw bytes + bound context**, không dùng mỗi SHA-256.
- New candidate dùng locator không khóa rồi lock Listing → Job, kiểm current Attempt/Worker/Listing, lấy DB `clock_timestamp()` **sau lock**; đúng hạn iff `received_at < hard_deadline_at`.
- Unique conflict: rollback complete UoW, dùng transaction mới đọc bản winner; giống bytes/context => 202 DUPLICATE, khác => 409; uncertain COMMIT cần reconcile trước khi kết luận.
- Không lưu `PENDING` cho token sai, body không parse/bind được hoặc callback đến muộn; không cập nhật `received_at` khi replay.
- Column SELECT trên PostgreSQL **không giới hạn theo hàng**. TV2+TV3+TV5 phải ACK cách đọc/so bytes giới hạn quyền (có thể là reviewed constrained function, không tự động làm thêm service).

### 6.3. `TX-FINALIZE` / `TX-DEADLINE-FALLBACK` — thứ tự Inbox và exactly once

1. Không bao giờ giữ Inbox row lock rồi chờ khóa Listing/Job. Locator không khóa; transaction quyết định khóa `Listing → Job → Allocation → Inbox → Contribution → Aggregate` theo hợp đồng chung.
2. Có nhiều result IDs của cùng Attempt: các Inbox candidates là riêng biệt. Đọc candidate đúng hạn theo `(received_at, inbox.id)`; một valid candidate đầu tiên thắng. Signature invalid: ghi rejected và tiếp tục, **không** kết luận Job failed sớm.
3. Nếu batch bounded kết thúc khi vẫn còn candidate chưa kiểm tra, trả `CONTINUE/DEFER`; chỉ fallback sau khi hoàn tất kiểm chứng toàn bộ on-time candidates đã commit. Thời điểm `received_at == hard_deadline_at` là muộn.
4. Một commit của TV2 thực thi policy TV5: accepted raw signed proof + terminal Job + một release + một contribution nếu eligible + aggregate delta + inbox status. Job terminal hoặc contribution đã tồn tại => reconciliation/no-op, không double effect.
5. `SYSTEM_FAULT`: không tạo Signed Result hay Reputation contribution, không làm giảm/lệch aggregate. `FAILED/JOB_FAULT` có accepted proof, tạo category `NONE`, counter delta bằng 0.

### 6.4. `TX-OUTBOX` và COMMIT unknown

- Lease 30 giây; `UPDATE ... WHERE event_id=:id AND lease_version=:observed AND owner/state/due predicates RETURNING ...`. Stale worker không được ACK/RETRY event của worker khác.
- Backoff do ADR-005: `2,4,8,16,30,30...` giây; poll mặc định 2 giây; receipt repair probe `finish_due_at+10s`; hard deadline `finish_due_at+120s`; không thay đổi bằng tay vì saturation.
- Lỗi `23xxx` và rollback definite được phân loại riêng (thường không retry vì constraint); `40001`, `40P01` chỉ cho phép retry cả UoW hữu hạn khi đáp ứng điều kiện; `40003`, mất kết nối/ACK hoặc lỗi lạ khi COMMIT => **UNKNOWN**, đọc/reconcile DB trước khi retry mutation.
- Async cancellation trong Manager **không đồng nghĩa** sync SQL thread đã rollback; TV1 phải đợi/resolve in-flight UoW trong bounded shutdown. TV2 không dùng một Session across workers.

## 7. POSTGRESQL PRIVILEGES, KEY VÀ AUDIT

**API (`gpm_api_app`):** authenticated callback được INSERT Inbox khi đủ điều kiện; SELECT `execution_attempts` cho binding có hạn; **không UPDATE `signed_results`, `worker_reputation_aggregates`, `allocations`, `execution_outbox`**; protected `simulation_references` vẫn chỉ INSERT (đã được Phase 1 cho phép), không đọc raw oracle. Một safe public result projection được thiết kế riêng; không suy ra API được SELECT toàn bộ signed raw evidence.

**Manager (`gpm_manager_app`):** INSERT Attempt, Allocation, Outbox, Signed Result, Contribution; UPDATE có giới hạn trên Outbox lease/tracking, Inbox processing, Allocation state, Job terminal, Listing counter và reputation aggregates. Các quyền cụ thể chỉ có hiệu lực sau khi SQL/ORM được kiểm thử với native login; không dùng DB owner trong runtime.

**Simulator:** không DB URL, SQL role, application ORM hoặc protected reference. Private Ed25519 key ở Simulator-only secret provisioning; PostgreSQL lưu **public key bytes 32**, Signed Result FK historical key. TV2 không tự quyết định rotation/compromise policy; phải ACK với TV3+TV5+lead.

**Audit:** Phase 1 `audit_events` đã tồn tại. TV2 cung cấp transaction-compatible persistence/narrow rights cho các sự kiện đã được owner phê duyệt; không đưa raw token/private key/ground truth vào audit. Các finding P2 audit của Phase 1 phải được TV1/owner triage; không tự đóng khi Phase 2 migration chạy thành công.

**Guards:** giữ các existing `trg_jobs_guard_update` D2, `trg_jobs_guard_delete` D3 và `trg_gpu_listings_guard_update` D7; không dùng superuser/`SET ROLE` để giả role proof. Trigger mới chỉ khi PK/FK/CHECK/GRANT không đủ, và không cài DELETE-trigger vô điều kiện cho Signed Results khiến Phase 3 retention cleanup hợp lệ không thể chạy.

## 8. GIAO DIỆN PHẢI XÁC NHẬN (`B-IF-01..09`)

| ID | Cặp owner/consumer | Cần freeze chính xác | Trạng thái |
|---|---|---|---|
| `B-IF-01` | TV1 ↔ TV2 | accepted main SHA + Alembic head/version + native roles/grants + preflight | `PENDING_BASELINE` |
| `B-IF-02` | TV2 ↔ TV3 ↔ TV5 | same result_id/bytes/context duplicate; UNIQUE collision loser; status 202/409 | `PENDING_ACK` |
| `B-IF-03` | TV2 ↔ TV3 | cách so raw Inbox hạn chế quyền, không nhầm SELECT-column là SELECT-row | `PENDING_ACK` |
| `B-IF-04` | TV2 ↔ TV3 | `received_at` DB after Job lock, ingress eligibility và trusted identity | `PENDING_SQL_DESIGN` |
| `B-IF-05` | TV1 ↔ TV2 ↔ TV3 ↔ TV5 | candidate order/multi-batch, post-terminal housekeeping, progress marker | `PENDING_ACK` |
| `B-IF-06` | TV1 ↔ TV2 ↔ TV4 ↔ TV5 | `allocate_one_listing`, Outbox lease CAS, PAUSED retry, data returns/errors | `PENDING_ACK` |
| `B-IF-07` | TV1 ↔ TV2 ↔ TV5 | Finalization/Release/Contribution atomic, rollback và unknown COMMIT | `PENDING_ACK` |
| `B-IF-08` | TV2 ↔ TV3 ↔ TV5 | key readiness, K1/K2 historical FK, rotation/compromise restrictions | `PENDING_ACK / OWNER_DECISION` |
| `B-IF-09` | TV1 ↔ TV2 | PostgreSQL disposable, role restoration, pool/executor, timeouts, shutdown | `PENDING_PARAMS / TEST` |

**Đề xuất ports** (minh họa để đóng băng sau ACK, **không phải chữ ký Python đã phê duyệt**):

```text
allocate_one_listing(listing_id) -> Allocated(attempt_id, event_id, job_id)
                                  | Blocked(reason) | Noop | CommitOutcomeUnknown

claim_due_outbox(batch_limit) -> list[FencedOutboxClaim]
ack_or_retry(event_id, observed_lease_version, owner, response_class)
    -> FencedUpdated | StaleClaimNoop | CommitOutcomeUnknown

ingest_signed_result(raw_bytes, parsed_untrusted_context)
    -> Stored(result_id, inbox_id) | ExactDuplicate(result_id)
     | Collision | Ineligible | CommitOutcomeUnknown

iter_eligible_inbox(job_id, cursor, bound) -> Batch(candidates, has_more)
finalize_one(verified_receipt_identity, job_id)
    -> Finalized(job_id) | AlreadyTerminalNoop | RejectedCandidate | CommitOutcomeUnknown

deadline_fallback(job_id, complete_candidate_scan_proof)
    -> SystemFaultFinalized | ContinueCandidateScan | AlreadyTerminalNoop
```

**Ràng buộc:** TV2 cung cấp port giao dịch; TV4 không tự commit trong pure FIFO; TV3 pure verifier không tự commit; TV5 domain rules không tự mở SQL Session; TV1 orchestration không chia Session giữa tasks.

## 9. TEST VÀ TIÊU CHÍ PASS (TẤT CẢ PHASE 2 `NOT_RUN`)

| Test ID | Tình huống sau khi code | Điều kiện PASS bắt buộc |
|---|---|---|
| `P2B-DRT-01` | Upgrade accepted Phase 1 → Phase 2 trên disposable PG | Đúng 6 bảng, 1 schema revision, không lệch Alembic head |
| `P2B-DRT-02` | API/Manager native role và ORM emitted SQL | SELECT/INSERT/UPDATE đúng whitelist; negative oracle/evidence read, DDL/DELETE bị chặn |
| `P2B-DRT-03` | 2 callback đồng thời cùng result_id/cùng bytes | 1 Inbox; cả 2 được 202, original bytes/received_at giữ nguyên |
| `P2B-DRT-04` | Same result_id khác bytes hoặc context | 409; không overwrite/second eligible row |
| `P2B-DRT-05` | Retained callback duplicate sau terminal/lost ACK | 202 DUPLICATE, không thêm event/effect/timestamp |
| `P2B-DRT-06` | Invalid Inbox batch 1, valid đúng hạn ở batch 2 | Xử lý valid trước fallback; không false SYSTEM_FAULT |
| `P2B-DRT-07` | 2 result_id cùng Attempt, 2 concurrent finalizers | 1 accepted result/job, 1 release, 1 contribution/delta |
| `P2B-DRT-08` | Stale Outbox lease takeover + PAUSED Listing | Stale update = 0; same event/attempt; retry không thêm allocation |
| `P2B-DRT-09` | Cancel↔Allocate + 2 Manager + capacity | Hai commit orders legal, FIFO giữ, counter đúng SUM(active allocations) |
| `P2B-DRT-10` | Crash giữa TX-FINALIZE, replay sau commit | Không partial effect, mỗi business effect đúng 1 lần |
| `P2B-DRT-11` | Lost COMMIT ACK và async cancellation | Không retry mù; reconcile đúng, Session không chia thread |
| `P2B-DRT-12` | K1 retired/K2 active với signed proof cũ | Key cũ còn verify, không thể delete khi receipt đang tham chiếu |
| `P2B-DRT-13` | Guarded PG role-password rotation + test teardown lỗi | Cluster disposable phá hủy hoặc restore có proof, không đổi shared DB |
| `P2B-DRT-14` | Executor/DB pool/lock saturation | Queue bounded, timeout/metrics có chứng cứ, không starve Finalization |
| `P2B-DRT-15` | Attempt to fake Phase 3 correction | CHECK/grants chặn `correction_version=1`, dispute FK chưa tồn tại |

**Tối thiểu chứng cứ cho mỗi test:** exact Git commit, Alembic revision, PostgreSQL instance (disposable), native `current_user/session_user`, fixed fixture, fake/trusted DB-clock setup, 2 separate SQL sessions & barrier for race, stimuli, before/after SQL rows, expected vs observed, test stdout/CI URL, verdict `PASS/FAIL/BLOCKED/ERROR/NOT_RUN`. Mock-only không chứng minh lock/concurrency.

**Regression bắt buộc:** Phase 1 `Submit↔Pause` và `Submit↔Resize` phải có cả hai commit orders; PR #39/42 có CI xanh nhưng không tự chứng minh đã đóng mọi thread audit/race. Retention/Dispute Phase 3 chỉ là compatibility design, không chạy Phase3 logic trong Phase2 nghiệm thu.

## 10. ĐIỀU KIỆN QUA GATE VÀ CHECKLIST BÀN GIAO

### G0 — Phê duyệt handoff và baseline

- [ ] Nhóm trưởng phê duyệt file handoff TV2 này là bản giao nhiệm vụ có điều kiện.
- [ ] PR #39 được chấp nhận vào main hoặc có baseline exception có văn bản; accepted main SHA và migration head/version xác định.
- [ ] Các blocker cross-file `X-01..X-09` liên quan DB được phân loại, quyết định nào cần lead thì chưa tự xử lý.
- [ ] Các `B-IF-01..09` nhận ACK producer/consumer theo **file SHA**, không chỉ theo PR.

### G1 — Coding authorization (riêng, không suy ra từ G0)

- [ ] Nhóm trưởng cho phép Phase 2B code với scope, branch, base SHA, reviewers, db test cluster và rollback policy.
- [ ] Không tự áp migration trên persistent/shared DB, không đổi owner DSN, không tự mở rộng `/health/ready` và không tự merge.

### G2 — Implementation + DB acceptance

- [ ] Sáu bảng/schema revision và toàn bộ grants/triggers được review; fail-closed preflight.
- [ ] Native role negative tests và PostgreSQL multi-session/concurrency tests PASS trên exact HEAD.
- [ ] Finalizer/Inbox/Outbox/cancellation/unknown COMMIT được kiểm chứng; CI Phase 2 PASS riêng.
- [ ] Có independent human review, ACK của TV1, TV3, TV4, TV5 trong phạm vi liên quan.

### G3 — Release

- [ ] Quyết định merge/release riêng, không lấy thiết kế/handoff approval thay thế.
- [ ] Phân biệt Phase 2 sandbox nghiệm thu với Phase 3 rollback/retention/Dispute và production hardening.

**Template bàn giao cuối của TV2:**

```text
[TV2-P2B IMPLEMENTATION HANDOFF]
Reviewed design version/SHA:
Owner-approved coding decision:
Branch / PR / exact HEAD:
Accepted Phase 1 main SHA:
Alembic parent / schema revision(s) / target DB version:
Six-table schema diff and checks/indexes:
Grant/trigger matrix and native role current_user/session_user:
UoW ports + lock/commit contract links (B-IF-01..09):
Database test environment safety and role credential restoration:
MIG/ACL/FK/DBTX/P2B-DRT test evidence URLs + before/after rows:
Phase 1 regression evidence:
Open P0/P1/P2/P3 / approved deferrals:
Reviewer ACK (source+consumer + exact version/SHA):
Disposition: ACK_COMPATIBLE | ACK_WITH_ACTIONS | BLOCKED
```

## 11. REVIEWER NOTES — KHÔNG ĐƯỢC HIỂU NHẦM

- **Có điều kiện được duyệt:** mục tiêu/scope 6 bảng, staged Alembic/ACL policy và transaction UoW strategy.
- **Chưa duyệt:** exact SQL/function signatures, raw duplicate read boundary, key-incident policy, conflict sau cold restart, thông số tài nguyên, merge/release.
- **Đã có code Phase 1:** migrations 0001..0005, D1/D2/D3/D7, TX-SUBMIT/CANCEL/read; không tính là TX-ALLOCATE/OUTBOX/INBOX/FINALIZE Phase 2 đã có.
- **Chưa có test Phase 2 PASS:** mọi `P2B-DRT-*` đang `NOT_RUN`.
- **Nguyên tắc nhánh:** một work package/nhánh rõ ràng theo nhóm, không tự tạo nhiều nhánh nhỏ, không sửa PR #39 nếu không có nhiệm vụ hợp lệ.

**Disposition:** `ACK_WITH_ACTIONS / AWAITING_OWNER_APPROVAL`. File này đủ chi tiết để review/giao chuẩn bị nhưng **không tự cho phép triển khai Phase 2B**.
