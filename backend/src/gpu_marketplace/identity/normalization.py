"""Login-name normalization shared by Login and account provisioning.

Trim/case/Unicode rules follow DEC-P1-03; rejection of NUL and lone surrogates follows
CR-GPU-003-UNICODE-01 (issue #16). Pure module: no web framework, ORM or database
driver imports, so the provisioning tool can reuse exactly the same rule as Login.
"""

import re

# Only ASCII SP, HT, LF and CR are trimmed; U+00A0 and other Unicode whitespace are kept.
LOGIN_NAME_TRIM_CHARACTERS = " \t\n\r"
LOGIN_NAME_MAX_LENGTH = 128
# PostgreSQL text cannot store U+0000, and surrogate code points cannot be encoded as UTF-8.
_UNSTORABLE_CODE_POINTS = re.compile("[\x00\ud800-\udfff]")


class LoginNameError(ValueError):
    """The login name is empty or longer than allowed after normalization."""


def normalize_login_name(raw: str) -> str:
    """Trim the approved ASCII characters at both ends; keep case and Unicode form unchanged.

    Length is counted in Unicode code points after trimming, matching ``users.login_name
    varchar(128)``. U+0000 and any surrogate code point are rejected before any database
    access. Error messages never echo the input, which may be a mistyped password.
    """
    if not isinstance(raw, str):
        raise TypeError("login name must be a string")
    if _UNSTORABLE_CODE_POINTS.search(raw):
        raise LoginNameError("login name contains NUL or a surrogate code point")
    normalized = raw.strip(LOGIN_NAME_TRIM_CHARACTERS)
    if not normalized:
        raise LoginNameError("login name is empty after normalization")
    if len(normalized) > LOGIN_NAME_MAX_LENGTH:
        raise LoginNameError(f"login name exceeds {LOGIN_NAME_MAX_LENGTH} characters")
    return normalized
