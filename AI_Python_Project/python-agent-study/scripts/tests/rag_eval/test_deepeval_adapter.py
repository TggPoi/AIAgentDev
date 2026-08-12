"""隔离 DeepEval/Qwen Judge Adapter 的兼容性测试。"""

import asyncio
from importlib.metadata import version
import os
import sys
from typing import get_args
from unittest.mock import patch

from pydantic import BaseModel, Field

from fast_app.rag_eval.config import RagEvalJudgeSettings
from fast_app.rag_eval.deep_eval_adapter import (
    QwenDeepEvalModel,
    UnsafeDeepEvalConfigurationError,
    configure_deepeval_environment,
)
from fast_app.rag_eval.generation_worker import evaluate_request, evaluate_with_model
from fast_app.rag_eval.models import GenerationEvaluationRequest
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, SingleTurnParams


class JudgePayload(BaseModel):
    value: str = Field(description="Judge 返回的测试值。")


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeStructuredInvoker:
    def __init__(self, schema: type[BaseModel]) -> None:
        self.schema = schema

    def invoke(self, _messages):
        return self._value("sync-structured")

    async def ainvoke(self, _messages):
        return self._value("async-structured")

    def _value(self, default_value: str):
        fields = self.schema.model_fields
        if "value" in fields:
            return self.schema(value=default_value)
        if "truths" in fields:
            return self.schema(truths=["上下文事实"])
        if "claims" in fields:
            return self.schema(claims=["上下文事实"])
        if "statements" in fields:
            return self.schema(statements=["回答问题"])
        if "verdicts" in fields:
            inner = get_args(fields["verdicts"].annotation)[0]
            return self.schema(verdicts=[inner(verdict="yes")])
        if "score" in fields:
            return self.schema(score=8.0, reason="覆盖充分")
        raise AssertionError(f"未覆盖的 DeepEval Schema: {self.schema}")


class FakeChatModel:
    def invoke(self, _messages):
        return FakeResponse("sync-text")

    async def ainvoke(self, _messages):
        return FakeResponse("async-text")

    def with_structured_output(self, schema, *, method):
        assert method == "json_schema"
        return FakeStructuredInvoker(schema)


class FailingJudge(DeepEvalBaseLLM):
    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return "failing-judge"

    def generate(self, prompt: str, schema=None):
        del prompt, schema
        raise self.failure

    async def a_generate(self, prompt: str, schema=None):
        del prompt, schema
        raise self.failure


