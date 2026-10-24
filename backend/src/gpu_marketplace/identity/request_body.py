"""Bounded reading of the public Auth request bodies (API Contract §4.2 and §4.4).

Login is reachable without authentication, so its body is limited while it is received:
the declared ``Content-Length`` is checked first and the stream is counted chunk by chunk,
so neither a missing nor a misleading length makes the API buffer more than the limit.
Only a body that passed the size, media-type and nesting checks reaches the JSON parser.
"""

import json
from typing import Any

from starlette.requests import Request

MAX_LOGIN_BODY_BYTES = 16 * 1024
# A Login body is one flat object; deeper nesting only costs parser work.
MAX_JSON_DEPTH = 8


class BodyTooLarge(Exception):
    """The body is larger than the endpoint's limit."""


class InvalidBody(Exception):
    """Unsupported media type, malformed framing, or a body that is not acceptable JSON."""


class UnexpectedBody(Exception):
    """A body was sent to an endpoint that accepts none."""


def require_json_media_type(content_type: str | None) -> None:
    if content_type is None:
        raise InvalidBody()
    media_type, *parameters = content_type.split(";")
    if media_type.strip().lower() != "application/json":
        raise InvalidBody()
    for parameter in parameters:
        name, _, value = parameter.partition("=")
        if name.strip().lower() == "charset" and value.strip().strip('"').lower() != "utf-8":
            raise InvalidBody()


async def read_bounded_body(request: Request, limit: int) -> bytes:
    declared = _declared_length(request)
    if declared is not None and declared > limit:
        raise BodyTooLarge()
    received = bytearray()
    async for chunk in request.stream():
        received += chunk
        if len(received) > limit:
            raise BodyTooLarge()
    return bytes(received)


async def require_empty_body(request: Request) -> None:
    if _declared_length(request):
        raise UnexpectedBody()
    async for chunk in request.stream():
        if chunk:
            raise UnexpectedBody()


def parse_json(body: bytes) -> Any:
    """Parse strict JSON: UTF-8, no duplicate keys, no NaN/Infinity, at most MAX_JSON_DEPTH levels."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidBody() from exc
    if not _within_depth(text, MAX_JSON_DEPTH):
        raise InvalidBody()
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise InvalidBody() from exc


def _declared_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    if not (raw.isascii() and raw.isdigit()):
        raise InvalidBody()
    return int(raw)


def _within_depth(text: str, limit: int) -> bool:
    # Count only brackets outside JSON strings; malformed input is left to the parser.
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                return False
        elif char in "]}":
            depth -= 1
    return True


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise ValueError("non-JSON numeric constant")
