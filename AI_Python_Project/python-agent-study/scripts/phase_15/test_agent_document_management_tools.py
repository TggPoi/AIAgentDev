import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from fast_app.agents.document_management_tools import (
    KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
    KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
    build_knowledge_document_management_tools,
)
from fast_app.core.config import get_settings
from fast_app.domain.knowledge_document_actions import KnowledgeDocumentOperation
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import AppServiceError
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)


TOOL_NAMES_BY_OPERATION = {
    KnowledgeDocumentOperation.CREATE: KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
    KnowledgeDocumentOperation.UPDATE: KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
    KnowledgeDocumentOperation.DELETE: KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="阶段 15-6.5 Agent 文档管理工具 dry-run 验收脚本"
    )
    parser.add_argument(
        "--operation",
        choices=[item.value for item in KnowledgeDocumentOperation],
        required=True,
        help="要测试的文档管理动作",
    )
    parser.add_argument(
        "--target-path",
        required=True,
        help="知识库根目录内的目标路径，例如 development/agent-generated-note.md",
    )
    parser.add_argument(
        "--content",
        default=None,
        help="create / update 使用的文档内容",
    )
    parser.add_argument(
        "--content-file",
        default=None,
        help="从本地文件读取 create / update 内容",
    )
    parser.add_argument(
        "--reason",
        default="阶段 15-6.5 文档管理工具 dry-run 验收",
        help="文档管理动作原因",
    )
    parser.add_argument(
        "--knowledge-base-dir",
        default=None,
        help="覆盖 KNOWLEDGE_BASE_DIR，仅用于本脚本验收",
    )
    parser.add_argument(
        "--department",
        action="append",
        default=[],
        help="当前测试用户所属部门，可重复传入",
    )
    parser.add_argument(
        "--expected-department",
        action="append",
        default=[],
        help="Agent 预期目标文档部门，可重复传入",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否 dry-run，默认 true",
    )
    parser.add_argument(
        "--expect-error",
        action="store_true",
        help="预期本次调用失败，例如路径攻击测试",
    )
    parser.add_argument(
        "--respect-env-enabled",
        action="store_true",
        help="严格使用 .env 中的 AGENT_DOCUMENT_TOOLS_ENABLED；默认脚本会临时开启工具",
    )
    return parser


def load_content(args: argparse.Namespace) -> str | None:
    if args.content_file:
        return Path(args.content_file).read_text(encoding="utf-8")
    return args.content


def build_tool_payload(
    operation: KnowledgeDocumentOperation,
    args: argparse.Namespace,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_path": args.target_path,
        "reason": args.reason,
        "dry_run": args.dry_run,
        "expected_department_codes": args.expected_department,
    }

    if operation in {
        KnowledgeDocumentOperation.CREATE,
        KnowledgeDocumentOperation.UPDATE,
    }:
        payload["content"] = load_content(args) or "# Agent 生成文档\n\n用于 dry-run 验收。"

    return payload


def build_service(args: argparse.Namespace) -> KnowledgeDocumentManagementService:
    settings = get_settings()
    updates: dict[str, Any] = {}
    if args.knowledge_base_dir:
        updates["knowledge_base_dir"] = args.knowledge_base_dir
    if not args.respect_env_enabled:
        updates["agent_document_tools_enabled"] = True
    settings = settings.model_copy(update=updates) if updates else settings
    return KnowledgeDocumentManagementService(settings=settings)


async def run(args: argparse.Namespace) -> None:
    operation = KnowledgeDocumentOperation(args.operation)
    user = CurrentUserContext(
        user_id="phase_15_document_tool_user",
        is_authenticated=True,
        auth_source="jwt",
        role="user",
        permissions=["rag:chat"],
        department_codes=args.department,
        primary_department_code=args.department[0] if args.department else None,
    )
    service = build_service(args)
    tools = {
        tool.name: tool
        for tool in build_knowledge_document_management_tools(
            service=service,
            user=user,
        )
    }
    tool_name = TOOL_NAMES_BY_OPERATION[operation]
    payload = build_tool_payload(operation, args)

    try:
        raw_result = await tools[tool_name].ainvoke(payload)
    except AppServiceError as exc:
        if args.expect_error:
            print(
                "agent_document_tool_expected_error=passed "
                f"operation={operation.value} error_code={exc.error_code} "
                f"message={exc.public_message}"
            )
            return
        raise

    if args.expect_error:
        raise AssertionError("本次调用预期失败，但工具返回了成功结果")

    result = json.loads(raw_result)
    preview = result["preview"]
    if result["executed"]:
        raise AssertionError("15-6.5 验收要求工具不能执行真实写入")
    if not result["dry_run"]:
        raise AssertionError("本脚本默认验收 dry-run 结果")
    if not preview["requires_confirmation"]:
        raise AssertionError("文档管理工具结果必须要求人工确认")

    print(
        "agent_document_tool_dry_run=passed "
        f"operation={result['operation']} "
        f"target={preview['normalized_path']} "
        f"risk_level={preview['risk_level']} "
        f"doc_id={preview['affected_doc_id']} "
        f"chunk_count={preview['affected_chunk_count']}"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    args = build_parser().parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
