"""Read-side policies for Jobs; writes remain explicitly unimplemented here."""

from __future__ import annotations

from uuid import UUID

from gpu_marketplace.jobs.errors import (
    Forbidden,
    InvalidCursor,
    InvalidFilter,
    JobNotFound,
    Unauthenticated,
    ValidationFailed,
)
from gpu_marketplace.jobs.models import (
    JobCollectionResponse,
    JobRole,
    JobStatus,
    PublicJobResponse,
)
from gpu_marketplace.jobs.ports import (
    CursorContext,
    CursorCodec,
    JobPrincipal,
    JobReader,
    JobScope,
)
from gpu_marketplace.jobs.projections import project_job


class JobsReadService:
    def __init__(self, *, reader: JobReader, cursor_codec: CursorCodec) -> None:
        self._reader = reader
        self._cursor_codec = cursor_codec

    def list_jobs(
        self,
        *,
        principal: JobPrincipal,
        scope: str | None = None,
        status: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> JobCollectionResponse:
        role = self._role(principal)
        resolved_scope = self._scope(role, scope)
        resolved_status = self._status(status)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationFailed()

        context = CursorContext(
            user_id=principal.user_id,
            role=role,
            scope=resolved_scope.value,
            status=resolved_status,
        )
        position = None
        if cursor is not None:
            if not cursor:
                raise InvalidCursor()
            try:
                position = self._cursor_codec.decode(cursor, context=context)
            except (ValueError, TypeError, KeyError) as exc:
                raise InvalidCursor() from exc

        page = self._reader.list_visible(
            principal=principal,
            status=resolved_status,
            after=position,
            limit=limit,
        )
        next_cursor = None
        if page.next_position is not None:
            # Encoding consumes a server/repository position. A malformed internal
            # position is a server failure, never a client INVALID_CURSOR response.
            next_cursor = self._cursor_codec.encode(page.next_position, context=context)
        items: list[PublicJobResponse] = [
            project_job(record, principal=principal) for record in page.items
        ]
        return JobCollectionResponse(items=items, next_cursor=next_cursor)

    def get_job(self, *, principal: JobPrincipal, job_id: UUID) -> PublicJobResponse:
        self._role(principal)
        record = self._reader.get_visible(principal=principal, job_id=job_id)
        if record is None:
            # Repository must return no row for both missing and non-visible Jobs.
            raise JobNotFound()
        return project_job(record, principal=principal)

    @staticmethod
    def _role(principal: JobPrincipal) -> JobRole:
        try:
            return JobRole(principal.role)
        except (ValueError, TypeError) as exc:
            raise Unauthenticated() from exc

    @staticmethod
    def _scope(role: JobRole, scope: str | None) -> JobScope:
        expected = {
            JobRole.CLIENT: JobScope.MINE,
            JobRole.WORKER: JobScope.ASSIGNED,
            JobRole.ADMIN: JobScope.ALL,
        }[role]
        if scope is None:
            return expected
        try:
            requested = JobScope(scope)
        except ValueError as exc:
            # API Contract §8.2 defines unsupported/cross-role scopes as 403.
            raise Forbidden() from exc
        if requested is not expected:
            raise Forbidden()
        return requested

    @staticmethod
    def _status(status: str | None) -> JobStatus | None:
        if status is None:
            return None
        try:
            return JobStatus(status)
        except ValueError as exc:
            raise InvalidFilter() from exc
