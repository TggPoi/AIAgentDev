from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fast_app.api.chat_routes import router as chat_router
from fast_app.api.health_routes import router as health_router
from fast_app.api.rag_chat_routes import router as rag_chat_router
from fast_app.api.rag_routes import router as rag_router
from fast_app.api.stream_routes import router as stream_router
from fast_app.api.error_demo_routes import router as error_demo_router
from fast_app.core.config import get_settings
from fast_app.core.logging import get_logger, setup_logging

from fast_app.core.exception_handlers import register_exception_handlers


settings = get_settings()
logger = get_logger(__name__)

# 把一个 async generator 函数，包装成可以用于管理“进入 / 退出”流程的上下文管理器。
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging(settings)

    logger.info("应用启动: app_name=%s, env=%s", settings.app_name, settings.app_env)

    # 应用启动时，FastAPI 会执行 lifespan 中 `yield` 之前的代码

    yield

    # 应用关闭时，执行 `yield` 后面的代码
    logger.info("应用关闭")


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(rag_router)
app.include_router(rag_chat_router)
app.include_router(stream_router)
app.include_router(error_demo_router)