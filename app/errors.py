"""Every error leaves the API as {"error": {"code": ..., "message": ...}} (contract 2)."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def bad_request(code: str, message: str) -> ApiError:
    return ApiError(400, code, message)


def forbidden(code: str, message: str) -> ApiError:
    return ApiError(403, code, message)


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = jsonable_encoder(exc.errors(), exclude={"input", "url", "ctx"})
        return JSONResponse(status_code=400, content={"error": {"code": "invalid_request", "message": errors}})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": f"http_{exc.status_code}", "message": str(exc.detail)}},
        )
