"""Định dạng lỗi thống nhất: {"error": {"code", "message", "details"}}."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found_or_mismatch(kind: str) -> ApiError:
    """Không phân biệt "không tồn tại" và "sai SĐT" để tránh dò mã (IDV-01)."""
    return ApiError(
        404,
        f"{kind.upper()}_NOT_FOUND_OR_PHONE_MISMATCH",
        "Không tìm thấy thông tin khớp với mã và số điện thoại đã cung cấp. "
        "Vui lòng kiểm tra lại mã và số điện thoại người đặt.",
    )


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        body = {"error": {"code": exc.code, "message": exc.message}}
        if exc.details is not None:
            body["error"]["details"] = jsonable_encoder(exc.details)
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "VALIDATION_ERROR", "message": "Dữ liệu gửi lên không hợp lệ.",
                               "details": jsonable_encoder(errors)}},
        )