class RecordingJudge(DeepEvalBaseLLM):
    """记录 DeepEval 最终 Judge Prompt，并返回合法的 0-10 原始分。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return "recording-judge"

    def generate(self, prompt: str, schema=None):
        self.prompts.append(prompt)
        return schema(score=8.0, reason="覆盖充分")

    async def a_generate(self, prompt: str, schema=None):
        self.prompts.append(prompt)
        return schema(score=8.0, reason="覆盖充分")


def build_adapter() -> QwenDeepEvalModel:
    settings = RagEvalJudgeSettings(
        api_key="test-only-key",
        base_url="https://judge.invalid/v1",
        model_name="qwen-test",
    )
    return QwenDeepEvalModel(settings=settings, chat_model=FakeChatModel())


def test_offline_environment_is_forced_before_deepeval_use() -> None:
    assert sys.version_info[:2] == (3, 12)
    assert version("deepeval") == "4.1.3"
    assert os.environ["DEEPEVAL_DISABLE_DOTENV"] == "1"
    assert os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] == "1"
    assert os.environ["DEEPEVAL_DISABLE_LEGACY_KEYFILE"] == "1"
    assert os.environ["DEEPEVAL_NO_INSPECT_PROMPT"] == "1"
    assert os.environ["DEEPEVAL_FILE_SYSTEM"] == "READ_ONLY"


def test_confident_cloud_key_is_rejected() -> None:
    try:
        configure_deepeval_environment({"CONFIDENT_API_KEY": "must-not-upload"})
    except UnsafeDeepEvalConfigurationError:
        return
    raise AssertionError("CONFIDENT_API_KEY should be rejected")


def test_adapter_supports_sync_text_and_schema_output() -> None:
    adapter = build_adapter()

    assert adapter.get_model_name() == "qwen-test"
    assert adapter.generate("prompt") == "sync-text"
    assert adapter.generate("prompt", schema=JudgePayload) == JudgePayload(
        value="sync-structured"
    )


async def async_adapter_test() -> None:
    adapter = build_adapter()

    assert await adapter.a_generate("prompt") == "async-text"
    assert await adapter.a_generate("prompt", schema=JudgePayload) == JudgePayload(
        value="async-structured"
    )


async def builtin_metrics_compatibility_test() -> None:
    adapter = build_adapter()
    case = LLMTestCase(
        input="问题",
        actual_output="上下文事实回答问题",
        expected_output="1. 上下文事实",
        retrieval_context=["上下文事实"],
    )
    metrics = [
        FaithfulnessMetric(model=adapter, include_reason=False, async_mode=True),
        AnswerRelevancyMetric(model=adapter, include_reason=False, async_mode=True),
        GEval(
            name="Answer Completeness",
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.EXPECTED_OUTPUT,
            ],
            evaluation_steps=["检查关键事实覆盖比例。"],
            model=adapter,
            async_mode=True,
        ),
        GEval(
            name="Context Utilization",
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
                SingleTurnParams.RETRIEVAL_CONTEXT,
            ],
            evaluation_steps=["检查回答是否有效使用上下文。"],
            model=adapter,
            async_mode=True,
        ),
    ]
    for metric in metrics:
        score = await metric.a_measure(case, _show_indicator=False)
        assert 0.0 <= score <= 1.0


async def no_answer_generation_semantics_test() -> None:
    request = GenerationEvaluationRequest(
        case_id="no-answer",
        question="未知问题",
        answer="",
        retrieval_context=[],
        required_key_facts=[],
        metrics=[
            "generation_faithfulness",
            "generation_answer_relevance",
            "generation_answer_completeness",
            "generation_context_utilization",
        ],
    )
    with patch.dict(
        os.environ,
        {
            "RAG_EVAL_JUDGE_API_KEY": "unused-test-key",
            "RAG_EVAL_JUDGE_BASE_URL": "https://judge.invalid/v1",
            "RAG_EVAL_JUDGE_MODEL_NAME": "qwen-test",
        },
    ):
        response = await evaluate_request(request)
    assert response.metrics["generation_answer_relevance"].score == 0.0
    assert response.metrics["generation_faithfulness"].status == "skipped"
    assert response.metrics["generation_answer_completeness"].status == "skipped"
    assert response.metrics["generation_context_utilization"].status == "skipped"


async def judge_failure_isolation_test() -> None:
    base = GenerationEvaluationRequest(
        case_id="failure-isolation",
        question="问题",
        answer="答案",
        retrieval_context=["上下文"],
        required_key_facts=["事实"],
        metrics=[
            "generation_faithfulness",
            "generation_answer_relevance",
        ],
    )
    timeout_response = await evaluate_with_model(
        base,
        model=FailingJudge(TimeoutError("judge timeout")),
        judge_model="failing-judge",
    )
    assert len(timeout_response.metrics) == 2
    assert {
        result.error.code for result in timeout_response.metrics.values()
    } == {"judge_timeout"}

    for message, expected_code in (
        ("429 rate limit", "judge_rate_limited"),
        ("invalid JSON schema", "judge_invalid_output"),
    ):
        response = await evaluate_with_model(
            base.model_copy(update={"metrics": ["generation_answer_relevance"]}),
            model=FailingJudge(RuntimeError(message)),
            judge_model="failing-judge",
        )
        result = response.metrics["generation_answer_relevance"]
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == expected_code


async def geval_score_scale_contract_test() -> None:
    """自定义步骤必须与 DeepEval GEval 的 0-10 原始分契约一致。"""

    judge = RecordingJudge()
    request = GenerationEvaluationRequest(
        case_id="geval-score-scale",
        question="问题",
        answer="答案",
        retrieval_context=["上下文"],
        required_key_facts=["事实"],
        metrics=[
            "generation_answer_completeness",
            "generation_context_utilization",
        ],
    )

    response = await evaluate_with_model(
        request,
        model=judge,
        judge_model="recording-judge",
    )

    assert len(judge.prompts) == 2
    assert all("给出 0 到 10" in prompt for prompt in judge.prompts)
    assert all("给出 0 到 1 的分数" not in prompt for prompt in judge.prompts)
    assert {
        result.score for result in response.metrics.values()
    } == {0.8}


if __name__ == "__main__":
    test_offline_environment_is_forced_before_deepeval_use()
    test_confident_cloud_key_is_rejected()
    test_adapter_supports_sync_text_and_schema_output()
    asyncio.run(async_adapter_test())
    asyncio.run(builtin_metrics_compatibility_test())
    asyncio.run(no_answer_generation_semantics_test())
    asyncio.run(judge_failure_isolation_test())
    asyncio.run(geval_score_scale_contract_test())
    print("rag_eval DeepEval adapter tests passed")
