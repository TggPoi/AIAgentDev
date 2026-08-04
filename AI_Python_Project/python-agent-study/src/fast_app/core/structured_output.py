"""OpenAI-compatible 模型的有限 structured-output 适配。"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel
from pydantic import ValidationError


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
_TRANSPORT_CACHE: dict[tuple[str, str, str], str] = {}
logger = logging.getLogger(__name__)


async def invoke_structured_model(
    *,
    model: BaseChatModel,
    schema: type[StructuredModel],
    messages: list[BaseMessage],
    config: RunnableConfig | None = None,
) -> StructuredModel:
    """使用最近成功 transport，最多五次技术调用后返回 Pydantic 模型。"""

    key = (
        type(model).__name__,
        str(getattr(model, "model_name", "unknown")),
        str(getattr(model, "openai_api_base", None) or getattr(model, "base_url", "")),
    )
    cached = _TRANSPORT_CACHE.get(key)
    transports = ["json_schema", "function_calling", "json_mode", "strict_json"]
    if cached in transports:
        transports.remove(cached)
        transports.insert(0, cached)

    calls = 0
    last_error: Exception | None = None
    for transport in transports:
        attempts = 0
        retry_messages = messages
        while attempts < 2 and calls < 5:
            attempts += 1
            calls += 1
            try:
                value = await _invoke_transport(model, schema, retry_messages, transport, config)
                _TRANSPORT_CACHE[key] = transport
                return value
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "structured_output transport=%s attempt=%s error_type=%s validation_errors=%s",
                    transport,
                    attempts,
                    type(exc).__name__,
                    exc.errors(include_input=False) if isinstance(exc, ValidationError) else None,
                )
                if _transport_unsupported(exc):
                    if _TRANSPORT_CACHE.get(key) == transport:
                        _TRANSPORT_CACHE.pop(key, None)
                    break
                if isinstance(exc, ValidationError) and attempts == 1:
                    details = "; ".join(
                        f"{'.'.join(map(str, item['loc'])) or '<root>'}: {item['msg']}"
                        for item in exc.errors(include_input=False)
                    )
                    retry_messages = [
                        *messages,
                        SystemMessage(
                            content=(
                                "上一次结构化响应未通过 Schema 校验。只修正以下契约错误，"
                                "不要改变用户任务语义；重新输出完整对象：\n" + details
                            )
                        ),
                    ]
                if attempts == 2:
                    raise
    raise RuntimeError("模型不支持可用的 structured-output transport") from last_error


async def _invoke_transport(model, schema, messages, transport, config):
    if transport in {"json_schema", "function_calling"}:
        value = await model.with_structured_output(schema, method=transport).ainvoke(messages, config=config)
        return value if isinstance(value, schema) else schema.model_validate(value)
    if transport == "json_mode":
        response = await model.bind(response_format={"type": "json_object"}).ainvoke(messages, config=config)
    else:
        response = await model.ainvoke(
            [
                *messages,
                SystemMessage(
                    content=(
                        "只输出符合以下 JSON Schema 的单个 JSON object，不要输出 Markdown：\n"
                        + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                    )
                ),
            ],
            config=config,
        )
    content = str(getattr(response, "content", response)).strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:].strip()
    return schema.model_validate(json.loads(content))


def _transport_unsupported(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "unsupported response_format",
            "unsupported tool",
            "not support json_schema",
            "not support function",
            "unknown parameter: response_format",
        )
    )


__all__ = ["invoke_structured_model"]
