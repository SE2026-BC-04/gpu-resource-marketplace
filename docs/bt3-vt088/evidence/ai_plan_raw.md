# BT3 — AI implementation plan (raw, unedited)

- Tool: Claude Code CLI 2.1.319, headless (`claude -p`), model `claude-opus-5-5`, fresh session `e8e72cfc-ab45-4d39-958a-7d81e605837f`
- Run: 2026-11-07T15:54:15Z → 2026-11-07T15:56:16Z (116.8 s, 15 turns)
- Context isolation: working directory was a separate folder containing ONLY the allowed files copied from `1d8b1b2` (identity/, domain/identity.py, test_identity_normalization.py, test_identity_passwords.py); tools limited to Read/Glob/Grep (no Bash/Edit/Write/Web).
- Prompt: verbatim from `BT3_prompt_plan.md` (section Prompt).

## Prompt

```
Bạn là coding agent. KHÔNG viết hay sửa code trong lượt này; chỉ lập implementation plan.

Chỉ được đọc đúng các file sau, không đọc file nào khác trong repository:
- backend/src/gpu_marketplace/identity/  (toàn bộ thư mục)
- backend/src/gpu_marketplace/domain/identity.py
- backend/tests/test_identity_normalization.py
- backend/tests/test_identity_passwords.py

Mini spec:
- Goal: thêm chức năng import tài khoản hàng loạt (login_name, password, role_code, status).
- Scope: một hàm/service Python import một danh sách bản ghi và trả về báo cáo; không có giao diện.
- Constraints: bản ghi lỗi không được làm mất các bản ghi hợp lệ; dùng lại quy tắc chuẩn hoá
  login_name và hàm băm mật khẩu hiện có; không log mật khẩu hay hash.
- Acceptance: lô N bản ghi có K bản ghi lỗi thì lưu đúng N−K tài khoản và báo rõ bản ghi nào lỗi,
  vì sao; không báo thành công cho bản ghi chưa thực sự được lưu.
- Evidence: unit test, property-based test (Hypothesis), integration test với PostgreSQL.
- Phi chức năng: 40 tác vụ import đồng thời, p95 ≤ 1,5 giây.

Hãy trả về plan gồm:
1. Các file sẽ tạo/sửa và lý do từng file.
2. Interface (hàm, kiểu dữ liệu, port) dự kiến.
3. Cách lưu dữ liệu và xử lý lỗi từng bản ghi.
4. Rủi ro chính và cách giảm.
5. Test strategy: unit / integration / property-based, ví dụ property cần kiểm.
6. Danh sách assumptions bạn đang đặt ra mà các file được cấp chưa trả lời.
```

## Output (verbatim)

# Kế hoạch triển khai: import tài khoản hàng loạt

Tôi chỉ đọc đúng các file được cho phép và chưa sửa file nào. Trước khi vào kế hoạch, có ba điểm trong code hiện tại ảnh hưởng trực tiếp đến thiết kế:

- **Module identity đang tự cam kết là không ghi tài khoản.** `identity/ports.py:1` ghi "GPU-003 never writes accounts", và việc ghi thuộc GPU-002. Muốn thêm chức năng import thì phải thống nhất lại ai sở hữu port ghi.
- **Yêu cầu hiệu năng p95 ≤ 1,5 giây có thể không đạt được với cấu hình băm hiện tại.** `DEFAULT_PROFILE` là N=2^15, r=8, p=3 và tốn 32 MiB mỗi lần băm. Hàm băm chỉ cho tối đa 4 lần băm chạy cùng lúc và chờ tối đa 2 giây (`identity/passwords.py:49`, `passwords.py:89-90`). 40 tác vụ, mỗi tác vụ dù chỉ 1 bản ghi, đã cần ≥ 10 lượt băm nối tiếp nhau. Nếu mỗi lần băm mất cỡ 0,15–0,3 giây thì tổng đã khoảng 1,5–3 giây. Đây chỉ là ước lượng, chưa đo.
- **Mỗi user chỉ có đúng một role.** `user_roles.user_id` là khóa chính (`domain/identity.py:49-53`), nên mỗi bản ghi import gán đúng một `role_code`.

