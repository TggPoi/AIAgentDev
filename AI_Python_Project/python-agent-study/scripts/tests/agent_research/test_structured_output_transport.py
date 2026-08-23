"""Planner、Reviewer、Rewriter 共用 structured-output transport 回归。"""

from __future__ import annotations

import asyncio
from typing import Literal

import httpx
from langchain_core.messages import AIMessage
from openai import BadRequestError
from pydantic import BaseModel, Field

import fast_app.core.structured_output as structured_output


class Payload(BaseModel):
    value: str = Field(description="测试结构化值。")


class StrictPayload(BaseModel):
    value: Literal["pass"] = Field(description="只能为 pass 的测试值。")


def provider_bad_request() -> BadRequestError:
    """构造与真实 OpenAI-compatible SDK 相同形态的无关键字 400。"""

    request = httpx.Request("POST", "https://provider.test/v1/chat/completions")
    response = httpx.Response(400, request=request)
    return BadRequestError(
        "provider rejected request",
        response=response,
        body={
            "code": "invalid_parameter_error",
            "message": "response format rejected by provider",
        },
    )


class BoundTransport:
    def __init__(self, model, method: str) -> None:
        self.model = model
        self.method = method

    async def ainvoke(self, _messages, config=None):
        self.model.calls.append(self.method)
        self.model.messages.append(_messages)
        outcome = self.model.outcomes[self.method]
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeModel:
    model_name = "transport-test"
    openai_api_base = "https://provider.test/v1"

    def __init__(self, outcomes) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []
        self.messages: list[list] = []

    def with_structured_output(self, _schema, *, method: str):
        return BoundTransport(self, method)

    def bind(self, **_kwargs):
        return BoundTransport(self, "json_mode")

    async def ainvoke(self, _messages, config=None):
        return await BoundTransport(self, "strict_json").ainvoke(_messages, config)


class ProviderStatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"provider status {status_code}")
        self.status_code = status_code


async def main() -> None:
    # 未缓存的结构化协议收到确定性 HTTP 400 时，不能原样重试同一个请求；
    # 真实 qwen3.7-max 会依次拒绝前三种协议，必须有界降级到 strict_json。
    structured_output._TRANSPORT_CACHE.clear()
    bad_request_model = FakeModel(
        {
            "json_schema": provider_bad_request(),
            "function_calling": provider_bad_request(),
            "json_mode": provider_bad_request(),
            "strict_json": AIMessage(content='{"value":"fallback-ok"}'),
        }
    )
    fallback = await structured_output.invoke_structured_model(
        model=bad_request_model,
        schema=Payload,
        messages=[],
    )
    assert fallback.value == "fallback-ok"
    assert bad_request_model.calls == [
        "json_schema",
        "function_calling",
        "json_mode",
        "strict_json",
    ]

    structured_output._TRANSPORT_CACHE.clear()
    model = FakeModel(
        {
            "json_schema": RuntimeError("unsupported response_format"),
            "function_calling": Payload(value="ok"),
            "json_mode": Payload(value="unused"),
            "strict_json": Payload(value="unused"),
        }
    )
    first = await structured_output.invoke_structured_model(
        model=model,
        schema=Payload,
        messages=[],
    )
    assert first.value == "ok"
    assert model.calls == ["json_schema", "function_calling"]

    model.calls.clear()
    second = await structured_output.invoke_structured_model(
        model=model,
        schema=Payload,
        messages=[],
    )
    assert second.value == "ok"
    assert model.calls == ["function_calling"]

    # 已确认支持的 transport 若发生技术失败，只在当前协议重试一次，不能
    # 轮流试探其余协议并把一次调用膨胀成八次。
    model.outcomes["function_calling"] = TimeoutError("temporary")
    model.calls.clear()
    try:
        await structured_output.invoke_structured_model(
            model=model,
            schema=Payload,
            messages=[],
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("当前 transport 技术失败两次后必须停止")
    assert model.calls == ["function_calling", "function_calling"]

    # Schema 校验失败后的第二次技术调用必须携带精简的纠错反馈；原样重发
    # 同一组消息会让真实模型稳定复现同一个自相矛盾输出。
    structured_output._TRANSPORT_CACHE.clear()
    correcting_model = FakeModel(
        {
            "json_schema": [{"value": "fail"}, {"value": "pass"}],
            "function_calling": Payload(value="unused"),
            "json_mode": Payload(value="unused"),
            "strict_json": Payload(value="unused"),
        }
    )
    corrected = await structured_output.invoke_structured_model(
        model=correcting_model,
        schema=StrictPayload,
        messages=[],
    )
    assert corrected.value == "pass"
    assert correcting_model.calls == ["json_schema", "json_schema"]
    assert len(correcting_model.messages[0]) == 0
    assert len(correcting_model.messages[1]) == 1
    assert "上一次结构化响应未通过 Schema 校验" in correcting_model.messages[1][0].content
    assert "value" in correcting_model.messages[1][0].content
    assert "fail" not in correcting_model.messages[1][0].content

    # ownership hook 在每次 Provider 调用前执行；hook 失败不能被 transport
    # fallback 或 retry 吞掉，也不能启动新的 Provider 请求。
    structured_output._TRANSPORT_CACHE.clear()
    hook_model = FakeModel(
        {
            "json_schema": Payload(value="never"),
            "function_calling": Payload(value="unused"),
            "json_mode": Payload(value="unused"),
            "strict_json": Payload(value="unused"),
        }
    )
    hook_calls = 0

    async def lost_lease() -> None:
        nonlocal hook_calls
        hook_calls += 1
        raise RuntimeError("lease lost")

    try:
        await structured_output.invoke_structured_model(
            model=hook_model,
            schema=Payload,
            messages=[],
            before_provider_call=lost_lease,
        )
    except RuntimeError as exc:
        assert str(exc) == "lease lost"
    else:
        raise AssertionError("ownership hook 失败必须直接传播")
    assert hook_calls == 1
    assert hook_model.calls == []

    # 429/5xx 只在当前 transport 内有限重试；全局调用预算是最终保险丝。
    structured_output._TRANSPORT_CACHE.clear()
    retry_model = FakeModel(
        {
            "json_schema": [ProviderStatusError(429), Payload(value="retry-ok")],
            "function_calling": Payload(value="unused"),
            "json_mode": Payload(value="unused"),
            "strict_json": Payload(value="unused"),
        }
    )
    retry_value = await structured_output.invoke_structured_model(
        model=retry_model,
        schema=Payload,
        messages=[],
        max_provider_calls=2,
        retry_base_delay_seconds=0,
    )
    assert retry_value.value == "retry-ok"
    assert retry_model.calls == ["json_schema", "json_schema"]

    structured_output._TRANSPORT_CACHE.clear()
    client_error_model = FakeModel(
        {
            "json_schema": ProviderStatusError(422),
            "function_calling": Payload(value="must-not-run"),
            "json_mode": Payload(value="unused"),
            "strict_json": Payload(value="unused"),
        }
    )
    try:
        await structured_output.invoke_structured_model(
            model=client_error_model,
            schema=Payload,
            messages=[],
        )
    except ProviderStatusError as exc:
        assert exc.status_code == 422
    else:
        raise AssertionError("非 transport 4xx 必须直接失败")
    assert client_error_model.calls == ["json_schema"]

    print("structured_output_transport=passed")


if __name__ == "__main__":
    asyncio.run(main())
