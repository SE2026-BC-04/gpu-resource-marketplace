"""Test doubles for GPU-003-C; never imported by production code."""

from uuid import UUID

from gpu_marketplace.identity.passwords import PasswordHashingBusy, ScryptPasswordHasher, ScryptProfile
from gpu_marketplace.identity.ports import AccountRecord, AccountStoreUnavailable
from gpu_marketplace.identity.service import AuthService
from gpu_marketplace.identity.tokens import AccessTokenCodec

SECRET = b"t" * 32
T0_US = 1_792_041_000_123_456
HASHER = ScryptPasswordHasher(profile=ScryptProfile(n=2**10, r=8, p=1))

C1 = UUID("8bf66294-daf8-42fa-a167-50a3a43b7b66")
W1 = UUID("0cbce840-2b5b-4eb8-83dc-968e5d47871b")
A1 = UUID("9d9907cc-12b3-4386-bdbe-9e53f24150b5")
D1 = UUID("2d0b8645-eb40-4584-9fb8-119bb68e3448")
NO_ROLE = UUID("4ec0d9ac-42cc-4d24-a71e-f9efa60e1db4")
BAD_ROLE = UUID("271a4dce-7615-4bf7-9990-379165a418ce")
NUL_PASSWORD_USER = UUID("6700e838-040d-4e9f-96a1-0f1e7668171b")

PASSWORD = "correct horse"
NUL_PASSWORD = "ab" + chr(0) + "cd"


class FakeClock:
    def __init__(self, now_us: int = T0_US) -> None:
        self.now_us = now_us

    def __call__(self) -> int:
        return self.now_us


class FakeAccountReader:
    """Counts every read so tests can prove that invalid input never reaches the database."""

    def __init__(self) -> None:
        self.reads = 0
        self.unavailable = False
        self.by_id: dict[UUID, AccountRecord] = {}
        for user_id, name, status, role, password in [
            (C1, "demo_client_01", "ACTIVE", "CLIENT", PASSWORD),
            (W1, "demo_worker_01", "ACTIVE", "WORKER", PASSWORD),
            (A1, "demo_admin_01", "ACTIVE", "ADMIN", PASSWORD),
            (D1, "demo_disabled_01", "DISABLED", "CLIENT", PASSWORD),
            (NO_ROLE, "demo_no_role", "ACTIVE", None, PASSWORD),
            (BAD_ROLE, "demo_bad_role", "ACTIVE", "OWNER", PASSWORD),
            (NUL_PASSWORD_USER, "demo_nul_password", "ACTIVE", "CLIENT", NUL_PASSWORD),
        ]:
            self.put(user_id, name, status, role, password)

    def put(self, user_id: UUID, name: str, status: str, role: str | None, password: str) -> None:
        self.by_id[user_id] = AccountRecord(user_id, name, HASHER.hash_password(password), status, role)

    def set(self, user_id: UUID, **changes: str | None) -> None:
        record = self.by_id[user_id]
        self.by_id[user_id] = AccountRecord(
            user_id=record.user_id,
            login_name=record.login_name,
            password_hash=record.password_hash,
            status=changes.get("status", record.status),  # type: ignore[arg-type]
            role=changes.get("role", record.role),
        )

    def _check(self) -> None:
        self.reads += 1
        if self.unavailable:
            raise AccountStoreUnavailable("database unavailable")

    def find_by_login_name(self, login_name: str) -> AccountRecord | None:
        self._check()
        return next((r for r in self.by_id.values() if r.login_name == login_name), None)

    def get_by_id(self, user_id: UUID) -> AccountRecord | None:
        self._check()
        return self.by_id.get(user_id)


class SpyHasher:
    """Wraps the real hasher and records whether the dummy verification ran."""

    def __init__(self) -> None:
        self.burned = 0
        self.busy = False

    def hash_password(self, password: str) -> str:
        return HASHER.hash_password(password)

    def verify_password(self, password: str, encoded: str) -> bool:
        if self.busy:
            raise PasswordHashingBusy()
        return HASHER.verify_password(password, encoded)

    def burn_verification(self, password: str) -> None:
        if self.busy:
            raise PasswordHashingBusy()
        self.burned += 1
        HASHER.burn_verification(password)


def build_service(
    reader: FakeAccountReader | None = None, clock: FakeClock | None = None, hasher: SpyHasher | None = None
) -> tuple[AuthService, FakeAccountReader, FakeClock, SpyHasher]:
    reader = reader or FakeAccountReader()
    clock = clock or FakeClock()
    hasher = hasher or SpyHasher()
    return AuthService(reader, AccessTokenCodec(SECRET, clock=clock), hasher), reader, clock, hasher
