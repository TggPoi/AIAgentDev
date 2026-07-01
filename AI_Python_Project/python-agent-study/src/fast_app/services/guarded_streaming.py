from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass, field

from fast_app.domain.prompt_guard_models import PromptGuardAction, PromptGuardResult
from fast_app.domain.rag_stream_models import RagStreamEvent
from fast_app.services.prompt_guard_service import PromptGuardService


SENTENCE_ENDINGS = {"。", "！", "？", ".", "!", "?", "\n"}


@dataclass
class GuardedStreamState:
    """记录一次安全流式输出的累计状态。"""

    raw_token_count: int = 0
    emitted_parts: list[str] = field(default_factory=list)
    blocked: bool = False

    @property
    def answer(self) -> str:
        """返回已经允许发送给用户的安全回答文本。"""

        return "".join(self.emitted_parts)


async def text_to_async_tokens(text: str) -> AsyncGenerator[str, None]:
    """把完整文本转成异步字符流，复用同一套缓冲安全检查逻辑。"""

    for char in text:
        yield char


async def guarded_answer_delta_events(
    token_stream: AsyncIterable[str],
    *,
    prompt_guard: PromptGuardService | None,
    source: str,
    mode: str,
    max_chars: int,
    state: GuardedStreamState,
) -> AsyncGenerator[RagStreamEvent, None]:
    """把原始 token 流转换为经过输出安全检查的结构化事件。

    这个函数是当前主流式接口 `/rag/chat/stream/events` 的输出安全边界。
    上游传进来的是 LLM 产生的原始 token；下游拿到的是可以发给前端的
    answer_delta / guard_sanitized / guard_blocked 事件。

    state 只累计“已经允许展示给用户”的安全文本，后续持久化也应该使用
    state.answer，而不是原始 token 拼出的未审计内容。
    """

    normalized_mode = mode.strip().lower()
    if normalized_mode == "buffer_then_emit":
        # 最强安全模式：先把完整回答全部缓冲下来，再做一次输出安全检查。
        # 优点是用户不会看到任何未检查内容；缺点是首包延迟最高，流式体验最弱。
        raw_parts: list[str] = []
        async for token in token_stream:
            state.raw_token_count += 1
            raw_parts.append(token)

        # 这里仍然复用 _emit_guarded_chunk，保证 allow / sanitize / block
        # 三种处理结果和默认 sentence_buffer 模式保持一致。
        async for event in _emit_guarded_chunk(
            "".join(raw_parts),
            prompt_guard=prompt_guard,
            source=source,
            state=state,
        ):
            yield event
        return

    if normalized_mode == "pre_guard_only":
        # 兼容旧流式体验的模式：原始 token 先发给用户，结束后只做审计。
        # 这个模式不能阻止已发出的危险内容，只适合兼容或观察，不适合作为严格安全主线。
        raw_parts: list[str] = []
        async for token in token_stream:
            state.raw_token_count += 1
            raw_parts.append(token)
            state.emitted_parts.append(token)
            yield _build_answer_delta_event(token)

        if prompt_guard is not None:
            # 生成结束后审计完整输出，用于日志 / trace 观察；这里不会改变已经发出的内容。
            await prompt_guard.audit_stream_output("".join(raw_parts), source=source)
        return

    # 默认主线：sentence_buffer。
    # 原始 token 先进入服务端 buffer，只有当 buffer 到达句子边界或最大长度时，
    # 才把一个语义片段交给 Prompt Guard 检查。检查通过后再发给前端。
    buffer: list[str] = []
    async for token in token_stream:
        state.raw_token_count += 1
        buffer.append(token)
        if _should_flush_buffer(buffer, max_chars=max_chars):
            should_continue = True
            # _emit_guarded_chunk 会根据 Prompt Guard 结果产出：
            # - answer_delta：片段安全，可以正常展示
            # - guard_sanitized：片段已脱敏，可以展示脱敏内容
            # - guard_blocked：片段高风险，应停止后续输出
            async for event in _emit_guarded_chunk(
                "".join(buffer),
                prompt_guard=prompt_guard,
                source=source,
                state=state,
            ):
                if event.event == "guard_blocked":
                    should_continue = False
                yield event

            # 当前 buffer 已经被检查并转换成事件，必须清空后继续收集下一个片段。
            buffer.clear()
            if not should_continue:
                # 一旦出现 guard_blocked，后续 raw token 不再继续读取和发送。
                # 这样可以避免高风险输出继续扩散到客户端。
                return

    if buffer:
        # LLM 流结束时，可能还剩一段没有遇到句号或最大长度阈值的尾部文本。
        # 这段尾部文本也必须先经过 Output Guard，不能直接发给用户。
        async for event in _emit_guarded_chunk(
            "".join(buffer),
            prompt_guard=prompt_guard,
            source=source,
            state=state,
        ):
            yield event


def _should_flush_buffer(buffer: list[str], *, max_chars: int) -> bool:
    """判断当前缓冲区是否到达句子边界或最大长度。"""

    if not buffer:
        return False

    return len(buffer) >= max_chars or buffer[-1] in SENTENCE_ENDINGS


async def _emit_guarded_chunk(
    chunk: str,
    *,
    prompt_guard: PromptGuardService | None,
    source: str,
    state: GuardedStreamState,
) -> AsyncGenerator[RagStreamEvent, None]:
    """检查一个输出片段，并转换为前端可消费的安全事件。"""

    if not chunk:
        return

    if prompt_guard is None:
        state.emitted_parts.append(chunk)
        yield _build_answer_delta_event(chunk)
        return

    # 检查当前准备输出的片段
    result, safe_text = await prompt_guard.guard_output_chunk(chunk, source=source)

    # 检查结果分类处理
    if result.action == PromptGuardAction.BLOCK:
        state.blocked = True
        state.emitted_parts.append(safe_text)
        yield _build_guard_event(
            event="guard_blocked",
            result=result,
            text=safe_text,
        )
        return

    if result.action == PromptGuardAction.SANITIZE:
        state.emitted_parts.append(safe_text)
        yield _build_guard_event(
            event="guard_sanitized",
            result=result,
            text=safe_text,
        )
        return

    state.emitted_parts.append(safe_text)
    yield _build_answer_delta_event(safe_text)


def _build_answer_delta_event(text: str) -> RagStreamEvent:
    """构造安全回答增量事件。"""

    return RagStreamEvent(
        event="answer_delta",
        data={
            "text": text,
        },
    )


def _build_guard_event(
    *,
    event: str,
    result: PromptGuardResult,
    text: str,
) -> RagStreamEvent:
    """构造 Prompt Guard 流式安全事件。"""

    return RagStreamEvent(
        event=event,  # type: ignore[arg-type]
        data={
            "text": text,
            "answer": text,
            "action": result.action.value,
            "risk_level": result.risk_level.value,
            "categories": [category.value for category in result.categories],
            "reason": result.reason,
        },
    )
