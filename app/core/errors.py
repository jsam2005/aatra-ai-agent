"""Domain exceptions. The API layer maps these to HTTP responses in one place (app/main.py)."""


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class LLMUnavailableError(AppError):
    """The language model could not be reached (network, rate limit, 5xx, auth)."""

    status_code = 503
    code = "llm_unavailable"


class BackendServiceError(AppError):
    """A (mock) backend service failed in an unexpected way."""

    status_code = 502
    code = "backend_error"
