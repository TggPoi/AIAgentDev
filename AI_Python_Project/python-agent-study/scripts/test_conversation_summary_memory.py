import argparse
import asyncio
import sys
from uuid import uuid4

from fast_app.core.config import get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.conversation_models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    utc_now,
)
from fast_app.services.conversation_history import (
    ConversationHistoryWindow,
    format_history_messages,
)
from fast_app.services.conversation_repository import PostgresConversationRepository
from fast_app.services.conversation_summary import ConversationSummaryService
from fast_app.services.query_rewrite import ConversationQueryRewriter


def print_field(name: str, value: object) -> None:
    text = str(value)
    print(f"{name}={text.encode('unicode_escape').decode('ascii')}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def build_seed_messages(conversation_id: str) -> list[ConversationMessage]:
    contents = [
        (
            ConversationRole.USER,
            "我的长期目标是评估混合检索在中文知识库中的效果。",
        ),
        (
            ConversationRole.ASSISTANT,
            "好的，后续会围绕中文知识库、混合检索和评测效果展开。",
        ),
        (
            ConversationRole.USER,
            "约束是不要只看回答，要同时看 sources 是否命中。",
        ),
        (
            ConversationRole.ASSISTANT,
            "我会把 sources 命中作为关键约束记录下来。",
        ),
        (
            ConversationRole.USER,
            "我们已经完成 Redis 最近窗口和 PostgreSQL 消息持久化。",
        ),
        (
            ConversationRole.ASSISTANT,
            "当前系统已经有短期窗口和完整事件日志。",
        ),
        (
            ConversationRole.USER,
            "接下来讨论一个普通的接口测试问题。",
        ),
        (
            ConversationRole.ASSISTANT,
            "可以，接口测试可以用脚本或 curl 验证。",
        ),
        (
            ConversationRole.USER,
            "再讨论一下 README 如何写启动步骤。",
        ),
        (
            ConversationRole.ASSISTANT,
            "README 应该包含环境变量、启动命令和验收方式。",
        ),
    ]
    created_at = utc_now()
    return [
        ConversationMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=created_at,
        )
        for role, content in contents
    ]


async def seed_conversation(
    repository: PostgresConversationRepository,
    conversation_id: str,
) -> list[ConversationMessage]:
    conversation = Conversation(
        id=conversation_id,
        updated_at=utc_now(),
        metadata={"test_case": "conversation_summary_memory"},
    )
    messages = build_seed_messages(conversation_id)
    await repository.save_conversation_turn(
        conversation=conversation,
        messages=messages,
    )
    return messages


def build_recent_window(
    conversation_id: str,
    messages: list[ConversationMessage],
    max_turns: int,
) -> ConversationHistoryWindow:
    max_messages = max(max_turns, 0) * 2
    recent_messages = messages[-max_messages:] if max_messages > 0 else []
    return ConversationHistoryWindow(
        conversation_id=conversation_id,
        messages=recent_messages,
        formatted_text=format_history_messages(recent_messages),
    )


async def main_async() -> None:
    parser = argparse.ArgumentParser(
        description="Verify phase 14-6 conversation summary memory.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Conversation id. Defaults to a generated verify id.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=120.0,
        help="Timeout for summary generation and rewrite.",
    )
    args = parser.parse_args()

    settings = get_settings()
    require(
        settings.summary_memory_enabled,
        "Set SUMMARY_MEMORY_ENABLED=true before running this script.",
    )

    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    conversation_id = args.session_id or f"verify-summary-14-6-{uuid4().hex[:8]}"

    try:
        async with session_factory() as session:
            repository = PostgresConversationRepository(session=session)
            messages = await seed_conversation(
                repository=repository,
                conversation_id=conversation_id,
            )
            stored_messages = await repository.list_messages(
                conversation_id=conversation_id,
                limit=len(messages),
            )
            require(
                [message.id for message in stored_messages]
                == [message.id for message in messages],
                "conversation messages must preserve database insertion order",
            )
            recent_window = build_recent_window(
                conversation_id=conversation_id,
                messages=messages,
                max_turns=settings.memory_history_max_turns,
            )
            summary_service = ConversationSummaryService.from_settings(
                settings=settings,
                repository=repository,
            )
            summary = await asyncio.wait_for(
                summary_service.maybe_update_summary(
                    conversation_id=conversation_id,
                    recent_window=recent_window,
                ),
                timeout=args.timeout_seconds,
            )

            require(summary is not None, "expected summary to be generated")
            require(summary.source_message_ids, "expected source_message_ids")
            require(summary.version >= 1, "expected summary version >= 1")
            require(
                summary.covered_until_message_id is not None,
                "expected covered_until_message_id",
            )

            memory_context = summary_service.build_memory_context(
                conversation_id=conversation_id,
                recent_window=recent_window,
                summary=summary,
            )
            rewriter = ConversationQueryRewriter.from_settings(settings)
            rewrite_result = await asyncio.wait_for(
                rewriter.rewrite(
                    query="这个目标最大的风险是什么？",
                    memory_context=memory_context,
                ),
                timeout=args.timeout_seconds,
            )

            print_field("conversation_id", conversation_id)
            print(f"summary_version={summary.version}")
            print(f"summary_source_message_count={summary.source_message_count}")
            print_field("summary_covered_until", summary.covered_until_message_id)
            print_field("summary_text", summary.summary_text)
            print(f"rewrite_used_summary={rewrite_result.used_summary}")
            print_field("rewrite_reason", rewrite_result.reason)
            print_field("rewrite_query", rewrite_result.rewritten_query)

            require(
                rewrite_result.used_summary,
                "expected query rewrite to receive summary context",
            )
    finally:
        await engine.dispose()


def main() -> int:
    try:
        asyncio.run(main_async())
        return 0
    except AssertionError as exc:
        print(f"assertion_failed={exc}", file=sys.stderr)
        return 1
    except TimeoutError as exc:
        print(f"timeout={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
