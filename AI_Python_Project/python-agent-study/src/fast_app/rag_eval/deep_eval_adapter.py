"""DeepEval 与 OpenAI-compatible Qwen 之间的隔离 Adapter。"""

from __future__ import annotations

import json
import os
from collections.abc import MutableMapping
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from fast_app.rag_eval.config import RagEvalJudgeSettings


class UnsafeDeepEvalConfigurationError(RuntimeError):
    """本地评测检测到可能触发云端上传的 DeepEval 配置。"""


class JudgeStructuredOutputError(RuntimeError):
    """Judge 未返回可由目标 Pydantic Schema 校验的 JSON。"""


def configure_deepeval_environment(
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """在 import deepeval 前强制本地、无遥测、无 dotenv 模式。"""

    values = environ if environ is not None else os.environ
    if values.get("CONFIDENT_API_KEY", "").strip():
        raise UnsafeDeepEvalConfigurationError(
            "轻量 Eval 禁止配置 CONFIDENT_API_KEY，避免结果上传"
        )
    values["DEEPEVAL_DISABLE_DOTENV"] = "1"
    values["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
    values["DEEPEVAL_DISABLE_LEGACY_KEYFILE"] = "1"
    values["DEEPEVAL_NO_INSPECT_PROMPT"] = "1"
    values["DEEPEVAL_FILE_SYSTEM"] = "READ_ONLY"


configure_deepeval_environment()

try:
    from deepeval.models import DeepEvalBaseLLM
except ImportError as exc:  # pragma: no cover - 由独立环境冒烟测试覆盖
    raise RuntimeError(
        "未安装 DeepEval；请使用 .venv-rag-eval 安装 requirements-eval.txt"
    ) from exc


def _message_content(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


class QwenDeepEvalModel(DeepEvalBaseLLM):
    """让 DeepEval 的所有指标使用独立 Qwen Judge。"""

    def __init__(
        self,
        *,
        settings: RagEvalJudgeSettings,
        chat_model: Any | None = None,
    ) -> None:
        self.settings = settings
        self._model = chat_model or ChatOpenAI(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            model=settings.model_name,
            temperature=settings.temperature,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
        )

    def load_model(self) -> Any:
        return self._model

    def get_model_name(self) -> str:
        return self.settings.model_name

    def generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        messages = [HumanMessage(content=prompt)]
        if schema is None:
            return _message_content(self._model.invoke(messages))
        return self._generate_structured_sync(messages, schema)

    async def a_generate(
        self,
        prompt: str,
        schema: type[BaseModel] | None = None,
    ) -> str | BaseModel:
        messages = [HumanMessage(content=prompt)]
        if schema is None:
            return _message_content(await self._model.ainvoke(messages))
        return await self._generate_structured_async(messages, schema)

    def _generate_structured_sync(
        self,
        messages: list[HumanMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        last_error: Exception | None = None
        for method in ("json_schema", "function_calling"):
            try:
                value = self._model.with_structured_output(
                    schema,
                    method=method,
                ).invoke(messages)
                return value if isinstance(value, schema) else schema.model_validate(value)
            except Exception as exc:
                last_error = exc
        try:
            raw = self._model.invoke(
                [
                    *messages,
                    SystemMessage(
                        content=(
                            "只输出符合以下 JSON Schema 的 JSON object：\n"
                            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                        )
                    ),
                ]
            )
            return schema.model_validate(json.loads(_message_content(raw)))
        except Exception as exc:
            raise JudgeStructuredOutputError(
                "Judge 无法返回合法 JSON Schema 结构化输出"
            ) from (last_error or exc)

    async def _generate_structured_async(
        self,
        messages: list[HumanMessage],
        schema: type[BaseModel],
    ) -> BaseModel:
        last_error: Exception | None = None
        for method in ("json_schema", "function_calling"):
            try:
                value = await self._model.with_structured_output(
                    schema,
                    method=method,
                ).ainvoke(messages)
                return value if isinstance(value, schema) else schema.model_validate(value)
            except Exception as exc:
                last_error = exc
        try:
            raw = await self._model.ainvoke(
                [
                    *messages,
                    SystemMessage(
                        content=(
                            "只输出符合以下 JSON Schema 的 JSON object：\n"
                            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
                        )
                    ),
                ]
            )
            return schema.model_validate(json.loads(_message_content(raw)))
        except Exception as exc:
            raise JudgeStructuredOutputError(
                "Judge 无法返回合法 JSON Schema 结构化输出"
            ) from (last_error or exc)


__all__ = [
    "QwenDeepEvalModel",
    "JudgeStructuredOutputError",
    "UnsafeDeepEvalConfigurationError",
    "configure_deepeval_environment",
]
