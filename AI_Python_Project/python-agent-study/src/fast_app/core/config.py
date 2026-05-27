from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# BaseSettings 读取环境变量
# 读取 .env 文件
# 把字符串配置转换成 Python 类型
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="Python Agent Study", alias="APP_NAME")
    app_env: str = Field(default="dev", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")

    rag_default_top_k: int = Field(default=5, alias="RAG_DEFAULT_TOP_K")
    rag_default_min_score: float = Field(default=0.0, alias="RAG_DEFAULT_MIN_SCORE")
    rag_use_mock: bool = Field(default=True, alias="RAG_USE_MOCK")

    llm_model_name: str = Field(default="mock-llm", alias="LLM_MODEL_NAME")

    milvus_host: str = Field(default="127.0.0.1", alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")

    elasticsearch_url: str = Field(
        default="http://127.0.0.1:9200",
        alias="ELASTICSEARCH_URL",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    cors_allow_origins: str = Field(
    default="http://localhost:5173,http://127.0.0.1:5173",
    alias="CORS_ALLOW_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]

# @lru_cache 第一次调用 get_settings() 时创建 Settings。后续再次调用，直接返回第一次创建好的对象。
# Settings 在应用运行期间通常是稳定的。没有必要每个请求都重新读取 .env。
@lru_cache
def get_settings() -> Settings:
    return Settings()