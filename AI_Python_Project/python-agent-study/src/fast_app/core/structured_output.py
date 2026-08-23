"""OpenAI-compatible 模型的有限 structured-output 适配。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, TypeVar

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
    before_provider_call: Callable[[], Awaitable[None]] | None = None,
    max_provider_calls: int = 5,
    max_attempts_per_transport: int = 2,
    retry_base_delay_seconds: float = 0.0,
) -> StructuredModel:
    """使用最近成功 transport，并在一个共享预算内有限重试和回退。"""

    if max_provider_calls < 1:
        raise ValueError("max_provider_calls 必须大于零")
    if max_attempts_per_transport < 1:
        raise ValueError("max_attempts_per_transport 必须大于零")
    if retry_base_delay_seconds < 0:
        raise ValueError("retry_base_delay_seconds 不能为负数")

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
        while attempts < max_attempts_per_transport and calls < max_provider_calls:
            attempts += 1
            # ownership/cancellation hook 不属于 Provider 技术失败。它必须在真实
            # 调用前执行，并原样传播，不能被 fallback/retry 吞掉。
            if before_provider_call is not None:
                await before_provider_call()
            calls += 1
            try:
                value = await _invoke_transport(
                    model, schema, retry_messages, transport, config
                )
                _TRANSPORT_CACHE[key] = transport
                return value
            except Exception as exc:
                last_error = exc
                http_status = _http_status_code(exc)
                provider_error_code = _provider_error_code(exc)
                logger.warning(
                    "structured_output transport=%s attempt=%s error_type=%s "
                    "http_status=%s provider_error_code=%s validation_errors=%s",
                    transport,
                    attempts,
                    type(exc).__name__,
                    http_status,
                    provider_error_code,
                    (
                        exc.errors(include_input=False)
                        if isinstance(exc, ValidationError)
                        else None
                    ),
                )
                # structured-output transport 的 HTTP 400 是确定性请求拒绝；
                # 立即尝试下一协议，避免原样重放。strict_json 已是最终兜底。
                if _transport_unsupported(exc) or (
                    transport != "strict_json" and http_status == 400
                ):
                    if _TRANSPORT_CACHE.get(key) == transport:
                        _TRANSPORT_CACHE.pop(key, None)
                    break
                if http_status is not None and 400 <= http_status < 500 and http_status != 429:
                    raise
                if isinstance(exc, ValidationError) and attempts < max_attempts_per_transport:
                    details = "; ".join(
                        (
                            f"{'.'.join(map(str, item['loc'])) or '<root>'}: "
                            f"{item['msg']}"
                        )
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
                retryable = (
                    isinstance(exc, (TimeoutError, ValidationError))
                    or http_status == 429
                    or (http_status is not None and http_status >= 500)
                    # 保持旧调用者的兼容语义：没有 HTTP 状态的技术异常在当前
                    # transport 中仍允许一次有限重试。
                    or http_status is None
                )
                if (
                    not retryable
                    or attempts >= max_attempts_per_transport
                    or calls >= max_provider_calls
                ):
                    raise
                delay = retry_base_delay_seconds * (2 ** (attempts - 1))
                if delay > 0:
                    await asyncio.sleep(delay)
        if calls >= max_provider_calls:
            break
    raise RuntimeError("模型不支持可用的 structured-output transport") from last_error


async def _invoke_transport(model, schema, messages, transport, config):
    if transport in {"json_schema", "function_calling"}:
        value = await model.with_structured_output(
            schema, method=transport
        ).ainvoke(messages, config=config)
        return value if isinstance(value, schema) else schema.model_validate(value)
    if transport == "json_mode":
        response = await model.bind(
            response_format={"type": "json_object"}
        ).ainvoke(messages, config=config)
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


def _http_status_code(exc: Exception) -> int | None:
    """读取 OpenAI-compatible SDK 的状态码，不依赖 provider 错误文案。"""

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None


def _provider_error_code(exc: Exception) -> str | None:
    """只记录非敏感 provider 错误码，不把错误正文或请求 Schema 写入日志。"""

    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    code = body.get("code")
    if code is None and isinstance(body.get("error"), dict):
        code = body["error"].get("code")
    return str(code) if code is not None else None


__all__ = ["invoke_structured_model"]