---

## 1. Các file sẽ tạo/sửa

| File | Tạo/Sửa | Lý do |
|---|---|---|
| `backend/src/gpu_marketplace/identity/account_import.py` | Tạo | Service thuần: kiểm tra dữ liệu, chuẩn hoá tên, lọc trùng, băm mật khẩu, gọi port ghi, dựng báo cáo. Không import FastAPI hay SQLAlchemy, giống `service.py`. |
| `backend/src/gpu_marketplace/identity/ports.py` | Sửa (hoặc tạo `import_ports.py` nếu GPU-002 không muốn file đã review bị đụng vào) | Thêm `AccountWriter` Protocol, kiểu `NewAccount` và kết quả ghi. Sửa lại docstring dòng 1. |
| Adapter PostgreSQL cho `AccountWriter` (đường dẫn chưa biết, nằm ở tầng persistence GPU-002) | Tạo | Cài đặt bằng SQLAlchemy trên bảng `users` và `user_roles`. Tôi không được đọc tầng này nên chưa biết vị trí và quy ước. |
| `backend/tests/test_identity_account_import.py` | Tạo | Unit test với port giả (fake) và hàm băm cấu hình nhẹ `FAST` (giống `test_identity_passwords.py:15`). |
| `backend/tests/test_identity_account_import_properties.py` | Tạo | Property-based test bằng Hypothesis. |
| `backend/tests/integration/test_account_import_postgres.py` (đường dẫn giả định) | Tạo | Integration test với PostgreSQL thật, gồm cả kiểm tra đồng thời và đo p95. |
| `pyproject.toml` / `uv.lock` | Có thể sửa | Thêm `hypothesis` nếu chưa có. Tôi chưa kiểm tra được vì không được đọc file này. |

## 2. Interface dự kiến

```python
# identity/ports.py (thêm)
@dataclass(frozen=True)
class NewAccount:
    login_name: str          # đã chuẩn hoá
    password_hash: str = field(repr=False)
    role_code: str           # thuộc ROLES
    status: str              # 'ACTIVE' | 'DISABLED'

class AccountWriter(Protocol):
    def existing_login_names(self, login_names: Collection[str]) -> frozenset[str]:
        """Đọc trước để khỏi băm vô ích; raise AccountStoreUnavailable."""
    def insert_accounts(self, accounts: Sequence[NewAccount]) -> frozenset[str]:
        """Một transaction. Trả về tập login_name ĐÃ COMMIT; tên bị trùng khi đang ghi thì không có trong tập.
        Raise AccountStoreUnavailable nếu transaction không commit được (khi đó coi như không có gì được lưu)."""

# identity/account_import.py
@dataclass(frozen=True)
class ImportRecord:
    login_name: object
    password: object = field(repr=False)   # repr không bao giờ in mật khẩu
    role_code: object
    status: object

class RecordErrorCode(StrEnum):
    MISSING_OR_INVALID_TYPE, INVALID_LOGIN_NAME, INVALID_PASSWORD, INVALID_ROLE,
    INVALID_STATUS, DUPLICATE_IN_BATCH, LOGIN_NAME_TAKEN,
    HASHING_UNAVAILABLE,   # lỗi tạm thời, có thể thử lại
    STORE_UNAVAILABLE      # lỗi tạm thời, chắc chắn chưa lưu

@dataclass(frozen=True)
class RecordOutcome:
    index: int                        # vị trí trong lô đầu vào
    saved: bool
    login_name: str | None            # chỉ là tên ĐÃ chuẩn hoá, chỉ có khi hợp lệ
    error: RecordErrorCode | None

@dataclass(frozen=True)
class ImportReport:
    outcomes: tuple[RecordOutcome, ...]   # đúng 1 phần tử cho mỗi bản ghi, theo thứ tự đầu vào
    @property saved_count / failed_count

class BatchTooLarge(ValueError): ...

class AccountImportService:
    def __init__(self, writer: AccountWriter, passwords: PasswordHasher, *, max_batch: int = ...) -> None
    def import_accounts(self, records: Sequence[ImportRecord]) -> ImportReport   # đồng bộ, chạy trong worker thread
```

