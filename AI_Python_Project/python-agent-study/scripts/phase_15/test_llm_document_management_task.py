from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ["LANGSMITH_TRACING"] = "false"

from langchain_core.messages import AIMessage, ToolMessage

import fast_app.services.agent_tasks.document_task_executor as document_module
from fast_app.services.agent_tasks import agent_task_plan_store as plan_store_module
from fast_app.services.agent_tasks.agent_task_tool_support import parallel_batch_error
import fast_app.services.knowledge.knowledge_document_management_service as management_module
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.retrievers.base import BaseRetriever
from fast_app.core.config import Settings
from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.domain.agent_tool_permissions import (
    AgentToolPermissionAction,
    AgentToolPermissionDecision,
    PermissionCode,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.rag_models import (
    RagContext,
    RetrievalFilters,
    RetrievalOptions,
    RetrievedDoc,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.ingestion.processing.metadata_models import build_document_metadata
from fast_app.services.agent_tasks.agent_task_executor import AgentTaskExecutor, AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.exceptions import AppServiceError
from fast_app.services.knowledge.knowledge_document_management_service import (
    KnowledgeDocumentManagementService,
)


class FakeRetriever(BaseRetriever):
    async def retrieve(self, query: str, options: RetrievalOptions):
        return [
            RetrievedDoc(
                id=f"chunk_{query}",
                content=f"fake evidence: {query}",
                score=0.9,
                source="fake",
                title="fake",
                metadata={
                    "doc_id": "doc_fake",
                    "source_path": "development/source.md",
                },
            )
        ]


class StaticRetriever(BaseRetriever):
    def __init__(self, doc: RetrievedDoc) -> None:
        self.doc = doc

    async def retrieve(self, query: str, options: RetrievalOptions):
        return [self.doc]


class FakeLLMClient(BaseLLMClient):
    async def generate(self, query: str, context: RagContext) -> str:
        return "unused"

    async def stream(self, query: str, context: RagContext):
        yield "unused"


class FakeEmbedding:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]


class FakePermissionService:
    async def authorize(self, user, context):
        if context.confirmation_text is not None:
            return AgentToolPermissionDecision(
                action=AgentToolPermissionAction.EXECUTE_ALLOWED,
                allowed=True,
                reason="测试确认执行",
                risk_level=context.risk_level,
                required_permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE],
                target_department_codes=context.target_department_codes,
                requires_confirmation=False,
            )
        return AgentToolPermissionDecision(
            action=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            allowed=True,
            reason="测试 dry-run 等待确认",
            risk_level=context.risk_level,
            required_permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE],
            target_department_codes=context.target_department_codes,
            requires_confirmation=True,
        )


class FakeAuditService:
    async def record_decision(self, **kwargs):
        return None

    async def record_execution(self, **kwargs):
        return None


class FakeBoundModel:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[object]] = []

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        self.messages.append(list(messages))
        if self.calls == 1:
            task_context = json.loads(messages[1].content)
            assert task_context == {
                "original_query": "创建一篇原生 Tool Calling 测试文档",
                "objective": "创建一篇原生 Tool Calling 测试文档",
            }
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_retrieval",
                        "args": {"query": "internal-a"},
                        "id": "parallel_read_a",
                        "type": "tool_call",
                    },
                    {
                        "name": "knowledge_retrieval",
                        "args": {"query": "internal-b"},
                        "id": "parallel_read_b",
                        "type": "tool_call",
                    },
                ],
            )
        if self.calls == 2:
            previous = messages[-2:]
            assert all(isinstance(item, ToolMessage) for item in previous)
            assert all(item.status == "success" for item in previous), [
                (item.status, item.content) for item in previous
            ]
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_document_create",
                        "args": {
                            "filename": "bad-a.md",
                            "content": "A",
                            "reason": "错误并行调用测试",
                        },
                        "id": "parallel_a",
                        "type": "tool_call",
                    },
                    {
                        "name": "knowledge_document_create",
                        "args": {
                            "filename": "bad-b.md",
                            "content": "B",
                            "reason": "错误并行调用测试",
                        },
                        "id": "parallel_b",
                        "type": "tool_call",
                    },
                ],
            )
        if self.calls == 3:
            previous = messages[-2:]
            assert all(isinstance(item, ToolMessage) for item in previous)
            assert all(item.status == "error" for item in previous)
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_document_create",
                        "args": {
                            "filename": "invalid.md",
                            "content": "invalid",
                            "reason": "验证 extra forbid",
                            "dry_run": False,
                        },
                        "id": "invalid_schema",
                        "type": "tool_call",
                    }
                ],
            )
        if self.calls == 4:
            assert isinstance(messages[-1], ToolMessage)
            assert messages[-1].tool_call_id == "invalid_schema"
            assert messages[-1].status == "error"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_document_create",
                        "args": {
                            "filename": "native-tool-call.md",
                            "content": "# 原生 Tool Calling\n\n```python\nprint('ok')\n```\n\n正文",
                            "reason": "验证 LLM 自主文档工具调用",
                        },
                        "id": "create_1",
                        "type": "tool_call",
                    }
                ],
            )
        assert self.calls == 5
        assert isinstance(messages[-1], ToolMessage)
        assert messages[-1].tool_call_id == "create_1"
        assert messages[-1].status == "success"
        return AIMessage(content="dry-run 已完成", tool_calls=[])


