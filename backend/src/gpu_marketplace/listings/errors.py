"""Public-safe Listing failures; never include adapter/driver exception text."""


class ListingError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ListingDependencyUnavailable(Exception):
    """An upstream auth/persistence adapter cannot currently serve a request."""


def not_found() -> ListingError:
    return ListingError(404, "LISTING_NOT_FOUND", "Listing not found.")


def invalid_fields() -> ListingError:
    return ListingError(422, "VALIDATION_ERROR", "Invalid Listing fields.")
