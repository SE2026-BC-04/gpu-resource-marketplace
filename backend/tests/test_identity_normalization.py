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
        "\u00a0demo_client\u00a0",  # NO-BREAK SPACE
        "\u2003demo_client",  # EM SPACE
        "demo_client\u3000",  # IDEOGRAPHIC SPACE
        "\x0bdemo_client\x0c",  # VT and FF are not in the approved trim set
    ],
)
def test_other_whitespace_is_part_of_the_name(raw: str) -> None:
    assert normalize_login_name(raw) == raw


def test_no_unicode_normalization() -> None:
    precomposed = "caf\u00e9"
    decomposed = "cafe\u0301"
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
    assert normalize_login_name("\u00e9" * LOGIN_NAME_MAX_LENGTH) == "\u00e9" * LOGIN_NAME_MAX_LENGTH
    with pytest.raises(LoginNameError):
        normalize_login_name("a" * (LOGIN_NAME_MAX_LENGTH + 1))


@pytest.mark.parametrize(
    "raw",
    [
        "\x00demo_client",
        "demo\x00client",
        "demo_client\x00",
        " demo_client \x00",  # NUL is not trimmed
        "demo\ud800client",  # lone high surrogate
        "demo\udfffclient",  # lone low surrogate
        "\udc00",
        chr(0xD83D) + chr(0xDE00),  # surrogate code points, even as a "pair", are invalid
    ],
)
def test_nul_and_surrogate_code_points_are_rejected(raw: str) -> None:
    # CR-GPU-003-UNICODE-01 R1: rejected before any database access.
    with pytest.raises(LoginNameError) as excinfo:
        normalize_login_name(raw)
    assert raw not in str(excinfo.value)


@pytest.mark.parametrize(
    "raw",
    [
        "user\U0001F600",  # outside the BMP
        "\U0001F600" * LOGIN_NAME_MAX_LENGTH,  # 128 code points, 512 UTF-8 bytes
        "Nguy\u1ec5n",  # precomposed Vietnamese letters
        "\u4e2d\u6587",
    ],
)
def test_valid_unicode_names_are_accepted_unchanged(raw: str) -> None:
    assert normalize_login_name(raw) == raw


def test_non_bmp_characters_count_as_one_code_point() -> None:
    with pytest.raises(LoginNameError):
        normalize_login_name("\U0001F600" * (LOGIN_NAME_MAX_LENGTH + 1))


def test_error_message_does_not_echo_input() -> None:
    secret_looking = "x" * (LOGIN_NAME_MAX_LENGTH + 1)
    with pytest.raises(LoginNameError) as excinfo:
        normalize_login_name(secret_looking)
    assert secret_looking not in str(excinfo.value)


def test_non_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        normalize_login_name(None)  # type: ignore[arg-type]