class FakeChatOpenAI:
    bound_model = FakeBoundModel()
    parallel_tool_calls: bool | None = None

    def __init__(self, **kwargs):
        pass

    def bind_tools(self, tools, **kwargs):
        FakeChatOpenAI.parallel_tool_calls = kwargs.get("parallel_tool_calls")
        return self.bound_model


class InterruptAfterRetrievalModel:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_retrieval",
                        "args": {"query": "恢复测试资料"},
                        "id": "resume_search",
                        "type": "tool_call",
                    }
                ],
            )
        raise asyncio.CancelledError


class ResumeCreateModel:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        if self.calls == 1:
            assert any(
                isinstance(message, ToolMessage)
                and message.tool_call_id == "resume_search"
                for message in messages
            )
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "knowledge_document_create",
                        "args": {
                            "filename": "resumed.md",
                            "content": "# 恢复后的候选正文",
                            "reason": "验证轮次检查点恢复",
                        },
                        "id": "resume_create",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="恢复完成", tool_calls=[])


class ModelWrapper:
    bound_model = None

    def __init__(self, **kwargs):
        pass

    def bind_tools(self, tools, **kwargs):
        return self.bound_model


class FakeUpdateModel:
    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self.calls = 0

    async def ainvoke(self, messages, config=None):
        self.calls += 1
        if self.calls == 1:
            name, args, call_id = "knowledge_retrieval", {"query": "旧内容"}, "search_1"
        elif self.calls == 2:
            assert isinstance(messages[-1], ToolMessage)
            name = "knowledge_document_update"
            args = {
                "doc_id": self.doc_id,
                "replacements": [{"old_text": "旧内容", "new_text": "新内容"}],
                "reason": "修改测试内容",
                "selection_reason": "检索结果唯一匹配",
            }
            call_id = "update_before_read"
        elif self.calls == 3:
            assert isinstance(messages[-1], ToolMessage)
            assert messages[-1].status == "error"
            name, args, call_id = (
                "knowledge_document_read",
                {"doc_id": self.doc_id},
                "read_1",
            )
        elif self.calls == 4:
            assert isinstance(messages[-1], ToolMessage)
            name = "knowledge_document_update"
            args = {
                "doc_id": self.doc_id,
                "replacements": [{"old_text": "旧内容", "new_text": "新内容"}],
                "reason": "修改测试内容",
                "selection_reason": "检索结果唯一匹配",
            }
            call_id = "update_1"
        else:
            assert isinstance(messages[-1], ToolMessage)
            assert messages[-1].tool_call_id == "update_1"
            return AIMessage(content="update dry-run 已完成", tool_calls=[])
        return AIMessage(
            content="",
            tool_calls=[
                {"name": name, "args": args, "id": call_id, "type": "tool_call"}
            ],
        )


