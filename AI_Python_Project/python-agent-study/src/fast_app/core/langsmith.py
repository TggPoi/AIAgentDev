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
    """判断当前进程是否应该真正写入 LangSmith。

    这里同时检查两个条件：
    1. `LANGSMITH_TRACING=true`：表示用户明确开启 tracing。
    2. `LANGSMITH_API_KEY` 不为空：表示具备写入远程 LangSmith 的凭证。

    这样可以避免只打开开关但没有 API Key 时，业务代码仍然尝试访问 LangSmith。
    """
    return settings.langsmith_tracing and bool(settings.langsmith_api_key)


def configure_langsmith(settings: Settings) -> None:
    """把项目 Settings 同步成 LangSmith / LangChain SDK 能读取的环境变量。

    当前工程使用 Pydantic Settings 读取 `.env`，但 LangSmith 和 LangChain
    SDK 通常从 `os.environ` 读取配置。因此应用启动时需要调用这个函数，
    把 `settings.langsmith_*` 同步到当前 Python 进程的环境变量中。

    这个函数只负责配置环境和记录配置日志，不创建具体 trace。
    """
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


def build_rag_langsmith_inputs(req: RagChatRequest) -> dict[str, Any]:
    """构造 pipeline root run 的 inputs。

    inputs 表示“这次 RAG 请求的业务输入是什么”。root run 需要包含用户问题
    和 RAG 控制参数，这样你在 LangSmith UI 中打开一次请求时，可以直接看到
    这次请求问了什么、使用了什么检索模式、top_k 等参数。

    注意：inputs 会上传到 LangSmith。后续生产环境需要结合脱敏策略决定
    是否保留完整 query。
    """
    return {
        "query": req.query,
        "mode": req.mode,
        "top_k": req.top_k,
        "candidate_k": req.candidate_k,
        "min_score": req.min_score,
        "filters": req.filters.model_dump(),
    }


def build_rag_langsmith_metadata(
    settings: Settings,
    req: RagChatRequest,
    pipeline_provider: str,
) -> dict[str, Any]:
    """构造 pipeline root run 的 metadata。

    metadata 用来描述“这次请求运行在什么上下文中”。它不会替代 inputs，
    而是补充 request_id、trace_id、环境、provider、模型名等排查信息。

    最关键的是 `request_id` 和 `trace_id`：
    - 本地结构化日志里有它们。
    - LangSmith metadata 里也有它们。
    - 排查时就能把本地日志和 LangSmith trace 串起来。
    """
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


def build_rag_langsmith_tags(
    settings: Settings,
    pipeline_provider: str,
    operation: str,
) -> list[str]:
    """构造 pipeline root run 的 tags。

    tags 是短标签，主要用于 LangSmith UI 中过滤和分组。
    例如：
    - `pipeline:classic`：只看 Classic Pipeline。
    - `pipeline:langgraph`：只看 LangGraph Pipeline。
    - `operation:stream_events`：只看结构化流式接口。

    和 metadata 的区别：
    metadata 更适合放结构化详情，tags 更适合做快速筛选。
    """
    tags = [
        "rag",
        f"operation:{operation}",
        f"pipeline:{pipeline_provider}",
        f"env:{settings.app_env}",
        f"llm:{settings.llm_provider}",
    ]
    tags.extend(settings.langsmith_tag_list)
    return tags


def langsmith_trace(
    settings: Settings,
    name: str,
    run_type: str,
    inputs: dict[str, Any],
    metadata: dict[str, Any],
    tags: list[str],
):
    """最底层的 LangSmith trace context 封装。

    其他函数最终都会调用到这里。它的职责很单一：
    - LangSmith 未开启时，返回 `nullcontext()`，业务代码可以照常执行。
    - LangSmith 开启时，返回 `langsmith.trace(...)`，把被 `with` 包裹的代码
      记录为一个 LangSmith run。

    `run_type` 由调用方传入，因为 root run、retriever step、chain step
    在 LangSmith 中应该有不同的类型。
    """
    if not is_langsmith_enabled(settings):
        return nullcontext()

    return trace(
        name=name,
        # 支持的常用类型："tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"
        run_type=run_type,
        inputs=inputs,
        project_name=settings.langsmith_project,
        metadata=metadata,
        tags=tags,
    )


