"""Domain exceptions. Routes / exception handlers translate these into HTTP status codes."""


class AuthError(Exception):
    """Base class for authentication problems."""


class TokenValidationError(AuthError):
    """Access token missing, malformed, expired, or not trusted  -> HTTP 401."""


class AuthRejectedError(AuthError):
    """Supabase Auth refused the request (bad credentials, weak password, ...)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthServiceUnavailableError(AuthError):
    """Supabase Auth unreachable or erroring  -> HTTP 503.

    A technical failure, never to be confused with "wrong password".
    """


class NotFoundError(Exception):
    """Resource does not exist OR belongs to another user  -> HTTP 404.

    We deliberately never reveal which of the two it is.
    """


class InvalidOperationError(Exception):
    """Request conflicts with the resource's current state  -> HTTP 409."""