Service dùng lại `normalize_login_name` và `LoginNameError` (`normalization.py:21`), `PasswordHasher.hash_password`, `PasswordHashingBusy` và `ROLES` (`principal.py:12`).

## 3. Lưu dữ liệu và xử lý lỗi từng bản ghi

Luồng xử lý gồm 5 bước:

1. **Kiểm tra từng bản ghi (chưa đụng DB):**
   - Sai kiểu hoặc thiếu trường → `MISSING_OR_INVALID_TYPE`.
   - `normalize_login_name` lỗi → `INVALID_LOGIN_NAME`.
   - `role_code ∉ ROLES` → `INVALID_ROLE`.
   - `status ∉ {ACTIVE, DISABLED}` → `INVALID_STATUS`.
   - Mật khẩu không phải chuỗi, rỗng, hoặc chứa surrogate → `INVALID_PASSWORD`.
   - Riêng surrogate: `hash_password` ném `UnicodeEncodeError` từ `_encode_password` (`passwords.py:113`, `189-191`). Vì đây là lớp con của `ValueError` nên phải bắt `ValueError`. Tốt hơn là kiểm tra trước khi băm để khỏi tốn một lượt băm.
2. **Lọc trùng trong lô** theo tên đã chuẩn hoá, chỉ xét các bản ghi đã qua bước 1. Bản ghi xuất hiện đầu tiên được giữ, các bản sau → `DUPLICATE_IN_BATCH`. So sánh phân biệt hoa thường và không chuẩn hoá Unicode (theo `test_identity_normalization.py:22-45`).
3. **Đọc trước** `existing_login_names(...)` → `LOGIN_NAME_TAKEN`. Bước này chỉ để tối ưu, không thay cho ràng buộc unique của DB.
4. **Băm mật khẩu ngoài transaction** (không giữ connection DB trong lúc chạy scrypt), chỉ cho các bản ghi còn lại.
   - Gặp `PasswordHashingBusy` → bản ghi đó thành `HASHING_UNAVAILABLE`. Không coi đó là lỗi dữ liệu.
   - `ValueError` "hashing failed" → `HASHING_UNAVAILABLE`.
5. **Ghi trong một transaction** (adapter):
   - Chạy `INSERT INTO users (...) VALUES ... ON CONFLICT (login_name) DO NOTHING RETURNING id, login_name`.
   - Sau đó `INSERT INTO user_roles (user_id, role_code)` cho các id vừa trả về, rồi `COMMIT`.
   - Tên không có trong RETURNING nghĩa là đã bị import khác chèn trước (race) → `LOGIN_NAME_TAKEN`. Khi chạy đồng thời, PostgreSQL bắt transaction sau chờ transaction trước, nên kết quả vẫn đúng.
   - Các ràng buộc CHECK đã được kiểm tra ở bước 1. Nếu vẫn có lỗi ràng buộc bất ngờ, adapter chuyển sang ghi từng bản ghi với `SAVEPOINT`, để một bản ghi hỏng không kéo các bản khác rollback theo.

**Chỉ báo thành công sau khi COMMIT xong.** `saved=True` chỉ được gán cho các tên có trong tập trả về sau commit. Nếu commit lỗi hoặc mất kết nối thì mọi bản ghi đang chờ ghi đều thành `STORE_UNAVAILABLE`, `saved=False`.

Có một trường hợp mập mờ: commit có thể đã thành công phía server nhưng client mất kết nối trước khi nhận phản hồi. Khi đó báo `STORE_UNAVAILABLE` là an toàn theo nghĩa không báo thành công giả. Nếu chạy lại, các bản ghi đó sẽ ra `LOGIN_NAME_TAKEN`, đây là chấp nhận được.

