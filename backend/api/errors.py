"""Normalize application, validation and unhandled API errors to safe public bodies."""

from logging import getLogger

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from public_error import public_error


# Handler params stay untyped, matching api/auth.rate_limit_handler: Starlette's overloaded add_exception_handler rejects specifically-typed handlers under Pyright.
def _http_exception_handler(_request, exc):
    detail = exc.detail
    if isinstance(detail, dict):
        body = {
            "code": detail.get("code", "error"),
            "message": detail.get("message", "Request failed."),
            "retryable": detail.get("retryable", False),
        }
    else:
        body = {"code": "error", "message": str(detail), "retryable": False}
    # Preserve auth/rate-limit headers and the intentionally indistinguishable transfer messages.
    return JSONResponse(status_code=exc.status_code, content={"detail": body}, headers=getattr(exc, "headers", None))


def _validation_handler(_request, _exc):
    # Never echo pydantic's raw errors: they can carry submitted input values.
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "invalid_request", "message": "The request was malformed.", "retryable": False}},
    )


def _unhandled_handler(_request, exc):
    getLogger(__name__).warning("unhandled API error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": public_error(exc)})


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
