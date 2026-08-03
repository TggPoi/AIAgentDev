"""Planner、Reviewer、Rewriter 共用 structured-output transport 回归。"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

import fast_app.core.structured_output as structured_output


class Payload(BaseModel):
    value: str = Field(description="测试结构化值。")


class BoundTransport:
    def __init__(self, model, method: str) -> None:
        self.model = model
        self.method = method

    async def ainvoke(self, _messages, config=None):
        self.model.calls.append(self.method)
        outcome = self.model.outcomes[self.method]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeModel:
    model_name = "transport-test"
    openai_api_base = "https://provider.test/v1"

    def __init__(self, outcomes) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def with_structured_output(self, _schema, *, method: str):
        return BoundTransport(self, method)

    def bind(self, **_kwargs):
        return BoundTransport(self, "json_mode")

    async def ainvoke(self, _messages, config=None):
        return await BoundTransport(self, "strict_json").ainvoke(_messages, config)


async def main() -> None:
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

    print("structured_output_transport=passed")


if __name__ == "__main__":
    asyncio.run(main())
