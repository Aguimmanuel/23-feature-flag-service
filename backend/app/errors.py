"""Shared, sanitized error responses for HTTP routes."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, TimeoutError as DatabaseTimeoutError
from starlette.exceptions import HTTPException


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def error_response(status_code: int, code: str, message: str, details=None, headers=None):
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or []}},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return error_response(exc.status_code, exc.code, exc.message, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Never serialize Pydantic's input, ctx, or arbitrary validator messages.
        details = []
        for error in exc.errors():
            location = list(error["loc"])
            if location and location[0] in {"body", "path", "query", "header"}:
                location = location[1:]
            details.append({
                "field": ".".join(str(part) for part in location) or "body",
                "message": "Field is required" if error["type"] == "missing" else "Invalid value",
            })
        return error_response(422, "VALIDATION_ERROR", "Request validation failed", details)

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        # Framework transport errors are distinct from domain FLAG_NOT_FOUND.
        if exc.status_code == 401:
            return error_response(401, "UNAUTHORIZED", "Authentication required")
        return error_response(exc.status_code, "HTTP_ERROR", "HTTP request could not be processed")

    async def database_error_handler(request: Request, exc: Exception):
        return error_response(503, "SERVICE_UNAVAILABLE", "Database service is unavailable")

    app.add_exception_handler(OperationalError, database_error_handler)
    app.add_exception_handler(DatabaseTimeoutError, database_error_handler)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        return error_response(500, "INTERNAL_ERROR", "An unexpected error occurred")
