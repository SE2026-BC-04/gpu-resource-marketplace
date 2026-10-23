import base64

import pytest

from gpu_marketplace.identity.passwords import ScryptPasswordHasher

# Low cost keeps the suite fast; the production default is checked separately.
FAST = {"n": 2**10, "r": 8, "p": 1}


@pytest.fixture
def hasher() -> ScryptPasswordHasher:
    return ScryptPasswordHasher(**FAST)


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


def test_default_cost_is_the_proposed_profile() -> None:
    encoded = ScryptPasswordHasher().hash_password("x")
    assert encoded.startswith("scrypt$n=32768,r=8,p=1$")


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "bcrypt$2b$12$abc",
        "scrypt$n=1024,r=8,p=1$c2FsdA==",
        "scrypt$n=1024,r=8,p=1$!!!$a2V5",
        "scrypt$n=1000,r=8,p=1$c2FsdHNhbHRzYWx0c2FsdA==$a2V5",
        "scrypt$n=4194304,r=8,p=1$c2FsdHNhbHRzYWx0c2FsdA==$a2V5",
        "scrypt$n=1024,r=0,p=1$c2FsdHNhbHRzYWx0c2FsdA==$a2V5",
    ],
)
def test_unreadable_stored_hash_fails_closed(hasher: ScryptPasswordHasher, encoded: str) -> None:
    assert hasher.verify_password("anything", encoded) is False


@pytest.mark.parametrize(("salt_bytes", "key_bytes"), [(8, 32), (65, 32), (16, 16), (16, 65), (16, 2_000_000)])
def test_stored_salt_and_key_lengths_are_bounded(
    hasher: ScryptPasswordHasher, salt_bytes: int, key_bytes: int
) -> None:
    encoded = (
        "scrypt$n=1024,r=8,p=1$"
        + base64.b64encode(b"s" * salt_bytes).decode()
        + "$"
        + base64.b64encode(b"k" * key_bytes).decode()
    )
    assert hasher.verify_password("anything", encoded) is False


def test_password_bytes_are_hashed_exactly_including_nul(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("ab\x00cd")
    assert hasher.verify_password("ab\x00cd", encoded)
    assert not hasher.verify_password("ab", encoded)


def test_non_string_inputs_fail_closed(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("pw")
    assert hasher.verify_password(None, encoded) is False  # type: ignore[arg-type]
    assert hasher.verify_password("pw", None) is False  # type: ignore[arg-type]


@pytest.mark.parametrize("password", ["\ud800", "pw\udfff", chr(0xD83D) + chr(0xDE00)])
def test_lone_surrogate_password_fails_closed(hasher: ScryptPasswordHasher, password: str) -> None:
    # CR-GPU-003-UNICODE-01 R3: a generic mismatch (401 at the endpoint), never an exception.
    encoded = hasher.hash_password("pw")
    assert hasher.verify_password(password, encoded) is False
    hasher.burn_verification(password)


def test_non_bmp_password_round_trips(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("p\U0001F600ss")
    assert hasher.verify_password("p\U0001F600ss", encoded)
    assert not hasher.verify_password("pss", encoded)


def test_empty_password_cannot_be_hashed(hasher: ScryptPasswordHasher) -> None:
    with pytest.raises(ValueError):
        hasher.hash_password("")


def test_burn_verification_runs_without_an_account(hasher: ScryptPasswordHasher) -> None:
    hasher.burn_verification("any password")


@pytest.mark.parametrize(
    "parameters",
    [{"n": 1000}, {"n": 1}, {"r": 0}, {"p": 0}, {"salt_bytes": 8}, {"salt_bytes": 65}, {"key_bytes": 65}],
)
def test_invalid_parameters_are_rejected(parameters: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ScryptPasswordHasher(**{**FAST, **parameters})
