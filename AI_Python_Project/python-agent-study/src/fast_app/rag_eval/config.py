"""轻量 Eval 的独立 Judge 配置。"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class RagEvalJudgeSettings(BaseModel):
    """不继承主生成模型凭据的独立 Judge 配置。"""

    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(
        description="Judge OpenAI-compatible endpoint 的独立密钥。",
    )
    base_url: str = Field(
        min_length=1,
        description="Judge OpenAI-compatible API 根地址，不从主 LLM 隐式继承。",
    )
    model_name: str = Field(
        min_length=1,
        description="DeepEval 使用的独立 Qwen Judge 模型名。",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Judge 采样温度；普通回归默认使用确定性的 0。",
    )
    timeout_seconds: float = Field(
        default=60.0,
        gt=0.0,
        description="单次 Judge 模型请求的超时秒数。",
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Judge SDK 对瞬态请求的最大重试次数。",
    )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "RagEvalJudgeSettings":
        """只从 RAG_EVAL_JUDGE_* 环境变量构造配置。"""

        values = environ or os.environ
        required = {
            "api_key": "RAG_EVAL_JUDGE_API_KEY",
            "base_url": "RAG_EVAL_JUDGE_BASE_URL",
            "model_name": "RAG_EVAL_JUDGE_MODEL_NAME",
        }
        missing = [env_name for env_name in required.values() if not values.get(env_name)]
        if missing:
            raise ValueError("缺少独立 Judge 配置: " + ", ".join(missing))
        return cls(
            **{field: values[env_name] for field, env_name in required.items()},
            temperature=float(values.get("RAG_EVAL_JUDGE_TEMPERATURE", "0")),
            timeout_seconds=float(
                values.get("RAG_EVAL_JUDGE_TIMEOUT_SECONDS", "60")
            ),
            max_retries=int(values.get("RAG_EVAL_JUDGE_MAX_RETRIES", "0")),
        )


__all__ = ["RagEvalJudgeSettings"]
