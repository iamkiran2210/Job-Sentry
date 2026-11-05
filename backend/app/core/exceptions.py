import logging
from typing import Any, Optional
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.utils.responses import error_response

logger = logging.getLogger("job_sentry")


class AppException(Exception):
    """Base application exception."""
    def __init__(
        self,
        message: str = "An error occurred",
        status_code: int = 400,
        errors: Optional[Any] = None,
    ):
        self.message = message
        self.status_code = status_code
        self.errors = errors
        super().__init__(self.message)


class BadRequestException(AppException):
    def __init__(self, message: str = "Invalid request", errors: Optional[Any] = None):
        super().__init__(message=message, status_code=400, errors=errors)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Could not validate credentials", errors: Optional[Any] = None):
        super().__init__(message=message, status_code=401, errors=errors)


class ForbiddenException(AppException):
    def __init__(self, message: str = "You do not have permission to access this resource", errors: Optional[Any] = None):
        super().__init__(message=message, status_code=403, errors=errors)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found", errors: Optional[Any] = None):
        super().__init__(message=message, status_code=404, errors=errors)


class ConflictException(AppException):
    def __init__(self, message: str = "Resource already exists", errors: Optional[Any] = None):
        super().__init__(message=message, status_code=409, errors=errors)


class ValidationException(AppException):
    def __init__(self, message: str = "Validation failed", errors: Optional[Any] = None):
        super().__init__(message=message, status_code=422, errors=errors)


async def app_exception_handler(request: Request, exc: AppException):
    """Handle custom application exceptions."""
    return error_response(
        message=exc.message,
        status_code=exc.status_code,
        errors=exc.errors,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle Starlette and FastAPI HTTPExceptions."""
    return error_response(
        message=str(exc.detail),
        status_code=exc.status_code,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request schema validation errors."""
    formatted_errors = []
    for err in exc.errors():
        loc = " -> ".join([str(p) for p in err.get("loc", []) if p != "body"])
        formatted_errors.append({
            "field": loc if loc else "body",
            "message": err.get("msg", "Invalid value"),
            "type": err.get("type"),
        })
    return error_response(
        message="Request validation error",
        status_code=422,
        errors=formatted_errors,
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    """Handle all uncaught exceptions, preventing stack trace leakage."""
    logger.exception(f"Unhandled error handling request {request.method} {request.url.path}: {exc}")
    return error_response(
        message="An unexpected internal server error occurred. Please try again later.",
        status_code=500,
    )
