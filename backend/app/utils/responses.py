from typing import Any, Generic, Optional, TypeVar
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from app.core.observability import current_request_id

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standardized API response envelope."""

    success: bool
    message: str
    data: Optional[T] = None
    errors: Optional[Any] = None


def success_response(
    data: Optional[Any] = None,
    message: str = "Operation completed successfully",
    status_code: int = 200,
) -> JSONResponse:
    """Format and return a standardized success JSONResponse."""
    payload = {
        "success": True,
        "message": message,
        "data": data,
    }
    return JSONResponse(status_code=status_code, content=payload)


def error_response(
    message: str,
    status_code: int = 400,
    errors: Optional[Any] = None,
) -> JSONResponse:
    """Format and return a standardized error JSONResponse."""
    payload = {
        "success": False,
        "message": message,
        "data": None,
        "errors": errors,
        "request_id": current_request_id(),
    }
    return JSONResponse(status_code=status_code, content=payload)
