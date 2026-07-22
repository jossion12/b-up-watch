"""统一错误格式与全局异常处理。

响应格式（接口文档 1.3）：
{
    "error": {"code": "...", "message": "...", "details": {...}}
}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class BizError(Exception):
    """业务异常：携带 HTTP 状态码与业务错误码。"""

    def __init__(self, code: str, message: str, http_status: int = 400, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


def _err_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz(_: Request, exc: BizError) -> JSONResponse:  # noqa: ANN001
        return JSONResponse(
            status_code=exc.http_status,
            content=_err_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: ANN001
        return JSONResponse(
            status_code=400,
            content=_err_payload("INVALID_PARAM", "参数错误", {"errors": exc.errors()}),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:  # noqa: ANN001
        log.exception("unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content=_err_payload("INTERNAL_ERROR", "服务内部错误"),
        )