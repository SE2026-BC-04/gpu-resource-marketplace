import base64
import hashlib
import hmac
import json
from uuid import UUID

import pytest

from gpu_marketplace.identity.tokens import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    AccessTokenCodec,
    InvalidTokenError,
)

SECRET = b"s" * 32
SUBJECT = UUID("e98d4b53-dca0-4a50-8ea0-51647b60b254")
T0_US = 1_792_041_000_123_456  # 2026-10-15T05:10:00.123456Z


class FakeClock:
    def __init__(self, now_us: int) -> None:
        self.now_us = now_us

    def __call__(self) -> int:
        return self.now_us


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign_raw(header: str, payload: str, secret: bytes = SECRET) -> str:
    """Build a token from raw JSON text, to test claims the codec itself never issues."""
    signing_input = f"{_b64(header.encode())}.{_b64(payload.encode())}"
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


HEADER = '{"alg":"HS256","typ":"JWT"}'


def _payload(**overrides: str) -> str:
    fields = {
        "iss": json.dumps(TOKEN_ISSUER),
        "aud": json.dumps(TOKEN_AUDIENCE),
        "sub": json.dumps(str(SUBJECT)),
        "iat": "1792041000.123456",
        "exp": "1792041900.123456",
    }
    fields.update(overrides)
    return "{" + ",".join(f'"{name}":{value}' for name, value in fields.items()) + "}"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0_US)


@pytest.fixture
def codec(clock: FakeClock) -> AccessTokenCodec:
    return AccessTokenCodec(SECRET, clock=clock)


def _decode_segment(segment: str) -> str:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode()


def test_issued_token_matches_approved_profile(codec: AccessTokenCodec) -> None:
    issued = codec.issue(SUBJECT)
    header, payload, _ = issued.token.split(".")

    assert _decode_segment(header) == HEADER
    assert _decode_segment(payload) == _payload()
    assert issued.expires_in == 900
    assert issued.claims.issued_at_us == T0_US
    assert issued.claims.expires_at_us - issued.claims.issued_at_us == 900_000_000


def test_numeric_date_keeps_microseconds_without_float_rounding(clock: FakeClock) -> None:
    clock.now_us = 1_792_041_000_000_001
    payload = _decode_segment(AccessTokenCodec(SECRET, clock=clock).issue(SUBJECT).token.split(".")[1])
    assert '"iat":1792041000.000001' in payload
    assert '"exp":1792041900.000001' in payload


def test_expiry_boundary_has_no_leeway(codec: AccessTokenCodec, clock: FakeClock) -> None:
    token = codec.issue(SUBJECT).token

    clock.now_us = T0_US + 899_999_999
    assert codec.verify(token).subject == SUBJECT

    clock.now_us = T0_US + 900_000_000
    with pytest.raises(InvalidTokenError) as excinfo:
        codec.verify(token)
    assert excinfo.value.reason == "expired"


def test_tampered_payload_is_rejected(codec: AccessTokenCodec) -> None:
    header, _, signature = codec.issue(SUBJECT).token.split(".")
    other = _b64(_payload(sub=json.dumps("11111111-1111-4111-8111-111111111111")).encode())
    with pytest.raises(InvalidTokenError) as excinfo:
        codec.verify(f"{header}.{other}.{signature}")
    assert excinfo.value.reason == "signature"


def test_token_from_another_secret_is_rejected(clock: FakeClock) -> None:
    token = AccessTokenCodec(b"o" * 32, clock=clock).issue(SUBJECT).token
    with pytest.raises(InvalidTokenError):
        AccessTokenCodec(SECRET, clock=clock).verify(token)


