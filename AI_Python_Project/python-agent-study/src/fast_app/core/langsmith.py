import os
from contextlib import nullcontext
from typing import Any

from langsmith import trace

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.core.request_context import get_request_id, get_trace_id
from fast_app.schemas.rag_chat_schema import RagChatRequest


logger = get_logger(__name__)


def is_langsmith_enabled(settings: Settings) -> bool:
    return settings.langsmith_tracing and bool(settings.langsmith_api_key)


def configure_langsmith(settings: Settings) -> None:
    if not is_langsmith_enabled(settings):
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        logger.info(
            "langsmith_config %s",
            format_log_fields(
                event="langsmith.config.disabled",
                reason="tracing_disabled_or_missing_api_key",
            ),
        )
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project

    logger.info(
        "langsmith_config %s",
        format_log_fields(
            event="langsmith.config.enabled",
            project=settings.langsmith_project,
            endpoint=settings.langsmith_endpoint,
        ),
    )

# 把用户 query 写入 LangSmith 需要能在 LangSmith 中看到问题输入
def build_rag_langsmith_inputs(req: RagChatRequest) -> dict[str, Any]:
    return {
        "query": req.query,
        "mode": req.mode,
        "top_k": req.top_k,
        "candidate_k": req.candidate_k,
        "min_score": req.min_score,
        "filters": req.filters.model_dump(),
    }

# 让 LangSmith run 可以和本地日志、服务配置、RAG 参数关联
def build_rag_langsmith_metadata(
    settings: Settings,
    req: RagChatRequest,
    pipeline_provider: str,
) -> dict[str, Any]:
    return {
        "request_id": get_request_id(),
        "trace_id": get_trace_id(),
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "pipeline_provider": pipeline_provider,
        "mode": req.mode,
        "top_k": req.top_k,
        "candidate_k": req.candidate_k,
        "min_score": req.min_score,
        "llm_provider": settings.llm_provider,
        "llm_model_name": settings.llm_model_name,
        "vector_retriever_provider": settings.vector_retriever_provider,
        "keyword_retriever_provider": settings.keyword_retriever_provider,
        "reranker_provider": settings.reranker_provider,
        "rerank_model_name": settings.rerank_model_name,
    }

# 让 LangSmith UI 可以按场景过滤
def build_rag_langsmith_tags(
    settings: Settings,
    pipeline_provider: str,
    operation: str,
) -> list[str]:
    tags = [
        "rag",
        f"operation:{operation}",
        f"pipeline:{pipeline_provider}",
        f"env:{settings.app_env}",
        f"llm:{settings.llm_provider}",
    ]
    tags.extend(settings.langsmith_tag_list)
    return tags

# 手动控制一次trace的格式
def rag_langsmith_trace(
    settings: Settings,
    name: str,
    inputs: dict[str, Any],
    metadata: dict[str, Any],
    tags: list[str],
):
    if not is_langsmith_enabled(settings):
        return nullcontext()

    return trace(
        name=name,
        run_type="chain", # 固定支持的类型："tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"
        inputs=inputs,
        project_name=settings.langsmith_project,
        metadata=metadata,
        tags=tags,
    )
