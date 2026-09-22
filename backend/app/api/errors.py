"""Uniform error responses. Nothing here may expose SQL, credentials, stack traces or request contents.

Every error uses one envelope::

    {"error": {"code": "device_not_found", "message": "...", "details": [...optional...]}}
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from app.services.ingestion import DeviceNotFoundError, IngestionConflictError

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def _error(status_code: int, code: str, message: str, details: list[ErrorDetail] | None = None) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json", exclude_none=True))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default body echoes the rejected input back (including URLs and any extra fields
    # the client sent). Keep only where and why the request was rejected.
    details = [
        ErrorDetail(loc=list(error["loc"]), msg=error["msg"], type=error["type"]) for error in exc.errors()
    ]
    return _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_error", "The request is invalid.", details)


async def _device_not_found(request: Request, exc: DeviceNotFoundError) -> JSONResponse:
    return _error(status.HTTP_404_NOT_FOUND, "device_not_found", "No such device for this user.")


async def _conflict(request: Request, exc: IngestionConflictError) -> JSONResponse:
    return _error(status.HTTP_409_CONFLICT, "conflict", "The request conflicted with existing data. Retry it.")


async def _database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    logger.error("Database unavailable during %s %s", request.method, request.url.path)
    return _error(status.HTTP_503_SERVICE_UNAVAILABLE, "database_unavailable", "The service is temporarily unavailable.")


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Path only (never the query string). Starlette re-raises after responding, so the server log
    # still carries the traceback for operators; the client learns nothing.
    logger.error("Unhandled %s during %s %s", type(exc).__name__, request.method, request.url.path)
    return _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "An unexpected error occurred.")


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(DeviceNotFoundError, _device_not_found)
    app.add_exception_handler(IngestionConflictError, _conflict)
    app.add_exception_handler(OperationalError, _database_unavailable)
    app.add_exception_handler(Exception, _unexpected_error)
