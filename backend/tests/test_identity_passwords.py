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


def test_non_string_inputs_fail_closed(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("pw")
    assert hasher.verify_password(None, encoded) is False  # type: ignore[arg-type]
    assert hasher.verify_password("pw", None) is False  # type: ignore[arg-type]


def test_lone_surrogate_password_fails_closed(hasher: ScryptPasswordHasher) -> None:
    encoded = hasher.hash_password("pw")
    assert hasher.verify_password("\ud800", encoded) is False
    hasher.burn_verification("\ud800")


def test_empty_password_cannot_be_hashed(hasher: ScryptPasswordHasher) -> None:
    with pytest.raises(ValueError):
        hasher.hash_password("")


def test_burn_verification_runs_without_an_account(hasher: ScryptPasswordHasher) -> None:
    hasher.burn_verification("any password")


@pytest.mark.parametrize("parameters", [{"n": 1000}, {"n": 1}, {"r": 0}, {"p": 0}, {"salt_bytes": 8}])
def test_invalid_parameters_are_rejected(parameters: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ScryptPasswordHasher(**{**FAST, **parameters})