def rag_langsmith_trace(
    settings: Settings,
    name: str,
    inputs: dict[str, Any],
    metadata: dict[str, Any],
    tags: list[str],
):
    """创建一次完整 RAG 请求的 pipeline root run。

    root run 表示“一次业务请求的外层边界”，例如：
    - `classic_rag_pipeline.run`
    - `langgraph_rag_pipeline.stream_events`

    它会额外写入：
    - `trace_level=pipeline`
    - `trace-level:pipeline`

    这样在 LangSmith 中可以区分：
    - pipeline run：整条链路。
    - step run：链路中的某一步。
    """
    return langsmith_trace(
        settings=settings,
        name=name,
        run_type="chain",
        inputs=inputs,
        metadata={
            **metadata,
            "trace_level": "pipeline",
        },
        tags=[
            *tags,
            "trace-level:pipeline",
        ],
    )


def build_rag_langsmith_step_metadata(
    settings: Settings,
    req: RagChatRequest,
    pipeline_provider: str,
    operation: str,
    step_name: str,
    step_index: int,
) -> dict[str, Any]:
    """根据 FastAPI 请求模型构造 step run 的 metadata。

    Classic Pipeline 中每一步都能拿到完整的 `RagChatRequest`，所以直接复用
    `build_rag_langsmith_metadata()`，再追加 step 级字段。

    step 级字段用于回答：
    - 当前 run 是哪一步：`retrieve` / `rerank` / `build_context`。
    - 当前 run 属于哪个入口：`run` / `stream` / `stream_events`。
    - 当前步骤在链路中排第几。
    """
    return {
        **build_rag_langsmith_metadata(
            settings=settings,
            req=req,
            pipeline_provider=pipeline_provider,
        ),
        "trace_level": "step",
        "operation": operation,
        "step_name": step_name,
        "step_index": step_index,
    }


def build_rag_langsmith_step_metadata_from_state(
    settings: Settings,
    state: dict[str, Any],
    pipeline_provider: str,
    operation: str,
    step_name: str,
    step_index: int,
) -> dict[str, Any]:
    """根据 LangGraph state 构造 step run 的 metadata。

    LangGraph node 内部拿到的是 `GraphRagState`，不是 `RagChatRequest`。
    所以这里提供一个 state 版本的 metadata 构造函数。

    它和 `build_rag_langsmith_step_metadata()` 的目标一致，只是数据来源不同：
    - Classic Pipeline：从 `RagChatRequest` 取参数。
    - LangGraph Pipeline：从 `GraphRagState` 取参数。

    这样两条链路最终写入 LangSmith 的字段结构仍然保持一致。
    """
    return {
        "request_id": get_request_id(),
        "trace_id": get_trace_id(),
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "pipeline_provider": pipeline_provider,
        "mode": state.get("mode"),
        "top_k": state.get("top_k"),
        "candidate_k": state.get("candidate_k"),
        "min_score": state.get("min_score"),
        "llm_provider": settings.llm_provider,
        "llm_model_name": settings.llm_model_name,
        "vector_retriever_provider": settings.vector_retriever_provider,
        "keyword_retriever_provider": settings.keyword_retriever_provider,
        "reranker_provider": settings.reranker_provider,
        "rerank_model_name": settings.rerank_model_name,
        "trace_level": "step",
        "operation": operation,
        "step_name": step_name,
        "step_index": step_index,
    }


def build_rag_langsmith_step_tags(
    settings: Settings,
    pipeline_provider: str,
    operation: str,
    step_name: str,
) -> list[str]:
    """构造 step run 的 tags。

    step run 会继承 pipeline 级 tags，并额外增加：
    - `trace-level:step`
    - `step:{step_name}`

    这样你可以在 LangSmith UI 中过滤：
    - 只看 retrieve。
    - 只看 rerank。
    - 只看 Classic 的 build_context。
    - 只看 LangGraph 的 stream_generate。
    """
    return [
        *build_rag_langsmith_tags(
            settings=settings,
            pipeline_provider=pipeline_provider,
            operation=operation,
        ),
        "trace-level:step",
        f"step:{step_name}",
    ]


def rag_langsmith_step_trace(
    settings: Settings,
    name: str,
    run_type: str,
    inputs: dict[str, Any],
    metadata: dict[str, Any],
    tags: list[str],
):
    """创建 RAG 链路中某一个业务步骤的 step run。

    这个函数不会自己构造 metadata / tags，而是要求调用方传入。
    原因是 Classic 和 LangGraph 的数据来源不同：
    - Classic 从 `RagChatRequest` 构造 metadata。
    - LangGraph 从 `GraphRagState` 构造 metadata。

    它只负责把“某一步代码”包装成 LangSmith run，例如：
    - `classic_rag_pipeline.run.retrieve`
    - `langgraph_rag_pipeline.stream_events.emit_sources`
    """
    return langsmith_trace(
        settings=settings,
        name=name,
        run_type=run_type,
        inputs=inputs,
        metadata=metadata,
        tags=tags,
    )