async def main() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        kb = root / "kb"
        kb.mkdir()
        source = kb / "development" / "source.md"
        source.parent.mkdir()
        source.write_text("# source", encoding="utf-8")
        original_cwd = Path.cwd()
        try:
            os.chdir(root)
            relative_service = KnowledgeDocumentManagementService(
                Settings(KNOWLEDGE_BASE_DIR="kb")
            )
            assert relative_service.read_document_content(
                "kb/development/source.md"
            ) == "# source"
            assert relative_service.read_document_content(
                "development/source.md"
            ) == "# source"
        finally:
            os.chdir(original_cwd)

        settings = Settings(
            OPENAI_API_KEY="test-key",
            KNOWLEDGE_BASE_DIR=kb.as_posix(),
            AGENT_DOCUMENT_TOOLS_ENABLED=True,
            AGENT_DOCUMENT_TOOLS_DRY_RUN_ONLY=False,
            AGENT_MAX_TOOL_CALLS=12,
            AGENT_TASK_PLAN_DIR=(root / "plans").as_posix(),
            MARKDOWN_CHUNK_MIN_CHARS=1,
        )
        planner = AgentTaskPlanner(settings)
        plan = planner.build_document_management_plan(
            query="创建一篇原生 Tool Calling 测试文档",
            user_id="u1",
        )
        assert plan.steps == []

        user = CurrentUserContext(
            user_id="u1",
            is_authenticated=True,
            auth_source="jwt",
            role="user",
            permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_CREATE.value],
            department_codes=["development"],
            primary_department_code="development",
        )
        executor = AgentTaskExecutor(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            llm_client=FakeLLMClient(),
            document_management_service=KnowledgeDocumentManagementService(settings),
            tool_permission_service=FakePermissionService(),
            tool_audit_service=FakeAuditService(),
            task_plan_store=AgentTaskPlanStore(settings),
        )
        original = document_module.ChatOpenAI
        document_module.ChatOpenAI = FakeChatOpenAI
        try:
            result = await executor.execute(
                plan=plan,
                user=user,
                mode="hybrid",
                top_k=5,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(
                    user_id=user.user_id,
                    department_codes=user.department_codes,
                ),
            )
        finally:
            document_module.ChatOpenAI = original

        assert FakeChatOpenAI.parallel_tool_calls is True
        assert result.status == AgentTaskPlanStatus.WAITING_CONFIRMATION
        assert len(result.steps) == 1
        assert result.steps[0].output["tool_call_id"] == "create_1"
        assert result.steps[0].input["target_path"] == "development/native-tool-call.md"
        assert not (kb / "development" / "native-tool-call.md").exists()
        create_markdown = executor._task_plan_store.load_markdown(result.task_plan_id)
        assert "## 子问题拆解" not in create_markdown
        assert "#### 候选正文" in create_markdown
        assert "````markdown" in create_markdown
        assert "```python\nprint('ok')\n```" in create_markdown
        assert "development/native-tool-call.md" in create_markdown
        assert "creator_scope" in create_markdown
        assert result.steps[0].output["preview"]["affected_doc_id"] in create_markdown
        traces = result.final_output["tool_calls"]
        assert [item["call_id"] for item in traces] == [
            "parallel_read_a",
            "parallel_read_b",
            "parallel_a",
            "parallel_b",
            "invalid_schema",
            "create_1",
        ]
        assert [item["status"] for item in traces] == [
            "completed",
            "completed",
            "failed",
            "failed",
            "failed",
            "completed",
        ]
        assert [item["round"] for item in traces[:2]] == [1, 1]
        checkpoint = result.final_output["checkpoint"]
        assert checkpoint["completed"] is True
        assert checkpoint["round"] == 4
        assert checkpoint["call_count"] == 6
        assert checkpoint["messages"]
        assert document_module._document_batch_dependency_error(
            calls=[
                {"name": "knowledge_retrieval", "args": {"query": "x"}},
                {
                    "name": "knowledge_document_read",
                    "args": {"doc_id": "future_doc"},
                },
            ],
            candidates=set(),
            read_doc_ids=set(),
        ) is not None
        assert document_module._document_batch_dependency_error(
            calls=[
                {"name": "knowledge_document_read", "args": {"doc_id": "a"}},
                {"name": "knowledge_document_read", "args": {"doc_id": "b"}},
            ],
            candidates={"a", "b"},
            read_doc_ids=set(),
        ) is None
        assert parallel_batch_error(
            tool_names=["knowledge_retrieval", "knowledge_document_create"],
            registered_tool_names={"knowledge_retrieval", "knowledge_document_create"},
            parallel_safe_tool_names=document_module.PARALLEL_SAFE_DOCUMENT_TOOL_NAMES,
            max_parallel_calls=4,
            remaining_calls=12,
        ) is not None
        assert parallel_batch_error(
            tool_names=["knowledge_retrieval"] * 5,
            registered_tool_names={"knowledge_retrieval"},
            parallel_safe_tool_names=document_module.PARALLEL_SAFE_DOCUMENT_TOOL_NAMES,
            max_parallel_calls=4,
            remaining_calls=12,
        ) is not None

        resumable_plan = planner.build_document_management_plan(
            query="检索资料后创建一篇可恢复测试文档",
            user_id=user.user_id,
        )
        ModelWrapper.bound_model = InterruptAfterRetrievalModel()
        document_module.ChatOpenAI = ModelWrapper
        try:
            await executor.execute(
                plan=resumable_plan,
                user=user,
                mode="hybrid",
                top_k=5,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(
                    user_id=user.user_id,
                    department_codes=user.department_codes,
                ),
            )
            raise AssertionError("expected document loop interruption")
        except asyncio.CancelledError:
            pass
        interrupted = executor._task_plan_store.load(resumable_plan.task_plan_id)
        assert interrupted.status == AgentTaskPlanStatus.FAILED
        assert interrupted.final_output["checkpoint"]["round"] == 1
        assert interrupted.final_output["checkpoint"]["call_count"] == 1
        assert interrupted.final_output["checkpoint"]["candidates"]

        ModelWrapper.bound_model = ResumeCreateModel()
        document_module.ChatOpenAI = ModelWrapper
        resumed = await executor.resume(interrupted.task_plan_id, user=user)
        assert resumed.status == AgentTaskPlanStatus.WAITING_CONFIRMATION
        assert [
            item["tool_name"] for item in resumed.final_output["tool_calls"]
        ] == ["knowledge_retrieval", "knowledge_document_create"]
        assert resumed.final_output["checkpoint"]["call_count"] == 2
        assert resumed.final_output["checkpoint"]["completed"] is True
        resumed_markdown = executor._task_plan_store.load_markdown(resumed.task_plan_id)
        assert "## Tool Loop 检查点" in resumed_markdown
        assert "最近完整轮次: `2`" in resumed_markdown
        assert "已消耗 ToolCall: `2`" in resumed_markdown
        cancelled = executor.cancel(resumed.task_plan_id, user=user)
        assert cancelled.status == AgentTaskPlanStatus.CANCELLED
        assert all(step.status.value == "skipped" for step in cancelled.steps)
        try:
            await executor.confirm(cancelled.task_plan_id, user=user)
            raise AssertionError("expected cancelled plan confirmation to fail")
        except AppServiceError:
            pass
        document_module.ChatOpenAI = original

        confirmed = await executor.confirm(result.task_plan_id, user=user)
        assert confirmed.status == AgentTaskPlanStatus.COMPLETED
        created = kb / "development" / "native-tool-call.md"
        assert created.read_text(encoding="utf-8") == (
            "# 原生 Tool Calling\n\n```python\nprint('ok')\n```\n\n正文"
        )
        completed_markdown = executor._task_plan_store.load_markdown(result.task_plan_id)
        assert "#### 执行结果" in completed_markdown
        assert "已同步更新知识库源文件、Elasticsearch 和 Milvus" in completed_markdown

        target = kb / "development" / "existing.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# 标题\n\n旧内容\n", encoding="utf-8")
        metadata = build_document_metadata(
            source_path=target.as_posix(),
            document_type="markdown",
            knowledge_base_dir=kb.as_posix(),
        )
        metadata.update(
            {
                "visibility": "department",
                "allowed_departments": ["development"],
                "allowed_users": [],
            }
        )
        retrieved = RetrievedDoc(
            id="chunk_1",
            content="旧内容",
            score=0.9,
            source=target.as_posix(),
            title="existing",
            metadata=metadata,
        )
        update_plan = planner.build_document_management_plan(
            query="修改和旧内容相关的文档，将旧内容修改为新内容",
            user_id=user.user_id,
        )
        update_executor = AgentTaskExecutor(
            settings=settings.model_copy(update={"agent_max_tool_calls": 4}),
            vector_retriever=StaticRetriever(retrieved),
            keyword_retriever=StaticRetriever(retrieved),
            llm_client=FakeLLMClient(),
            document_management_service=KnowledgeDocumentManagementService(settings),
            tool_permission_service=FakePermissionService(),
            tool_audit_service=FakeAuditService(),
            task_plan_store=AgentTaskPlanStore(settings),
        )
        FakeChatOpenAI.bound_model = FakeUpdateModel(str(metadata["doc_id"]))
        document_module.ChatOpenAI = FakeChatOpenAI
        try:
            updated = await update_executor.execute(
                plan=update_plan,
                user=user,
                mode="hybrid",
                top_k=5,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(
                    user_id=user.user_id,
                    department_codes=user.department_codes,
                ),
            )
        finally:
            document_module.ChatOpenAI = original
        assert updated.status == AgentTaskPlanStatus.WAITING_CONFIRMATION
        assert updated.steps[0].output["tool_call_id"] == "update_1"
        assert "-旧内容" in updated.steps[0].output["diff"]
        assert "+新内容" in updated.steps[0].output["diff"]
        update_markdown = update_executor._task_plan_store.load_markdown(
            updated.task_plan_id
        )
        assert "#### 精确替换 1" in update_markdown
        assert "旧内容" in update_markdown
        assert "新内容" in update_markdown
        assert "#### 差异" in update_markdown
        assert target.read_text(encoding="utf-8") == "# 标题\n\n旧内容\n"
        assert any(
            item["call_id"] == "update_before_read" and item["status"] == "failed"
            for item in updated.final_output["tool_calls"]
        )

        delete_review = updated.model_copy(deep=True)
        delete_step = delete_review.steps[0]
        delete_step.tool_name = "knowledge_document_delete"
        delete_step.output["action_request"] = {
            "operation": "delete",
            "target_path": target.as_posix(),
            "content": None,
            "reason": "删除旧文档",
        }
        delete_step.output["candidate"] = {
            "title": "existing",
            "source_path": target.as_posix(),
            "matched_chunks": ["旧内容"],
        }
        delete_step.output["selection_reason"] = "检索结果与删除主题一致"
        delete_step.output["replacements"] = []
        delete_step.output["diff"] = ""
        delete_markdown = plan_store_module._render_task_plan_markdown(delete_review)
        assert "#### 删除候选证据" in delete_markdown
        assert "existing" in delete_markdown
        assert target.as_posix() in delete_markdown
        assert "##### 匹配片段 1" in delete_markdown

        question_review = updated.model_copy(deep=True)
        question_review.task_kind = "question_decomposition"
        question_review.final_output = {"final_answer": "综合答案"}
        question_markdown = plan_store_module._render_task_plan_markdown(question_review)
        assert "## 子问题拆解" in question_markdown
        assert "## 最终整合要求" in question_markdown
        assert "## 最终答案\n\n综合答案" in question_markdown

        seen_actions: dict[str, str] = {}
        await executor._document_executor._change_plan_service.prepare_dry_run(
            user=user,
            operation=KnowledgeDocumentOperation.CREATE,
            target_path="development/conflict.md",
            content="# first",
            reason="冲突检测",
            candidate=None,
            selection_reason="创建",
            replacements=[],
            document_actions=seen_actions,
        )
        try:
            await executor._document_executor._change_plan_service.prepare_dry_run(
                user=user,
                operation=KnowledgeDocumentOperation.CREATE,
                target_path="development/conflict.md",
                content="# second",
                reason="冲突检测",
                candidate=None,
                selection_reason="重复创建",
                replacements=[],
                document_actions=seen_actions,
            )
        except Exception as exc:
            assert "同一文档不能重复或冲突操作" in str(exc)
        else:
            raise AssertionError("同一文档重复动作必须被拒绝")

        rollback_service = KnowledgeDocumentManagementService(
            settings=settings,
            embedding_client=FakeEmbedding(),
            elasticsearch_client=object(),
            milvus_client=object(),
        )
        rollback_actions = [
            (
                KnowledgeDocumentActionRequest(
                    operation=KnowledgeDocumentOperation.CREATE,
                    target_path=f"development/rollback-{index}.md",
                    content=f"# rollback {index}",
                    reason="批量补偿测试",
                    dry_run=False,
                ),
                None,
            )
            for index in (1, 2)
        ]
        replace_calls = 0

        async def fake_replace(**kwargs):
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise RuntimeError("第二项写入失败")

        async def fake_delete_es(**kwargs):
            return {"deleted": 1}

        def fake_delete_milvus(**kwargs):
            return {"delete_count": 1}

        original_replace = management_module.replace_docs_rag_stores
        original_delete_es = management_module.delete_es_docs_by_doc_ids
        original_delete_milvus = management_module.delete_milvus_docs_by_doc_ids
        management_module.replace_docs_rag_stores = fake_replace
        management_module.delete_es_docs_by_doc_ids = fake_delete_es
        management_module.delete_milvus_docs_by_doc_ids = fake_delete_milvus
        try:
            try:
                await rollback_service.execute_confirmed_actions(
                    actions=rollback_actions,
                    user=user,
                )
            except Exception as exc:
                assert "已完成补偿回滚" in str(exc)
            else:
                raise AssertionError("第二项失败必须触发整批补偿")
        finally:
            management_module.replace_docs_rag_stores = original_replace
            management_module.delete_es_docs_by_doc_ids = original_delete_es
            management_module.delete_milvus_docs_by_doc_ids = original_delete_milvus
        assert not (kb / "development" / "rollback-1.md").exists()
        assert not (kb / "development" / "rollback-2.md").exists()

    print("llm_document_management_task=passed")


if __name__ == "__main__":
    asyncio.run(main())
