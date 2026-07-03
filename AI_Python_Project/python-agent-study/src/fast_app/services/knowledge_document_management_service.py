import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.core.config import Settings
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionPreview,
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentActionResult,
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.knowledge_models import DocumentType, LoadedDocument
from fast_app.domain.user_context import CurrentUserContext
from fast_app.ingestion.chunk_builders import ChunkBuildOptions, MarkdownChunkBuilder
from fast_app.ingestion.metadata_models import (
    PERMISSION_RULES_FILE_NAME,
    build_document_metadata,
)
from fast_app.services.exceptions import (
    AppServiceError,
    ToolExecutionRequiresApprovalError,
)


@dataclass(frozen=True)
class SafeDocumentTarget:
    """通过路径安全校验后的目标文档。"""

    requested_path: str
    relative_path: str
    source_path: str
    absolute_path: Path
    document_type: DocumentType


class KnowledgeDocumentManagementService:
    """知识库文档管理服务。

    Agent 只能把 create / update / delete 意图提交到这里。服务层负责路径安全、
    文件类型、权限 metadata 预估和 dry-run 预览；真实写入必须等 15-7 的工具
    权限网关和人工确认接入后再放开。
    """

    def __init__(
        self,
        settings: Settings,
        embedding_client: BaseEmbeddingClient | None = None,
        elasticsearch_client: Any | None = None,
        milvus_client: Any | None = None,
        chunk_builder: MarkdownChunkBuilder | None = None,
    ):
        self.settings = settings
        self.embedding_client = embedding_client
        self.elasticsearch_client = elasticsearch_client
        self.milvus_client = milvus_client
        self.chunk_builder = chunk_builder or MarkdownChunkBuilder()

    async def plan_action(
        self,
        request: KnowledgeDocumentActionRequest,
        user: CurrentUserContext,
    ) -> KnowledgeDocumentActionResult:
        """生成文档管理动作的 dry-run 预览，或拒绝真实执行。"""

        if not self.settings.agent_document_tools_enabled:
            raise AppServiceError("Agent 文档管理工具未启用")

        target = self._resolve_safe_target_path(request.target_path)
        self._validate_operation_requirements(request=request, target=target)

        preview = self._build_preview(
            request=request,
            target=target,
            user=user,
        )

        if request.dry_run:
            return KnowledgeDocumentActionResult(
                operation=request.operation,
                target_path=request.target_path,
                dry_run=True,
                executed=False,
                preview=preview,
                message="已生成文档管理 dry-run 预览，尚未执行真实写入。",
            )

        if self.settings.agent_document_tools_dry_run_only:
            raise ToolExecutionRequiresApprovalError(
                "当前配置只允许 dry-run，文档写操作需要经过 15-7 工具权限和人工确认。"
            )

        if self.settings.agent_document_tools_require_confirmation:
            raise ToolExecutionRequiresApprovalError(
                "文档写操作需要经过 15-7 工具权限和人工确认后才能执行。"
            )

        raise ToolExecutionRequiresApprovalError(
            "文档真实执行路径尚未接入 15-7 工具权限网关。"
        )

    def _resolve_safe_target_path(self, target_path: str) -> SafeDocumentTarget:
        """把用户传入路径转换成知识库内的安全目标路径。"""

        requested_path = target_path.strip().replace("\\", "/")
        if not requested_path:
            raise AppServiceError("target_path 不能为空")

        raw_parts = [part for part in requested_path.split("/") if part]
        if any(part == ".." for part in raw_parts):
            raise AppServiceError("target_path 不能包含 .. 路径穿越片段")

        knowledge_base_root = Path(self.settings.knowledge_base_dir)
        resolved_root = knowledge_base_root.resolve(strict=False)
        candidate = Path(requested_path)
        if not candidate.is_absolute():
            root_name = knowledge_base_root.name
            if raw_parts and raw_parts[0] == root_name:
                candidate = knowledge_base_root.parent.joinpath(*raw_parts)
            else:
                candidate = knowledge_base_root.joinpath(*raw_parts)

        resolved_candidate = candidate.resolve(strict=False)
        try:
            relative = resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise AppServiceError(
                "target_path 不在 KNOWLEDGE_BASE_DIR 配置的知识库根目录内"
            ) from exc

        if not relative.parts:
            raise AppServiceError("target_path 必须指向知识库内的具体文档")

        relative_path = relative.as_posix()
        suffix = resolved_candidate.suffix.lower()
        allowed_extensions = self.settings.agent_document_tools_allowed_extension_list
        if suffix not in allowed_extensions:
            raise AppServiceError(
                "不支持的文档类型: "
                f"{suffix or '<empty>'}; 允许类型: {', '.join(allowed_extensions)}"
            )

        if not self.settings.agent_document_tools_allow_permission_file_edit:
            self._reject_permission_control_file(relative_path)

        return SafeDocumentTarget(
            requested_path=target_path,
            relative_path=relative_path,
            source_path=knowledge_base_root.joinpath(relative).as_posix(),
            absolute_path=resolved_candidate,
            document_type=self._document_type_from_suffix(suffix),
        )

    def _reject_permission_control_file(self, relative_path: str) -> None:
        path = Path(relative_path)
        if path.name == PERMISSION_RULES_FILE_NAME or relative_path.endswith(".meta.json"):
            raise AppServiceError(
                "默认不允许 Agent 修改权限规则文件或 sidecar metadata 文件"
            )

    def _document_type_from_suffix(self, suffix: str) -> DocumentType:
        if suffix == ".md":
            return "markdown"
        if suffix == ".txt":
            return "text"
        raise AppServiceError(f"不支持的文档类型: {suffix}")

    def _validate_operation_requirements(
        self,
        request: KnowledgeDocumentActionRequest,
        target: SafeDocumentTarget,
    ) -> None:
        exists_before = target.absolute_path.exists()
        content = request.content or ""

        if request.operation == KnowledgeDocumentOperation.CREATE:
            if exists_before:
                raise AppServiceError("create_document 要求目标文档不存在")
            if not content.strip():
                raise AppServiceError("create_document 要求 content 非空")

        if request.operation == KnowledgeDocumentOperation.UPDATE:
            if not exists_before:
                raise AppServiceError("update_document 要求目标文档已存在")
            if not content.strip():
                raise AppServiceError("update_document 要求 content 非空")

        if request.operation == KnowledgeDocumentOperation.DELETE:
            if not exists_before:
                raise AppServiceError("delete_document 要求目标文档已存在")
            if content.strip():
                raise AppServiceError("delete_document 不允许传入 content")

        if len(content) > self.settings.agent_document_tools_max_content_chars:
            raise AppServiceError(
                "content 超过 AGENT_DOCUMENT_TOOLS_MAX_CONTENT_CHARS 限制"
            )

    def _build_preview(
        self,
        request: KnowledgeDocumentActionRequest,
        target: SafeDocumentTarget,
        user: CurrentUserContext,
    ) -> KnowledgeDocumentActionPreview:
        exists_before = target.absolute_path.exists()
        before_content = self._read_text_if_exists(target.absolute_path)
        preview_content = self._preview_content(
            request=request,
            before_content=before_content,
        )
        metadata = build_document_metadata(
            source_path=target.source_path,
            document_type=target.document_type,
            knowledge_base_dir=self.settings.knowledge_base_dir,
        )
        chunks = self._build_preview_chunks(
            target=target,
            content=preview_content,
            metadata=metadata,
        )
        warnings = self._build_warnings(
            request=request,
            metadata=metadata,
            user=user,
        )

        return KnowledgeDocumentActionPreview(
            operation=request.operation,
            target_path=request.target_path,
            normalized_path=target.relative_path,
            exists_before=exists_before,
            risk_level=self._risk_level_for_operation(request.operation),
            affected_doc_id=str(metadata.get("doc_id")),
            affected_chunk_count=len(chunks),
            before_hash=self._sha256_text(before_content) if before_content else None,
            after_hash=self._sha256_text(preview_content) if preview_content else None,
            permission_metadata={
                "visibility": metadata.get("visibility"),
                "allowed_departments": metadata.get("allowed_departments", []),
                "allowed_users": metadata.get("allowed_users", []),
                "permission_source": metadata.get("permission_source"),
            },
            warnings=warnings,
            requires_confirmation=self._requires_confirmation(request.operation),
        )

    def _preview_content(
        self,
        request: KnowledgeDocumentActionRequest,
        before_content: str | None,
    ) -> str:
        if request.operation in {
            KnowledgeDocumentOperation.CREATE,
            KnowledgeDocumentOperation.UPDATE,
        }:
            return request.content or ""
        return before_content or ""

    def _build_preview_chunks(
        self,
        target: SafeDocumentTarget,
        content: str,
        metadata: dict[str, Any],
    ) -> list[object]:
        if not content.strip():
            return []

        document = LoadedDocument(
            source_path=target.source_path,
            content=content,
            document_type=target.document_type,
            metadata=metadata,
        )
        return self.chunk_builder.build(
            documents=[document],
            options=ChunkBuildOptions(
                source=self.settings.ingestion_source_name,
                max_chars=self.settings.markdown_chunk_max_chars,
                overlap_chars=self.settings.markdown_chunk_overlap_chars,
                max_tokens=self.settings.markdown_chunk_max_tokens,
                min_chars=self.settings.markdown_chunk_min_chars,
            ),
        )

    def _build_warnings(
        self,
        request: KnowledgeDocumentActionRequest,
        metadata: dict[str, Any],
        user: CurrentUserContext,
    ) -> list[str]:
        warnings: list[str] = []
        metadata_departments = set(metadata.get("allowed_departments") or [])
        expected_departments = set(request.expected_department_codes)
        user_departments = set(user.department_codes)

        if expected_departments and expected_departments != metadata_departments:
            warnings.append(
                "expected_department_codes 与服务端权限规则推断出的部门不一致"
            )

        if metadata_departments and user_departments:
            missing = metadata_departments - user_departments
            if missing:
                warnings.append(
                    "当前用户不属于目标文档推断部门: "
                    + ",".join(sorted(missing))
                )

        if request.operation == KnowledgeDocumentOperation.DELETE:
            warnings.append("delete 当前只允许 dry-run，后续需要人工确认后执行 soft delete")

        return warnings

    def _risk_level_for_operation(
        self,
        operation: KnowledgeDocumentOperation,
    ) -> KnowledgeDocumentRiskLevel:
        if operation == KnowledgeDocumentOperation.CREATE:
            return KnowledgeDocumentRiskLevel.MEDIUM
        if operation == KnowledgeDocumentOperation.UPDATE:
            return KnowledgeDocumentRiskLevel.HIGH
        return KnowledgeDocumentRiskLevel.CRITICAL

    def _requires_confirmation(self, operation: KnowledgeDocumentOperation) -> bool:
        if self.settings.agent_document_tools_require_confirmation:
            return True
        return operation in {
            KnowledgeDocumentOperation.UPDATE,
            KnowledgeDocumentOperation.DELETE,
        }

    def _read_text_if_exists(self, path: Path) -> str | None:
        if not path.exists():
            return None
        if not path.is_file():
            raise AppServiceError("target_path 必须指向普通文件")
        return path.read_text(encoding="utf-8")

    def _sha256_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["KnowledgeDocumentManagementService", "SafeDocumentTarget"]
