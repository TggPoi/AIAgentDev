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
    ToolExecutionRequiresConfirmationError,
)


@dataclass(frozen=True)
class SafeDocumentTarget:
    """通过路径安全校验后的目标文档。"""

    # 用户原始提交的目标路径，用于回显和错误排查。
    requested_path: str
    # 目标文档相对知识库根目录的路径，是后续权限和预览展示的稳定路径。
    relative_path: str
    # 用于写入 metadata / chunk 的 source_path，保持 ingestion 链路中的来源语义一致。
    source_path: str
    # 经过 resolve 和根目录校验后的真实文件系统路径。
    absolute_path: Path
    # 根据文件后缀推断出的文档类型，决定后续 chunk builder 如何处理。
    document_type: DocumentType


class KnowledgeDocumentManagementService:
    """知识库文档管理服务。

    Agent 只能把 create / update / delete 意图提交到这里。服务层负责路径安全、
    文件类型、权限 metadata 预估和 dry-run 预览；真实写入必须由 TaskPlan
    确认入口重新校验权限后再放开。
    """

    def __init__(
        self,
        settings: Settings,
        embedding_client: BaseEmbeddingClient | None = None,
        elasticsearch_client: Any | None = None,
        milvus_client: Any | None = None,
        chunk_builder: MarkdownChunkBuilder | None = None,
    ):
        # settings 控制工具是否启用、是否只允许 dry-run、允许编辑的后缀和内容大小等安全边界。
        self.settings = settings
        # 下面三个 client 预留给后续直接触发索引更新；当前阶段不在本服务里直接写 ES / Milvus。
        self.embedding_client = embedding_client
        self.elasticsearch_client = elasticsearch_client
        self.milvus_client = milvus_client
        # 当前预览需要估算 affected_chunk_count，因此复用 ingestion 的 MarkdownChunkBuilder。
        self.chunk_builder = chunk_builder or MarkdownChunkBuilder()

    async def plan_action(
        self,
        request: KnowledgeDocumentActionRequest,
        user: CurrentUserContext,
    ) -> KnowledgeDocumentActionResult:
        """生成文档管理动作的 dry-run 预览，或拒绝真实执行。"""

        # 总开关未启用时，Agent 不能进入任何文档管理链路。
        if not self.settings.agent_document_tools_enabled:
            raise AppServiceError("Agent 文档管理工具未启用")

        # 先做路径安全解析，再做 create/update/delete 的业务前置条件检查。
        target = self._resolve_safe_target_path(request.target_path)
        self._validate_operation_requirements(request=request, target=target)

        # preview 是后续权限网关、TaskPlan 确认页面的事实输入。
        preview = self._build_preview(
            request=request,
            target=target,
            user=user,
            )

        # plan_action 默认只负责 dry-run；真实写入必须经过确认执行入口。
        if request.dry_run:
            return KnowledgeDocumentActionResult(
                operation=request.operation,
                target_path=request.target_path,
                dry_run=True,
                executed=False,
                preview=preview,
                message="已生成文档管理 dry-run 预览，尚未执行真实写入。",
            )

        # 安全默认值：即使上游传 dry_run=false，只要配置仍是 dry-run-only，就必须拒绝。
        if self.settings.agent_document_tools_dry_run_only:
            raise ToolExecutionRequiresConfirmationError(
                "当前配置只允许 dry-run，文档写操作需要经过 TaskPlan 权限校验和人工确认。"
            )

        # 如果配置要求人工确认，则普通 plan_action 不能直接执行写操作。
        if self.settings.agent_document_tools_require_confirmation:
            raise ToolExecutionRequiresConfirmationError(
                "文档写操作需要经过 TaskPlan 权限校验和人工确认后才能执行。"
            )

        # 兜底拒绝：真实执行只允许走 execute_confirmed_action，避免绕过权限网关。
        raise ToolExecutionRequiresConfirmationError(
            "文档真实执行路径必须通过 TaskPlan 确认入口。"
        )

    async def execute_confirmed_action(
        self,
        request: KnowledgeDocumentActionRequest,
        user: CurrentUserContext,
        expected_before_hash: str | None = None,
    ) -> KnowledgeDocumentActionResult:
        """执行已经通过 TaskPlan 权限网关和人工确认的文档动作。

        本阶段只修改知识库源文件，不直接写 Elasticsearch / Milvus。索引一致性继续由
        ingestion CLI 负责，避免把 TaskPlan 确认接口扩展成复杂异步索引任务。
        """

        if not self.settings.agent_document_tools_enabled:
            raise AppServiceError("Agent 文档管理工具未启用")

        # 确认接口仍受全局 dry-run-only 开关保护，便于本地演示和生产配置一键禁写。
        if self.settings.agent_document_tools_dry_run_only:
            raise ToolExecutionRequiresConfirmationError(
                "当前配置只允许 dry-run，请将 AGENT_DOCUMENT_TOOLS_DRY_RUN_ONLY=false 后再确认执行。"
            )

        # 执行前重新解析路径、校验动作要求、重建 preview，避免复用过期 plan 中的可变文件状态。
        target = self._resolve_safe_target_path(request.target_path)
        self._validate_operation_requirements(request=request, target=target)
        preview = self._build_preview(request=request, target=target, user=user)

        # before_hash 是乐观并发保护：plan 生成后文件被改过，就拒绝执行旧计划。
        if expected_before_hash and preview.before_hash != expected_before_hash:
            raise AppServiceError("目标文档已变化，before_hash 不匹配，拒绝执行旧 plan")

        # 当前只修改知识库源文件。ES / Milvus 索引重建交给 ingestion CLI，避免同步接口变重。
        if request.operation == KnowledgeDocumentOperation.CREATE:
            target.absolute_path.parent.mkdir(parents=True, exist_ok=True)
            target.absolute_path.write_text(request.content or "", encoding="utf-8")
            message = "已新增知识库源文件；请按需运行 ingestion 重建 ES / Milvus 索引。"
        elif request.operation == KnowledgeDocumentOperation.UPDATE:
            target.absolute_path.write_text(request.content or "", encoding="utf-8")
            message = "已修改知识库源文件；请按需运行 ingestion 重建 ES / Milvus 索引。"
        else:
            target.absolute_path.unlink()
            message = "已删除知识库源文件；请按需运行 ingestion 重建 ES / Milvus 索引。"

        return KnowledgeDocumentActionResult(
            operation=request.operation,
            target_path=request.target_path,
            dry_run=False,
            executed=True,
            preview=preview,
            message=message,
        )

    def _resolve_safe_target_path(self, target_path: str) -> SafeDocumentTarget:
        """把用户传入路径转换成知识库内的安全目标路径。"""

        # 统一 Windows / Unix 分隔符，保证后续路径切分逻辑一致。
        requested_path = target_path.strip().replace("\\", "/")
        if not requested_path:
            raise AppServiceError("target_path 不能为空")

        # 明确拒绝 ..，避免 Agent 或用户构造路径穿越到知识库外部。
        raw_parts = [part for part in requested_path.split("/") if part]
        if any(part == ".." for part in raw_parts):
            raise AppServiceError("target_path 不能包含 .. 路径穿越片段")

        # strict=False 允许目标文件尚未存在，create 场景需要先解析未来路径。
        knowledge_base_root = Path(self.settings.knowledge_base_dir)
        resolved_root = knowledge_base_root.resolve(strict=False)
        candidate = Path(requested_path)
        if not candidate.is_absolute():
            root_name = knowledge_base_root.name
            # 兼容用户传入 "knowledge-base/xxx.md" 或只传 "xxx.md" 两种相对路径。
            if raw_parts and raw_parts[0] == root_name:
                candidate = knowledge_base_root.parent.joinpath(*raw_parts)
            else:
                candidate = knowledge_base_root.joinpath(*raw_parts)

        resolved_candidate = candidate.resolve(strict=False)
        try:
            relative = resolved_candidate.relative_to(resolved_root)
        except ValueError as exc:
            # resolve 后仍不在知识库根目录内，说明路径试图越界。
            raise AppServiceError(
                "target_path 不在 KNOWLEDGE_BASE_DIR 配置的知识库根目录内"
            ) from exc

        if not relative.parts:
            raise AppServiceError("target_path 必须指向知识库内的具体文档")

        relative_path = relative.as_posix()
        suffix = resolved_candidate.suffix.lower()
        allowed_extensions = self.settings.agent_document_tools_allowed_extension_list
        # 文件后缀白名单防止 Agent 修改任意二进制、脚本或配置文件。
        if suffix not in allowed_extensions:
            raise AppServiceError(
                "不支持的文档类型: "
                f"{suffix or '<empty>'}; 允许类型: {', '.join(allowed_extensions)}"
            )

        # 默认禁止修改权限规则文件，避免 Agent 通过改 ACL 文件扩大自己的权限。
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
        """拒绝修改权限控制文件和 sidecar metadata 文件。"""

        path = Path(relative_path)
        if path.name == PERMISSION_RULES_FILE_NAME or relative_path.endswith(".meta.json"):
            raise AppServiceError(
                "默认不允许 Agent 修改权限规则文件或 sidecar metadata 文件"
            )

    def _document_type_from_suffix(self, suffix: str) -> DocumentType:
        """把文件后缀映射成 ingestion 层使用的文档类型。"""

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

        # create 只能创建新文件，并且必须提供非空内容。
        if request.operation == KnowledgeDocumentOperation.CREATE:
            if exists_before:
                raise AppServiceError("create_document 要求目标文档不存在")
            if not content.strip():
                raise AppServiceError("create_document 要求 content 非空")

        # update 只能修改已有文件，并且必须提供非空新内容。
        if request.operation == KnowledgeDocumentOperation.UPDATE:
            if not exists_before:
                raise AppServiceError("update_document 要求目标文档已存在")
            if not content.strip():
                raise AppServiceError("update_document 要求 content 非空")

        # delete 只能删除已有文件，且不接受 content，避免误把删除请求当更新请求处理。
        if request.operation == KnowledgeDocumentOperation.DELETE:
            if not exists_before:
                raise AppServiceError("delete_document 要求目标文档已存在")
            if content.strip():
                raise AppServiceError("delete_document 不允许传入 content")

        # 内容大小限制在 service 层再兜底一次，避免超大内容进入 chunk / hash 计算。
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
        # preview_content 表示“执行后预计会参与 ingestion 的内容”。
        # 对 delete 来说，它仍使用旧内容来估算会影响多少 chunk。
        preview_content = self._preview_content(
            request=request,
            before_content=before_content,
        )
        # 复用 ingestion metadata 构建逻辑，保证 preview 里的权限信息和真实入库逻辑一致。
        metadata = build_document_metadata(
            source_path=target.source_path,
            document_type=target.document_type,
            knowledge_base_dir=self.settings.knowledge_base_dir,
        )
        # dry-run 不写索引，只在内存里构建 chunk，用于估算影响范围。
        chunks = self._build_preview_chunks(
            target=target,
            content=preview_content,
            metadata=metadata,
        )
        # warnings 不阻断执行，只给 plan review / 前端确认页展示潜在风险。
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
            # before_hash / after_hash 是人工确认和并发保护的重要事实。
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
        """计算 dry-run 预览时应参与 hash 和 chunk 估算的内容。"""

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

        # 构造临时 LoadedDocument，只用于预览 chunk 数，不落盘也不写向量库 / ES。
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

        # planner / 用户声称的目标部门和服务端规则推断不一致时，要提示人工复查。
        if expected_departments and expected_departments != metadata_departments:
            warnings.append(
                "expected_department_codes 与服务端权限规则推断出的部门不一致"
            )

        # 用户不属于目标部门时不在这里直接拒绝；真正拒绝由权限网关处理。
        # 这里先生成 warning，方便 plan review 页面解释风险。
        if metadata_departments and user_departments:
            missing = metadata_departments - user_departments
            if missing:
                warnings.append(
                    "当前用户不属于目标文档推断部门: "
                    + ",".join(sorted(missing))
                )

        # 删除动作影响更大，预览阶段明确提示后续需要人工确认。
        if request.operation == KnowledgeDocumentOperation.DELETE:
            warnings.append("delete 当前只允许 dry-run，后续需要人工确认后执行 soft delete")

        return warnings

    def _risk_level_for_operation(
        self,
        operation: KnowledgeDocumentOperation,
    ) -> KnowledgeDocumentRiskLevel:
        """根据动作类型给出默认风险等级。"""

        if operation == KnowledgeDocumentOperation.CREATE:
            return KnowledgeDocumentRiskLevel.MEDIUM
        if operation == KnowledgeDocumentOperation.UPDATE:
            return KnowledgeDocumentRiskLevel.HIGH
        return KnowledgeDocumentRiskLevel.CRITICAL

    def _requires_confirmation(self, operation: KnowledgeDocumentOperation) -> bool:
        """判断当前动作是否必须进入人工确认流程。"""

        if self.settings.agent_document_tools_require_confirmation:
            return True
        return operation in {
            KnowledgeDocumentOperation.UPDATE,
            KnowledgeDocumentOperation.DELETE,
        }

    def _read_text_if_exists(self, path: Path) -> str | None:
        """读取已有目标文件；不存在时返回 None，供 create 场景使用。"""

        if not path.exists():
            return None
        if not path.is_file():
            raise AppServiceError("target_path 必须指向普通文件")
        return path.read_text(encoding="utf-8")

    def _sha256_text(self, text: str) -> str:
        """计算文本 SHA256，用于 plan 事实快照和执行前变更检测。"""

        return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["KnowledgeDocumentManagementService", "SafeDocumentTarget"]
