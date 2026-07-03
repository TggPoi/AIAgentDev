import json

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentOperation,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)


KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME = "knowledge_document_create"
KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME = "knowledge_document_update"
KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME = "knowledge_document_delete"


class KnowledgeDocumentCreateToolInput(BaseModel):
    """新增知识库文档工具输入。"""

    model_config = ConfigDict(extra="forbid")

    target_path: str = Field(description="知识库根目录下的目标相对路径")
    content: str = Field(description="新文档内容")
    reason: str = Field(description="为什么需要新增这篇文档")
    dry_run: bool = Field(default=True, description="默认只生成预览，不执行写入")
    expected_department_codes: list[str] = Field(
        default_factory=list,
        description="Agent 预期文档归属部门；最终以服务端权限规则为准",
    )


class KnowledgeDocumentUpdateToolInput(BaseModel):
    """修改知识库文档工具输入。"""

    model_config = ConfigDict(extra="forbid")

    target_path: str = Field(description="知识库根目录下的目标相对路径")
    content: str = Field(description="修改后的完整文档内容")
    reason: str = Field(description="为什么需要修改这篇文档")
    dry_run: bool = Field(default=True, description="默认只生成预览，不执行写入")
    expected_department_codes: list[str] = Field(default_factory=list)


class KnowledgeDocumentDeleteToolInput(BaseModel):
    """删除知识库文档工具输入。"""

    model_config = ConfigDict(extra="forbid")

    target_path: str = Field(description="知识库根目录下的目标相对路径")
    reason: str = Field(description="为什么需要删除这篇文档")
    dry_run: bool = Field(default=True, description="默认只生成预览，不执行删除")
    expected_department_codes: list[str] = Field(default_factory=list)


def _dump_tool_result(result: object) -> str:
    """把 Pydantic 结果转成 Agent 可读的 JSON 字符串。"""

    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def build_knowledge_document_create_tool(
    service: KnowledgeDocumentManagementService,
    user: CurrentUserContext,
) -> BaseTool:
    async def create_document(
        target_path: str,
        content: str,
        reason: str,
        dry_run: bool = True,
        expected_department_codes: list[str] | None = None,
    ) -> str:
        result = await service.plan_action(
            KnowledgeDocumentActionRequest(
                operation=KnowledgeDocumentOperation.CREATE,
                target_path=target_path,
                content=content,
                reason=reason,
                dry_run=dry_run,
                expected_department_codes=expected_department_codes or [],
            ),
            user=user,
        )
        return _dump_tool_result(result)

    return StructuredTool.from_function(
        coroutine=create_document,
        name=KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
        description=(
            "提出新增知识库文档的受控请求。默认只返回 dry-run 预览，"
            "不会直接写文件、Elasticsearch 或 Milvus。"
        ),
        args_schema=KnowledgeDocumentCreateToolInput,
    )


def build_knowledge_document_update_tool(
    service: KnowledgeDocumentManagementService,
    user: CurrentUserContext,
) -> BaseTool:
    async def update_document(
        target_path: str,
        content: str,
        reason: str,
        dry_run: bool = True,
        expected_department_codes: list[str] | None = None,
    ) -> str:
        result = await service.plan_action(
            KnowledgeDocumentActionRequest(
                operation=KnowledgeDocumentOperation.UPDATE,
                target_path=target_path,
                content=content,
                reason=reason,
                dry_run=dry_run,
                expected_department_codes=expected_department_codes or [],
            ),
            user=user,
        )
        return _dump_tool_result(result)

    return StructuredTool.from_function(
        coroutine=update_document,
        name=KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
        description=(
            "提出修改知识库文档的受控请求。默认只返回 dry-run 预览，"
            "真实修改需要后续工具权限网关和人工确认。"
        ),
        args_schema=KnowledgeDocumentUpdateToolInput,
    )


def build_knowledge_document_delete_tool(
    service: KnowledgeDocumentManagementService,
    user: CurrentUserContext,
) -> BaseTool:
    async def delete_document(
        target_path: str,
        reason: str,
        dry_run: bool = True,
        expected_department_codes: list[str] | None = None,
    ) -> str:
        result = await service.plan_action(
            KnowledgeDocumentActionRequest(
                operation=KnowledgeDocumentOperation.DELETE,
                target_path=target_path,
                reason=reason,
                dry_run=dry_run,
                expected_department_codes=expected_department_codes or [],
            ),
            user=user,
        )
        return _dump_tool_result(result)

    return StructuredTool.from_function(
        coroutine=delete_document,
        name=KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
        description=(
            "提出删除知识库文档的受控请求。当前默认只返回 dry-run 预览，"
            "不执行真实删除。"
        ),
        args_schema=KnowledgeDocumentDeleteToolInput,
    )


def build_knowledge_document_management_tools(
    service: KnowledgeDocumentManagementService,
    user: CurrentUserContext,
) -> list[BaseTool]:
    """构造三个独立工具，方便 15-7 按工具名配置不同权限。"""

    return [
        build_knowledge_document_create_tool(service=service, user=user),
        build_knowledge_document_update_tool(service=service, user=user),
        build_knowledge_document_delete_tool(service=service, user=user),
    ]


__all__ = [
    "KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME",
    "KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME",
    "KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME",
    "KnowledgeDocumentCreateToolInput",
    "KnowledgeDocumentDeleteToolInput",
    "KnowledgeDocumentUpdateToolInput",
    "build_knowledge_document_create_tool",
    "build_knowledge_document_delete_tool",
    "build_knowledge_document_management_tools",
    "build_knowledge_document_update_tool",
]