**Log:** chỉ ghi số lượng, mã lỗi và một batch id. Không ghi mật khẩu, hash, và cả login_name thô (theo quy ước "error messages never echo the input", `normalization.py:26`). Exception tự định nghĩa không mang dữ liệu đầu vào. `NewAccount.password_hash` và `ImportRecord.password` đều đặt `repr=False`.

## 4. Rủi ro chính và cách giảm

| Rủi ro | Cách giảm |
|---|---|
| **Yêu cầu p95 ≤ 1,5 giây với 40 tác vụ có thể không đạt** vì scrypt 32 MiB và giới hạn 4 lần băm đồng thời. | Đo sớm (benchmark một lần băm `DEFAULT_PROFILE` trên máy CI hoặc máy đích). Cần chốt kích thước lô cho kịch bản NFR. Các hướng có thể chọn: tăng `max_concurrent` theo số core, giới hạn kích thước lô, hoặc nới SLO. Hướng giảm profile băm cần team lead quyết vì profile đã được duyệt ở C1/PR #18. |
| Import tranh suất băm với Login, khiến Login trả 503 (`service.py:82-85`). | Đề xuất cho import dùng một instance hasher riêng với giới hạn nhỏ, để Login không bị chiếm hết suất. Đổi lại sẽ tốn thêm RAM và CPU, cần quyết định. |
| `PasswordHashingBusy` bị báo nhầm thành lỗi dữ liệu. | Dùng mã riêng `HASHING_UNAVAILABLE` và đánh dấu có thể thử lại. |
| Hai import đồng thời cùng chèn một tên. | Dùng `ON CONFLICT DO NOTHING` + `RETURNING` và có test đồng thời. |
| Báo thành công khi chưa commit. | Kết quả chỉ được dựng từ tập trả về sau commit. Có test giả lập commit lỗi. |
| Lộ mật khẩu hoặc hash qua log, repr hoặc exception. | `repr=False`, test kiểm tra `caplog` và `repr(report)` không chứa mật khẩu hay hash. |
| Lô quá lớn làm transaction dài và tốn RAM. | Đặt `max_batch`. Vượt ngưỡng thì ném `BatchTooLarge` trước khi xử lý gì. |
| Role WORKER cần thêm dòng `workers`, mà bảng này bắt buộc `display_name` (`domain/identity.py:60-77`). | Kế hoạch chỉ tạo `user_roles`. Cần xác nhận (xem phần 6). |

## 5. Chiến lược test

**Unit** (fake `AccountWriter`, hasher `FAST`):
- Từng loại lỗi trả đúng mã.
- Trùng trong lô thì giữ bản đầu.
- Tên đã tồn tại → `LOGIN_NAME_TAKEN`.
- Writer mô phỏng race: không trả về một tên dù đã đọc trước là trống.
- Writer ném `AccountStoreUnavailable` → mọi bản ghi đang chờ thành `saved=False`.
- Hasher ném `PasswordHashingBusy` (dùng lại cách giữ `_slots`, `test_identity_passwords.py:194-205`).
- Không bản ghi lỗi nào bị băm (dùng monkeypatch `_derive` để đếm số lần gọi).
- `caplog` và `repr(report)` không chứa mật khẩu hay hash.
- Bản ghi có `"  name\t"` được lưu dưới dạng `"name"`.

