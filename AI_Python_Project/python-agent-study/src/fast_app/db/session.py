from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fast_app.core.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    """根据配置创建 SQLAlchemy 异步 Engine，用于session和数据库的连接"""

    return create_async_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )


def create_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """创建请求级 AsyncSession 工厂，由 FastAPI dependency 负责打开和关闭。用于业务层操作数据库"""

    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
