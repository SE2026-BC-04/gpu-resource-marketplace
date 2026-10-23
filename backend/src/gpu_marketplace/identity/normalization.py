"""Login-name normalization shared by Login and account provisioning (DEC-P1-03).

Pure module: no web framework, ORM or database driver imports, so the provisioning
tool can reuse exactly the same rule as the Login endpoint.
"""

# Only ASCII SP, HT, LF and CR are trimmed; U+00A0 and other Unicode whitespace are kept.
LOGIN_NAME_TRIM_CHARACTERS = " \t\n\r"
LOGIN_NAME_MAX_LENGTH = 128


class LoginNameError(ValueError):
    """The login name is empty or longer than allowed after normalization."""


def normalize_login_name(raw: str) -> str:
    """Trim the approved ASCII characters at both ends; keep case and Unicode form unchanged.

    Length is counted in Unicode code points after trimming, matching ``users.login_name
    varchar(128)``. Error messages never echo the input, which may be a mistyped password.
    """
    if not isinstance(raw, str):
        raise TypeError("login name must be a string")
    normalized = raw.strip(LOGIN_NAME_TRIM_CHARACTERS)
    if not normalized:
        raise LoginNameError("login name is empty after normalization")
    if len(normalized) > LOGIN_NAME_MAX_LENGTH:
        raise LoginNameError(f"login name exceeds {LOGIN_NAME_MAX_LENGTH} characters")
    return normalized