**Property-based** (Hypothesis, sinh lô hỗn hợp hợp lệ/lỗi, kể cả tên có NUL, surrogate, khoảng trắng Unicode, tên trùng sau khi trim):
- P1: `len(report.outcomes) == len(records)` và `outcome[i].index == i`.
- P2: Writer giả thu được đúng N − K tài khoản, với K = số outcome có `saved=False`. Tập tên đã lưu bằng đúng tập `{o.login_name | o.saved}`.
- P3: `saved ⇔ error is None`. Mọi outcome lỗi đều có mã lỗi.
- P4: Tên đã lưu đều cố định qua chuẩn hoá (`normalize(x) == x`), không trùng nhau, và độ dài ≤ 128 code point.
- P5: Thêm một bản ghi lỗi vào lô bất kỳ không làm thay đổi kết quả của các bản ghi hợp lệ khác (bản ghi lỗi không làm mất bản ghi hợp lệ).
- P6: Đổi thứ tự lô thì tập tên được lưu không đổi. Riêng bản ghi nào thắng khi trùng thì phụ thuộc thứ tự, đúng như đã định nghĩa.
- P7: Không mật khẩu nào xuất hiện trong `repr(report)` hay trong log.
- P8: Khi writer ngẫu nhiên lỗi lúc commit thì `saved_count == 0`.

**Integration với PostgreSQL:**
- Lô N bản ghi có K lỗi → đếm bằng `SELECT` đúng N − K dòng `users` và đúng N − K dòng `user_roles` với role đúng.
- Băm lưu xuống DB verify được bằng `verify_password`.
- Hai import đồng thời chung một tên → đúng một dòng được lưu, một bên báo `LOGIN_NAME_TAKEN`.
- Ngắt kết nối hoặc lỗi trước commit → không có dòng nào và báo cáo không có `saved=True`.
- Test tải: 40 luồng gọi `import_accounts` dùng `DEFAULT_PROFILE`, đo p95 và đánh marker riêng (ví dụ `@pytest.mark.perf`) để tách khỏi suite nhanh.

## 6. Các giả định chưa được file nào trả lời

1. Ai sở hữu và review port ghi (GPU-002 hay GPU-003)? Có được sửa `ports.py` không, hay phải tạo file riêng?
2. Adapter PostgreSQL đặt ở đâu, quản lý session/engine thế nào, và có migration hoặc seed sẵn bảng `roles` không?
3. Hạ tầng integration test: có fixture PostgreSQL sẵn (testcontainers, docker-compose) không? `hypothesis` đã có trong dependency chưa?
4. Kịch bản NFR: mỗi tác vụ có bao nhiêu bản ghi? Đo trên phần cứng nào? Có dùng `DEFAULT_PROFILE` không? Có chạy cùng lúc với tải Login không?
5. Có được dùng hasher riêng cho import, hay bắt buộc chung instance với Login (`service.py:57-62` yêu cầu một hasher mỗi process)?
6. `role_code` và `status` so khớp chính xác hay được trim / không phân biệt hoa thường? Thiếu `status` thì mặc định `ACTIVE` (như server default) hay báo lỗi?
7. Có cho import role `ADMIN` không? Có cần kiểm tra quyền của người gọi không? (Không có giao diện nên tôi giả định người gọi là công cụ vận hành đáng tin.)
8. Role `WORKER` có cần tạo luôn dòng `workers` không? Đầu vào không có `display_name`.
9. Có chính sách độ mạnh mật khẩu nào ngoài "chuỗi không rỗng, encode được UTF-8" không?
10. Khi tên trùng trong lô: tôi giả định bản đầu tiên thắng. Có cần báo cả hai là lỗi không?
11. Tên đã tồn tại: tôi giả định báo lỗi, không cập nhật (không upsert).
12. Báo cáo có được chứa login_name đã chuẩn hoá không, hay chỉ chỉ số dòng? Tôi giả định chỉ chứa tên của bản ghi hợp lệ, không bao giờ chứa tên thô.
13. Ngữ nghĩa ghi: một transaction cho cả lô hay commit theo từng phần (chunk)? Tôi chọn một transaction cùng trần `max_batch`. Giá trị `max_batch` cần được chốt.
14. Có công cụ provisioning nào đã tồn tại không? `normalization.py:5` và `passwords.py:1` có nhắc tới "provisioning tool". Nếu có, import nên dùng lại hoặc gộp vào nó để khỏi trùng logic.