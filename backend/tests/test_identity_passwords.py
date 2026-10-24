import base64
import threading

import pytest

from gpu_marketplace.identity import passwords
from gpu_marketplace.identity.passwords import (
    DEFAULT_PROFILE,
    PasswordHashingBusy,
    ScryptPasswordHasher,
    ScryptProfile,
)

# Low cost keeps the suite fast; the production default is checked separately.
FAST = ScryptProfile(n=2**10, r=8, p=1)
SURROGATE_PAIR = chr(0xD83D) + chr(0xDE00)


@pytest.fixture
def hasher() -> ScryptPasswordHasher:
    return ScryptPasswordHasher(profile=FAST)


def stored(profile: str, salt_bytes: int = 16, key_bytes: int = 32) -> str:
    salt = base64.b64encode(b"s" * salt_bytes).decode()
    key = base64.b64encode(b"k" * key_bytes).decode()
    return f"scrypt${profile}${salt}${key}"


def test_hash_then_verify(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("correct horse")
    assert hasher.verify_password("correct horse", encoded)
    assert not hasher.verify_password("wrong horse", encoded)


def test_password_is_not_trimmed_or_case_folded(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("Secret")
    for candidate in (" Secret", "Secret ", "secret", "Secret\n"):
        assert not hasher.verify_password(candidate, encoded)


def test_each_hash_uses_a_new_salt(hasher: ScryptPasswordHasher) -> None:
    assert hasher.hash_password("same") != hasher.hash_password("same")


def test_encoded_value_contains_no_plaintext(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("plain-text-password")
    assert encoded.startswith("scrypt$n=1024,r=8,p=1$")
    assert "plain-text-password" not in encoded


def test_default_profile_is_the_c1_profile() -> None:
    # C1 on PR #18: N=2^15, r=8, p=3 (OWASP-comparable 32 MiB profile).
    assert DEFAULT_PROFILE == ScryptProfile(n=2**15, r=8, p=3)
    assert DEFAULT_PROFILE.memory_bytes == 32 * 1024 * 1024
    default = ScryptPasswordHasher()
    encoded = default.hash_password("x")
    assert encoded.startswith("scrypt$n=32768,r=8,p=3$")
    assert default.verify_password("x", encoded)


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "bcrypt$2b$12$abc",
        "scrypt$n=1024,r=8,p=1$c2FsdA==",
        "scrypt$n=1024,r=8,p=1$!!!$a2V5",
        stored("n=1000,r=8,p=1"),
        stored("n=1024,r=0,p=1"),
    ],
)
def test_unreadable_stored_hash_fails_closed(hasher: ScryptPasswordHasher, encoded: str) -> None:
    assert hasher.verify_password("anything", encoded) is False


@pytest.mark.parametrize(
    "profile",
    ["n=1048576,r=8,p=1", "n=1048576,r=32,p=16", "n=4194304,r=8,p=1", "n=32768,r=8,p=3", "n=1024,r=8,p=2"],
)
def test_stored_hash_with_unapproved_profile_never_derives(
    hasher: ScryptPasswordHasher, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    # P1 on PR #18: a stored row cannot choose its own cost; only allowlisted profiles are computed.
    def must_not_run(*_: object) -> bytes:
        raise AssertionError("scrypt must not run for an unapproved profile")

    monkeypatch.setattr(passwords, "_derive", must_not_run)
    assert hasher.verify_password("anything", stored(profile)) is False


def test_accepted_profiles_allow_verifying_an_older_profile() -> None:
    old = ScryptProfile(n=2**10, r=8, p=2)
    legacy = ScryptPasswordHasher(profile=old).hash_password("pw")
    current = ScryptPasswordHasher(profile=FAST, accepted_profiles=frozenset({FAST, old}))
    assert current.verify_password("pw", legacy)
    assert not ScryptPasswordHasher(profile=FAST).verify_password("pw", legacy)


def test_oversized_stored_hash_is_rejected_before_decoding(hasher: ScryptPasswordHasher) -> None:
    assert hasher.verify_password("anything", stored("n=1024,r=8,p=1", key_bytes=2_000_000)) is False
    assert hasher.verify_password("anything", "scrypt$" + "A" * 10_000) is False


@pytest.mark.parametrize(("salt_bytes", "key_bytes"), [(8, 32), (65, 32), (16, 16), (16, 65)])
def test_stored_salt_and_key_lengths_are_bounded(
    hasher: ScryptPasswordHasher, salt_bytes: int, key_bytes: int
) -> None:
    assert hasher.verify_password("anything", stored("n=1024,r=8,p=1", salt_bytes, key_bytes)) is False


@pytest.mark.parametrize("error", [ValueError("memory limit exceeded"), MemoryError()])
def test_resource_errors_fail_closed_without_raising(
    hasher: ScryptPasswordHasher, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    encoded = hasher.hash_password("pw")

    def fail(*_: object) -> bytes:
        raise error

    monkeypatch.setattr(passwords, "_derive", fail)
    assert hasher.verify_password("pw", encoded) is False
    hasher.burn_verification("pw")


def test_concurrent_derivations_are_capped() -> None:
    hasher = ScryptPasswordHasher(profile=FAST, max_concurrent=1, acquire_timeout_seconds=0.05)
    encoded = hasher.hash_password("pw")
    hasher._slots.acquire()  # simulate one derivation already running
    try:
        with pytest.raises(PasswordHashingBusy):
            hasher.verify_password("pw", encoded)
        with pytest.raises(PasswordHashingBusy):
            hasher.burn_verification("pw")
    finally:
        hasher._slots.release()
    assert hasher.verify_password("pw", encoded)


def test_cap_holds_under_real_threads(monkeypatch: pytest.MonkeyPatch) -> None:
    hasher = ScryptPasswordHasher(profile=FAST, max_concurrent=2, acquire_timeout_seconds=5)
    encoded = hasher.hash_password("pw")
    real = passwords._derive
    running = 0
    peak = 0
    lock = threading.Lock()

    def counting(*args: object) -> bytes:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        try:
            return real(*args)  # type: ignore[arg-type]
        finally:
            with lock:
                running -= 1

    monkeypatch.setattr(passwords, "_derive", counting)
    threads = [threading.Thread(target=hasher.verify_password, args=("pw", encoded)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert 1 <= peak <= 2


def test_password_bytes_are_hashed_exactly_including_nul(hasher: ScryptPasswordHasher) -> None:
    password = "ab" + chr(0) + "cd"
    encoded = hasher.hash_password(password)
    assert hasher.verify_password(password, encoded)
    assert not hasher.verify_password("ab", encoded)


def test_non_string_inputs_fail_closed(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("pw")
    assert hasher.verify_password(None, encoded) is False  # type: ignore[arg-type]
    assert hasher.verify_password("pw", None) is False  # type: ignore[arg-type]


@pytest.mark.parametrize("password", [chr(0xD800), "pw" + chr(0xDFFF), SURROGATE_PAIR])
def test_lone_surrogate_password_fails_closed(hasher: ScryptPasswordHasher, password: str) -> None:
    # CR-GPU-003-UNICODE-01 R3: a generic mismatch (401 at the endpoint), never an exception.
    encoded = hasher.hash_password("pw")
    assert hasher.verify_password(password, encoded) is False
    hasher.burn_verification(password)


def test_non_bmp_password_round_trips(hasher: ScryptPasswordHasher) -> None:
    password = "p" + chr(0x1F600) + "ss"
    encoded = hasher.hash_password(password)
    assert hasher.verify_password(password, encoded)
    assert not hasher.verify_password("pss", encoded)


def test_empty_password_cannot_be_hashed(hasher: ScryptPasswordHasher) -> None:
    with pytest.raises(ValueError):
        hasher.hash_password("")


def test_burn_verification_runs_without_an_account(hasher: ScryptPasswordHasher) -> None:
    hasher.burn_verification("any password")


@pytest.mark.parametrize(("n", "r", "p"), [(1000, 8, 1), (1, 8, 1), (1024, 0, 1), (1024, 8, 0)])
def test_invalid_profiles_are_rejected(n: int, r: int, p: int) -> None:
    with pytest.raises(ValueError):
        ScryptProfile(n=n, r=r, p=p)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"salt_bytes": 8},
        {"salt_bytes": 65},
        {"key_bytes": 65},
        {"max_concurrent": 0},
        {"acquire_timeout_seconds": 0},
        {"accepted_profiles": frozenset({ScryptProfile(n=2**11, r=8, p=1)})},
    ],
)
def test_invalid_hasher_settings_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ScryptPasswordHasher(profile=FAST, **kwargs)  # type: ignore[arg-type]
