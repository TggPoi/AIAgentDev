from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from fast_app.core.logging import get_logger

from fast_app.services.exceptions import (
    AppServiceError,
    ExternalServiceError,
    LLMCallError,
    NoSearchResultError,
)


logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    
    @app.exception_handler(NoSearchResultError)
    async def handle_no_search_result_error(
        request: Request,
        exc: NoSearchResultError,
    ) -> JSONResponse:
        logger.warning(
            "没有检索结果: path=%s, message=%s",
            request.url.path,
            str(exc),
        )

        return JSONResponse(
            status_code=404,
            content={
                "code": "NO_SEARCH_RESULT",
                "message": str(exc),
            },
        )

    @app.exception_handler(ExternalServiceError)
    async def handle_external_service_error(
        request: Request,
        exc: ExternalServiceError,
    ) -> JSONResponse:
        logger.error(
            "外部服务异常: path=%s, message=%s",
            request.url.path,
            str(exc),
        )

        return JSONResponse(
            status_code=503,
            content={
                "code": "EXTERNAL_SERVICE_ERROR",
                "message": str(exc),
            },
        )

    @app.exception_handler(AppServiceError)
    async def handle_app_service_error(
        request: Request,
        exc: AppServiceError,
    ) -> JSONResponse:
        logger.error(
            "业务异常: path=%s, message=%s",
            request.url.path,
            str(exc),
        )

        return JSONResponse(
            status_code=400,
            content={
                "code": "APP_SERVICE_ERROR",
                "message": str(exc),
            },
        )


    @app.exception_handler(LLMCallError)
    async def handle_llm_call_error(
        request: Request,
        exc: LLMCallError,
    ) -> JSONResponse:
        logger.error(
            "大模型调用异常: path=%s, message=%s",
            request.url.path,
            str(exc),
        )

        return JSONResponse(
            status_code=503,
            content={
                "code": "LLM_CALL_ERROR",
                "message": str(exc),
            },
        )


    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "未知服务端异常: path=%s",
            request.url.path,
        )

        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "服务器内部错误",
            },
        )