import hashlib
import json
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
from fast_app.domain.knowledge_models import DocumentType, KnowledgeChunk, LoadedDocument
from fast_app.domain.user_context import CurrentUserContext
from fast_app.ingestion.chunk_builders import ChunkBuildOptions, MarkdownChunkBuilder
from fast_app.ingestion.metadata_models import (
    PERMISSION_RULES_FILE_NAME,
    build_document_metadata,
    normalize_permission_metadata,
)
from fast_app.ingestion.rag_store_writer import (
    delete_es_docs_by_doc_ids,
    delete_milvus_docs_by_doc_ids,
    escape_milvus_string,
    replace_docs_rag_stores,
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


@dataclass
class PreparedDocumentMutation:
    """确认执行前冻结的一项变更，以及失败时恢复它所需的完整快照。"""

    # 原始动作、规范化目标和 dry-run 预览共同描述“准备执行什么”。
    request: KnowledgeDocumentActionRequest
    target: SafeDocumentTarget
    preview: KnowledgeDocumentActionPreview
    # 源文件与 sidecar 的旧值用于文件系统补偿；None 表示执行前不存在。
    before_content: str | None
    before_sidecar: str | None
    # 旧、新 chunks 及向量提前算好，执行和回滚阶段都无需再次调用 embedding。
    old_chunks: list[KnowledgeChunk]
    old_vectors: list[list[float]]
    new_chunks: list[KnowledgeChunk]
    new_vectors: list[list[float]]


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
        # 确认执行使用这三个 client 生成向量并同步 ES / Milvus；dry-run 不写外部存储。
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
        preview = await self._build_preview(
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

    def read_document_content(self, target_path: str) -> str:
        """安全读取一个已存在的知识库源文档，供精确修改计划使用。"""

        target = self._resolve_safe_target_path(target_path)
        content = self._read_text_if_exists(target.absolute_path)
        if content is None:
            raise AppServiceError("目标文档不存在")
        return content

    async def execute_confirmed_action(
        self,
        request: KnowledgeDocumentActionRequest,
        user: CurrentUserContext,
        expected_before_hash: str | None = None,
    ) -> KnowledgeDocumentActionResult:
        """执行一个已确认动作；底层复用批量入口以获得相同回滚语义。"""

        results = await self.execute_confirmed_actions(
            actions=[(request, expected_before_hash)],
            user=user,
        )
        return results[0]

    async def execute_confirmed_actions(
        self,
        actions: list[tuple[KnowledgeDocumentActionRequest, str | None]],
        user: CurrentUserContext,
    ) -> list[KnowledgeDocumentActionResult]:
        """预计算整批变更，任一执行失败时恢复文件与两个检索存储。"""

        if not self.settings.agent_document_tools_enabled:
            raise AppServiceError("Agent 文档管理工具未启用")

        # 确认接口仍受全局 dry-run-only 开关保护，便于本地演示和生产配置一键禁写。
        if self.settings.agent_document_tools_dry_run_only:
            raise ToolExecutionRequiresConfirmationError(
                "当前配置只允许 dry-run，请将 AGENT_DOCUMENT_TOOLS_DRY_RUN_ONLY=false 后再确认执行。"
            )

        if not actions:
            raise AppServiceError("确认执行缺少文档动作")

        # 三个 client 是一组不可拆分的同步能力：要么全部存在并同步双库，要么全部缺省用于纯文件测试。
        # 禁止只配置其中一部分，否则文件写入成功后可能留下不一致的检索数据。
        store_clients = (
            self.embedding_client,
            self.elasticsearch_client,
            self.milvus_client,
        )
        if any(client is not None for client in store_clients) and not all(
            client is not None for client in store_clients
        ):
            raise AppServiceError("文档真实执行需要 embedding、Elasticsearch 和 Milvus client")
        sync_stores = all(client is not None for client in store_clients)

        prepared: list[PreparedDocumentMutation] = []
        seen_doc_ids: set[str] = set()
        # 第一阶段只做预检查和计算，不改文件或数据库。整批都准备成功后才进入写入阶段，
        # 避免执行到一半才发现后续动作的路径、版本或 embedding 无效。
        for request, expected_before_hash in actions:
            target = self._resolve_safe_target_path(request.target_path)
            self._validate_operation_requirements(request=request, target=target)
            preview = await self._build_preview(request=request, target=target, user=user)
            # before_hash 来自用户确认时看到的 plan；不一致说明确认后源文件又被修改过。
            if expected_before_hash and preview.before_hash != expected_before_hash:
                raise AppServiceError("目标文档已变化，before_hash 不匹配，拒绝执行旧 plan")
            doc_id = str(preview.affected_doc_id or "")
            # 一批内禁止重复操作同一 doc_id，避免 update/delete 顺序产生隐式依赖。
            if not doc_id or doc_id in seen_doc_ids:
                raise AppServiceError("批量计划包含空 doc_id 或重复目标文档")
            seen_doc_ids.add(doc_id)
            before_content = self._read_text_if_exists(target.absolute_path)
            sidecar = Path(f"{target.absolute_path}.meta.json")
            before_sidecar = sidecar.read_text(encoding="utf-8") if sidecar.exists() else None
            permission = normalize_permission_metadata(preview.permission_metadata)
            # update/delete 沿用预览阶段冻结的 ACL；LLM 请求不能提供或改写这些字段。
            old_chunks = self._build_chunks(
                target=target,
                content=before_content or "",
                permission_metadata=permission,
            )
            new_chunks = self._build_chunks(
                target=target,
                content=request.content or "",
                permission_metadata=permission,
            ) if request.operation != KnowledgeDocumentOperation.DELETE else []
            # embedding 也属于预计算：任何向量生成失败都会发生在真实写入之前。
            old_vectors = await self.embedding_client.embed_documents(
                [chunk.content for chunk in old_chunks]
            ) if old_chunks and sync_stores else []
            new_vectors = await self.embedding_client.embed_documents(
                [chunk.content for chunk in new_chunks]
            ) if new_chunks and sync_stores else []
            prepared.append(
                PreparedDocumentMutation(
                    request=request,
                    target=target,
                    preview=preview,
                    before_content=before_content,
                    before_sidecar=before_sidecar,
                    old_chunks=old_chunks,
                    old_vectors=old_vectors,
                    new_chunks=new_chunks,
                    new_vectors=new_vectors,
                )
            )

        results: list[KnowledgeDocumentActionResult] = []
        try:
            # 第二阶段严格按 TaskPlan 顺序执行，不并行，保证结果和人工确认步骤一致。
            for item in prepared:
                await self._apply_prepared_mutation(item)
                results.append(
                    KnowledgeDocumentActionResult(
                        operation=item.request.operation,
                        target_path=item.request.target_path,
                        dry_run=False,
                        executed=True,
                        preview=item.preview,
                        message="已同步更新知识库源文件、Elasticsearch 和 Milvus。",
                    )
                )
            return results
        except Exception as exc:
            rollback_errors: list[str] = []
            # 补偿按执行顺序的反方向进行，尽量恢复源文件、sidecar 和检索存储的旧快照。
            for item in reversed(prepared):
                try:
                    await self._restore_prepared_mutation(item)
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"{item.preview.affected_doc_id}:{type(rollback_exc).__name__}:{rollback_exc}"
                    )
            if rollback_errors:
                raise AppServiceError(
                    "文档批量执行失败且补偿未完全成功；需要修复 doc_id: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise AppServiceError("文档批量执行失败，已完成补偿回滚") from exc

    async def _apply_prepared_mutation(self, item: PreparedDocumentMutation) -> None:
        """把已预计算的单项变更写入源文件，并同步 ES/Milvus。"""

        path = item.target.absolute_path
        sidecar = Path(f"{path}.meta.json")
        if item.request.operation == KnowledgeDocumentOperation.DELETE:
            # delete 只使用冻结的 doc_id 删除目标文档 chunks，不执行全库重建。
            path.unlink()
            if sidecar.exists():
                sidecar.unlink()
            if self.elasticsearch_client is not None:
                await self._delete_doc_from_stores(str(item.preview.affected_doc_id))
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(item.request.content or "", encoding="utf-8")
        if item.request.operation == KnowledgeDocumentOperation.CREATE:
            # 只有 create 生成新 ACL sidecar；update 保留原 sidecar，禁止借正文修改变更权限。
            sidecar.write_text(
                json.dumps(item.preview.permission_metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        if self.elasticsearch_client is None:
            return
        # replace 是文档级覆盖：只替换同 doc_id 的 chunks，不影响其他文档。
        await replace_docs_rag_stores(
            elasticsearch_client=self.elasticsearch_client,
            milvus_client=self.milvus_client,
            settings=self.settings,
            chunks=item.new_chunks,
            vectors=item.new_vectors,
        )

    async def _restore_prepared_mutation(self, item: PreparedDocumentMutation) -> None:
        """根据 dry run 阶段快照补偿一项变更；用于批量失败后的逆序回滚。"""

        path = item.target.absolute_path
        sidecar = Path(f"{path}.meta.json")
        if item.before_content is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(item.before_content, encoding="utf-8")
        if item.before_sidecar is None:
            if sidecar.exists():
                sidecar.unlink()
        else:
            sidecar.write_text(item.before_sidecar, encoding="utf-8")
        if self.elasticsearch_client is None:
            return
        if item.old_chunks:
            # update/delete 原先有内容时，用旧 chunks 和旧向量恢复检索存储。
            await replace_docs_rag_stores(
                elasticsearch_client=self.elasticsearch_client,
                milvus_client=self.milvus_client,
                settings=self.settings,
                chunks=item.old_chunks,
                vectors=item.old_vectors,
            )
        else:
            # create 原先不存在，没有旧 chunks 可恢复，只需删除刚写入的 doc_id。
            await self._delete_doc_from_stores(str(item.preview.affected_doc_id))

    async def _delete_doc_from_stores(self, doc_id: str) -> None:
        """仅按 doc_id 删除目标文档在 ES/Milvus 中的 chunks。"""

        await delete_es_docs_by_doc_ids(
            client=self.elasticsearch_client,
            settings=self.settings,
            doc_ids=[doc_id],
        )
        delete_milvus_docs_by_doc_ids(
            client=self.milvus_client,
            settings=self.settings,
            doc_ids=[doc_id],
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
            # ingestion metadata 保存的 source_path 可能是包含知识库根目录的 repo 相对路径。
            # 如果它解析后已经位于根目录内，直接使用，避免再次拼接 KNOWLEDGE_BASE_DIR。
            resolved_from_workdir = candidate.resolve(strict=False)
            try:
                resolved_from_workdir.relative_to(resolved_root)
            except ValueError:
                root_name = knowledge_base_root.name
                # 兼容 "knowledge-base/xxx.md" 和只传 "xxx.md" 两种知识库相对路径。
                if raw_parts and raw_parts[0] == root_name:
                    candidate = knowledge_base_root.parent.joinpath(*raw_parts)
                else:
                    candidate = knowledge_base_root.joinpath(*raw_parts)
            else:
                candidate = resolved_from_workdir

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

    async def _build_preview(
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
        if request.operation == KnowledgeDocumentOperation.CREATE:
            # create 没有历史 ACL：优先继承当前用户主部门；无部门时退化为仅本人可见。
            if user.primary_department_code:
                metadata.update(
                    {
                        "visibility": "department",
                        "allowed_departments": [user.primary_department_code],
                        "allowed_users": [],
                        "permission_source": "creator_scope",
                    }
                )
            else:
                metadata.update(
                    {
                        "visibility": "restricted",
                        "allowed_departments": [],
                        "allowed_users": [user.user_id],
                        "permission_source": "creator_scope",
                    }
                )
        elif self.elasticsearch_client is not None and self.milvus_client is not None:
            # update/delete 的 ACL 以现有 ES/Milvus 共同记录为准，不能由请求内容决定。
            metadata.update(
                await self._load_stored_permission_metadata(str(metadata["doc_id"]))
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
        """按真实 ingestion 规则在内存中估算 dry-run 会影响的 chunks。"""

        if not content.strip():
            return []

        return self._build_chunks(
            target=target,
            content=content,
            permission_metadata=normalize_permission_metadata(metadata),
        )

    def _build_chunks(
        self,
        target: SafeDocumentTarget,
        content: str,
        permission_metadata: dict[str, Any],
    ) -> list[KnowledgeChunk]:
        """使用统一 metadata 和 chunk 配置构造可写入检索存储的 chunks。"""

        if not content.strip():
            return []
        # 从 source_path 重新生成 doc_id 等普通 metadata，再覆盖已冻结的权限字段。
        metadata = build_document_metadata(
            source_path=target.source_path,
            document_type=target.document_type,
            knowledge_base_dir=self.settings.knowledge_base_dir,
        )
        metadata.update(permission_metadata)
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

    async def _load_stored_permission_metadata(self, doc_id: str) -> dict[str, Any]:
        """读取并比较 ES/Milvus 中同一 doc_id 的权限字段。"""

        es_result = await self.elasticsearch_client.search(
            index=self.settings.elasticsearch_index_name,
            body={
                "size": 1,
                "_source": ["metadata"],
                "query": {"term": {"metadata.doc_id": doc_id}},
            },
        )
        es_hits = es_result.get("hits", {}).get("hits", [])
        milvus_rows = self.milvus_client.query(
            collection_name=self.settings.milvus_collection_name,
            filter=f'doc_id == "{escape_milvus_string(doc_id)}"',
            output_fields=["metadata"],
            limit=1,
        )
        if not es_hits or not milvus_rows:
            raise AppServiceError(
                f"目标文档在 ES/Milvus 中不存在或未同步: {doc_id}"
            )
        es_metadata = es_hits[0].get("_source", {}).get("metadata", {})
        milvus_metadata = milvus_rows[0].get("metadata", {})
        es_permission = normalize_permission_metadata(es_metadata)
        milvus_permission = normalize_permission_metadata(milvus_metadata)
        if es_permission != milvus_permission:
            raise AppServiceError(f"目标文档 ES/Milvus 权限 metadata 不一致: {doc_id}")
        return es_permission

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
            warnings.append("delete 当前只允许 dry-run，确认后执行删除，失败时补偿回滚")

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
