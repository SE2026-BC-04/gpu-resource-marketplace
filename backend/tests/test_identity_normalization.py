import pytest

from gpu_marketplace.identity.normalization import (
    LOGIN_NAME_MAX_LENGTH,
    LoginNameError,
    normalize_login_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("demo_client", "demo_client"),
        (" \t\r\ndemo_client\n\r\t ", "demo_client"),
        ("demo client", "demo client"),
    ],
)
def test_trims_only_surrounding_ascii_sp_ht_lf_cr(raw: str, expected: str) -> None:
    assert normalize_login_name(raw) == expected


def test_matching_is_case_sensitive() -> None:
    assert normalize_login_name("Demo") == "Demo"
    assert normalize_login_name("Demo") != normalize_login_name("demo")


@pytest.mark.parametrize(
    "raw",
    [
        " demo_client ",  # NO-BREAK SPACE
        " demo_client",  # EM SPACE
        "demo_client　",  # IDEOGRAPHIC SPACE
        "\x0bdemo_client\x0c",  # VT and FF are not in the approved trim set
    ],
)
def test_other_whitespace_is_part_of_the_name(raw: str) -> None:
    assert normalize_login_name(raw) == raw


def test_no_unicode_normalization() -> None:
    precomposed = "café"
    decomposed = "café"
    assert normalize_login_name(precomposed) == precomposed
    assert normalize_login_name(decomposed) == decomposed
    assert normalize_login_name(precomposed) != normalize_login_name(decomposed)


@pytest.mark.parametrize("raw", ["", " ", " \t\r\n "])
def test_empty_after_trim_is_rejected(raw: str) -> None:
    with pytest.raises(LoginNameError):
        normalize_login_name(raw)


def test_length_is_checked_after_trim_in_code_points() -> None:
    longest = "a" * LOGIN_NAME_MAX_LENGTH
    assert normalize_login_name(f"  {longest}\t") == longest
    assert normalize_login_name("é" * LOGIN_NAME_MAX_LENGTH) == "é" * LOGIN_NAME_MAX_LENGTH
    with pytest.raises(LoginNameError):
        normalize_login_name("a" * (LOGIN_NAME_MAX_LENGTH + 1))


def test_error_message_does_not_echo_input() -> None:
    secret_looking = "x" * (LOGIN_NAME_MAX_LENGTH + 1)
    with pytest.raises(LoginNameError) as excinfo:
        normalize_login_name(secret_looking)
    assert secret_looking not in str(excinfo.value)


def test_non_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        normalize_login_name(None)  # type: ignore[arg-type]