@pytest.mark.parametrize(
    "header",
    [
        '{"alg":"none","typ":"JWT"}',
        '{"alg":"HS512","typ":"JWT"}',
        '{"alg":"HS256"}',
        '{"alg":"HS256","typ":"JWT","kid":"1"}',
        '{"alg":"HS256","typ":"JWT","typ":"JWT"}',
    ],
)
def test_wrong_header_is_rejected(codec: AccessTokenCodec, header: str) -> None:
    with pytest.raises(InvalidTokenError):
        codec.verify(_sign_raw(header, _payload()))


def test_unsigned_alg_none_token_is_rejected(codec: AccessTokenCodec) -> None:
    none_header = _b64(b'{"alg":"none","typ":"JWT"}')
    token = f"{none_header}.{_b64(_payload().encode())}."
    with pytest.raises(InvalidTokenError):
        codec.verify(token)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"iss": json.dumps("someone-else")}, "issuer"),
        ({"aud": json.dumps("gpu-marketplace-admin")}, "audience"),
        ({"sub": json.dumps("not-a-uuid")}, "subject"),
        ({"sub": json.dumps(str(SUBJECT).upper())}, "subject"),
        ({"sub": "42"}, "subject"),
        ({"iat": "1792041000"}, "numeric_date"),
        ({"iat": "1792041000.123", "exp": "1792041900.123"}, "numeric_date"),
        ({"exp": "1792041901.123456"}, "lifetime"),
        ({"iat": "-1792041000.123456"}, "numeric_date"),
    ],
)
def test_signed_but_invalid_claims_are_rejected(
    codec: AccessTokenCodec, overrides: dict[str, str], reason: str
) -> None:
    with pytest.raises(InvalidTokenError) as excinfo:
        codec.verify(_sign_raw(HEADER, _payload(**overrides)))
    assert excinfo.value.reason == reason


def test_extra_or_missing_claims_are_rejected(codec: AccessTokenCodec) -> None:
    extra = _payload()[:-1] + ',"role":"ADMIN"}'
    missing = _payload().replace(f',"aud":{json.dumps(TOKEN_AUDIENCE)}', "")
    for payload in (extra, missing):
        with pytest.raises(InvalidTokenError) as excinfo:
            codec.verify(_sign_raw(HEADER, payload))
        assert excinfo.value.reason == "claims"


@pytest.mark.parametrize(
    "payload",
    [
        _payload()[:-1] + ',"iss":"gpu-marketplace-api"}',  # duplicate key
        _payload(iat="NaN"),
        "[]",
        "not json",
    ],
)
def test_malformed_payload_is_rejected(codec: AccessTokenCodec, payload: str) -> None:
    with pytest.raises(InvalidTokenError):
        codec.verify(_sign_raw(HEADER, payload))


@pytest.mark.parametrize("token", ["", "a.b", "a.b.c.d", None, 123])
def test_malformed_token_shape_is_rejected(codec: AccessTokenCodec, token: object) -> None:
    with pytest.raises(InvalidTokenError) as excinfo:
        codec.verify(token)  # type: ignore[arg-type]
    assert excinfo.value.reason == "malformed"


def test_non_canonical_base64url_is_rejected(codec: AccessTokenCodec) -> None:
    header, payload, signature = codec.issue(SUBJECT).token.split(".")
    for bad_signature in (signature + "=", signature[:-1] + "+", signature + "A"):
        with pytest.raises(InvalidTokenError):
            codec.verify(f"{header}.{payload}.{bad_signature}")


def test_secret_must_be_at_least_256_bits() -> None:
    AccessTokenCodec(b"k" * 32)
    with pytest.raises(ValueError):
        AccessTokenCodec(b"k" * 31)
    with pytest.raises(ValueError):
        AccessTokenCodec("k" * 32)  # type: ignore[arg-type]


def test_error_reason_does_not_contain_the_token(codec: AccessTokenCodec, clock: FakeClock) -> None:
    token = codec.issue(SUBJECT).token
    clock.now_us = T0_US + 900_000_000
    with pytest.raises(InvalidTokenError) as excinfo:
        codec.verify(token)
    assert token not in str(excinfo.value)
