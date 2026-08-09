"""Deep Agents 文档链路最小回归；默认离线，RUN_REAL_LLM=1 时调用真实 Qwen。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("LANGSMITH_TRACING", "false")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

from fast_app.components.retrievers.base import BaseRetriever
from fast_app.agents.runtime.langchain_agent_middlewares import (
    SharedModelCallBudgetExceededError,
    SharedModelCallBudgetMiddleware,
)
from fast_app.core.config import Settings, get_settings
from fast_app.domain.agent_task_plan import AgentResearchPolicy, AgentTaskPlanStatus
from fast_app.domain.agent_tool_permissions import (
    AgentToolPermissionAction,
    AgentToolPermissionDecision,
    PermissionCode,
)
from fast_app.domain.document_workflow import (
    DocumentChangeProposal,
    DocumentDeliverable,
    DocumentDraftResult,
    DocumentResearchResult,
    DocumentReviewResult,
    DocumentWorkflowDecision,
    DocumentWorkflowResult,
)
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionPreview,
    KnowledgeDocumentActionResult,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.rag_models import RetrievalFilters, RetrievalOptions, RetrievedDoc
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.deep_document_agent import (
    DeepDocumentAgent,
    DeepDocumentAgentRunResult,
    DocumentReadSnapshot,
    REVIEWER_PROMPT,
    WRITER_PROMPT,
    _CoordinatorToolExclusionMiddleware,
    _DocumentCoordinatorProgressMiddleware,
    _ResearcherToolExclusionMiddleware,
    _TodoToolExclusionMiddleware,
)
from fast_app.services.agent_tasks.deep_document_runtime import DeepDocumentRuntime
from fast_app.services.agent_tasks.document_task_executor import DocumentTaskExecutor
from fast_app.services.agent_tasks.document_supervisor_agent import DocumentSupervisorAgent
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.callbacks import AsyncCallbackHandler
from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph


ORIGINAL = "# Damage Rules\n\nBase damage is attack minus defense.\n"
UPDATED = "# Damage Rules\n\nFinal damage is max(1, attack - defense).\n"
DOC_ID = "doc_damage_rules"
SOURCE_PATH = "development/damage-rules.md"


class RealModelTraceHandler(AsyncCallbackHandler):
    """真实测试只统计模型调用数，不输出可能包含文档内容的 Tool 参数。"""

    def __init__(self) -> None:
        self.call_count = 0

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.call_count += 1


class FakeRetriever(BaseRetriever):
    async def retrieve(self, query: str, options: RetrievalOptions):
        return [
            RetrievedDoc(
                id="chunk_damage_rules",
                content=ORIGINAL,
                score=0.95,
                source="fake",
                title="Damage Rules",
                metadata={"doc_id": DOC_ID, "source_path": SOURCE_PATH},
            )
        ]


class FakeManagementService:
    def __init__(self) -> None:
        self.content = ORIGINAL

    def read_document_content(self, target_path: str) -> str:
        assert target_path == SOURCE_PATH
        return self.content

    async def read_document_content_current(
        self,
        target_path: str,
        *,
        doc_id: str | None = None,
        department_code: str | None = None,
    ) -> str:
        assert doc_id in {None, DOC_ID}
        assert department_code is None
        return self.read_document_content(target_path)

    async def plan_action(self, request, user, candidate_doc_id=None):
        assert candidate_doc_id in {None, DOC_ID}
        before_hash = sha256(self.content.encode("utf-8")).hexdigest()
        after_hash = (
            sha256((request.content or "").encode("utf-8")).hexdigest()
            if request.content is not None
            else None
        )
        return KnowledgeDocumentActionResult(
            operation=request.operation,
            target_path=request.target_path,
            dry_run=True,
            executed=False,
            preview=KnowledgeDocumentActionPreview(
                operation=request.operation,
                target_path=request.target_path,
                normalized_path=request.target_path,
                exists_before=True,
                risk_level=KnowledgeDocumentRiskLevel.HIGH,
                affected_doc_id=DOC_ID,
                affected_chunk_count=1,
                before_hash=before_hash,
                after_hash=after_hash,
                permission_metadata={"allowed_departments": ["development"]},
                requires_confirmation=True,
            ),
            message="dry-run",
        )


class FakePermissionService:
    async def authorize(self, user, context):
        return AgentToolPermissionDecision(
            action=AgentToolPermissionAction.CONFIRMATION_REQUIRED,
            allowed=True,
            reason="test",
            risk_level=context.risk_level,
            required_permissions=[PermissionCode.KNOWLEDGE_DOCUMENT_UPDATE],
            target_department_codes=context.target_department_codes,
            requires_confirmation=True,
        )


class FakeAuditService:
    async def record_decision(self, **kwargs):
        return None

    async def record_execution(self, **kwargs):
        return None


class StubSupervisor:
    async def decide(self, **kwargs):
        return build_decision()


class StubDeepAgent:
    async def run(self, **kwargs):
        review = DocumentReviewResult(
            deliverable_id="damage_update",
            verdict="approved",
            confidence=0.95,
        )
        proposal = DocumentChangeProposal(
            deliverable_id="damage_update",
            operation="update",
            candidate_doc_id=DOC_ID,
            candidate_source_path=SOURCE_PATH,
            base_sha256=sha256(ORIGINAL.encode("utf-8")).hexdigest(),
            content=UPDATED,
            reason="test update",
            selection_reason="ACL candidate",
            review=review,
        )
        return DeepDocumentAgentRunResult(
            workflow=DocumentWorkflowResult(
                research_results=[
                    DocumentResearchResult(
                        deliverable_id="damage_update",
                        status="completed",
                        findings=["minimum damage is required"],
                    )
                ],
                draft_results=[
                    DocumentDraftResult(
                        deliverable_id="damage_update",
                        operation="update",
                        candidate_doc_id=DOC_ID,
                        candidate_source_path=SOURCE_PATH,
                        base_sha256=proposal.base_sha256,
                        content=UPDATED,
                    )
                ],
                review_results=[review],
                approved_changes=[proposal],
                used_tools=["knowledge_retrieval", "knowledge_document_read"],
            ),
            candidates={
                DOC_ID: {
                    "doc_id": DOC_ID,
                    "source_path": SOURCE_PATH,
                    "title": "Damage Rules",
                }
            },
            read_snapshots={
                DOC_ID: DocumentReadSnapshot(
                    doc_id=DOC_ID,
                    source_path=SOURCE_PATH,
                    content=ORIGINAL,
                    sha256=proposal.base_sha256 or "",
                )
            },
        )


class TimeoutDeepAgent:
    """模拟外部模型链路超过文档 Worker 总墙钟预算。"""

    async def run(self, **kwargs):
        raise TimeoutError("document worker timed out")


def build_decision() -> DocumentWorkflowDecision:
    return DocumentWorkflowDecision(
        execution_mode="agentic",
        objective="Update damage calculation documentation",
        deliverables=[
            DocumentDeliverable(
                deliverable_id="damage_update",
                title="Damage Rules Update",
                operation="update",
                target_hint=SOURCE_PATH,
                objective="Add an explicit minimum damage rule",
            )
        ],
        web_policy="disabled",
        reason="Requires research, writing and independent review",
    )


def build_user() -> CurrentUserContext:
    return CurrentUserContext(
        user_id="tool_admin",
        is_authenticated=True,
        auth_source="jwt",
        global_role_codes=["system_admin"],
        department_codes=["development"],
        primary_department_code="development",
    )


async def test_deterministic_boundary() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="test-key",
            AGENT_DOCUMENT_TOOLS_ENABLED=True,
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Update damage rules after reviewing related documents",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        store.save(plan)
        management = FakeManagementService()
        executor = DocumentTaskExecutor(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            document_management_service=management,  # type: ignore[arg-type]
            tool_permission_service=FakePermissionService(),  # type: ignore[arg-type]
            tool_audit_service=FakeAuditService(),  # type: ignore[arg-type]
            task_plan_store=store,
            supervisor_agent=StubSupervisor(),  # type: ignore[arg-type]
            deep_document_agent=StubDeepAgent(),  # type: ignore[arg-type]
        )
        result = await executor.execute(
            plan=plan,
            user=build_user(),
            mode="hybrid",
            top_k=5,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(can_read_all=True),
        )
        assert result.status == AgentTaskPlanStatus.WAITING_CONFIRMATION
        assert len(result.steps) == 1
        assert result.steps[0].output["preview"]["before_hash"] == sha256(
            ORIGINAL.encode("utf-8")
        ).hexdigest()
        assert result.steps[0].output["action_request"]["content"] == UPDATED
        assert management.content == ORIGINAL, "dry-run 前不得修改真实文档"
        assert any(
            event.get("event") == "agent_task_document_action_prepared"
            for event in result.final_output["document_progress"]["events"]
        )


async def test_recoverable_document_failure_returns_task_plan() -> None:
    """可重试的模型/超时错误应返回 failed TaskPlan，而不是冒泡成通用 500。"""

    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="test-key",
            AGENT_DOCUMENT_TOOLS_ENABLED=True,
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Create a researched document",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        store.save(plan)
        executor = DocumentTaskExecutor(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            document_management_service=FakeManagementService(),  # type: ignore[arg-type]
            tool_permission_service=FakePermissionService(),  # type: ignore[arg-type]
            tool_audit_service=FakeAuditService(),  # type: ignore[arg-type]
            task_plan_store=store,
            supervisor_agent=StubSupervisor(),  # type: ignore[arg-type]
            deep_document_agent=TimeoutDeepAgent(),  # type: ignore[arg-type]
        )
        result = await executor.execute(
            plan=plan,
            user=build_user(),
            mode="hybrid",
            top_k=5,
            candidate_k=None,
            min_score=0.0,
            filters=RetrievalFilters(can_read_all=True),
        )
        assert result.status == AgentTaskPlanStatus.FAILED
        assert result.error == "TimeoutError: document worker timed out"


async def test_subagent_model_limit_isolated_as_tool_failure() -> None:
    """Reviewer 预算耗尽只能失败当前 task，不能让整个 Deep Agent 图返回 500。"""

    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="test-key",
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Create a reviewed document",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        plan.final_output["document_progress"] = {"events": []}
        store.save(plan)
        middleware = _DocumentCoordinatorProgressMiddleware(
            store,
            plan.task_plan_id,
            deliverable_ids=("damage_update",),
            deliverables=(
                DocumentDeliverable(
                    deliverable_id="damage_update",
                    title="Damage update",
                    operation="create",
                    target_hint="development/damage-update.md",
                    objective="Create the reviewed damage document",
                ),
            ),
            max_revision_rounds=2,
        )

        researcher_call = {
            "id": "task-researcher-1",
            "name": "task",
            "args": {
                "subagent_type": "document-researcher",
                "description": "Research deliverable damage_update",
            },
        }

        class Request:
            tool_call = researcher_call
            state = {
                "messages": [
                    AIMessage(content="", tool_calls=[researcher_call]),
                ]
            }

        async def exhausted_handler(_request):
            raise ModelCallLimitExceededError(
                thread_count=12,
                run_count=12,
                thread_limit=None,
                run_limit=12,
            )

        result = await middleware.awrap_tool_call(Request(), exhausted_handler)
        assert isinstance(result, ToolMessage)
        assert "SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED" in str(result.content)
        latest = store.load(plan.task_plan_id)
        event = latest.final_output["document_progress"]["events"][-1]
        assert event["event"] == "agent_task_document_subagent_failed"
        assert event["error_code"] == "SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED"

        failed_state = {
            "messages": [
                AIMessage(content="", tool_calls=[researcher_call]),
                result,
            ]
        }
        graph = StateGraph(dict)
        graph.add_node("coordinator_before_model", middleware.before_model)
        graph.add_edge(START, "coordinator_before_model")
        graph.add_edge("coordinator_before_model", END)
        terminal = await graph.compile().ainvoke(failed_state)
        assert terminal is not None
        assert terminal["jump_to"] == "end"
        workflow = terminal["structured_response"]
        assert workflow.failed_deliverables[0].deliverable_id == "damage_update"
        assert (
            workflow.failed_deliverables[0].error_code
            == "SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED"
        )

        class WriterRequest:
            tool_call = {
                "id": "task-writer-1",
                "name": "task",
                "args": {
                    "subagent_type": "document-writer",
                    "description": "Write deliverable damage_update",
                },
            }
            state = failed_state

        writer_called = False

        async def forbidden_writer(_request):
            nonlocal writer_called
            writer_called = True
            return "unexpected"

        rejected = await middleware.awrap_tool_call(
            WriterRequest(),
            forbidden_writer,
        )
        assert writer_called is False
        assert isinstance(rejected, ToolMessage)
        assert "UPSTREAM_RESEARCH_FAILED" in str(rejected.content)

        successful_research_call = {
            **researcher_call,
            "id": "task-researcher-2",
        }
        successful_research = ToolMessage(
            content=json.dumps(
                {
                    "deliverable_id": "damage_update",
                    "status": "partial",
                    "evidence": [{"source_id": "doc-1"}],
                }
            ),
            tool_call_id="task-researcher-2",
            name="task",
        )

        class SuccessfulWriterRequest:
            tool_call = WriterRequest.tool_call
            state = {
                "messages": [
                    AIMessage(content="", tool_calls=[successful_research_call]),
                    successful_research,
                ],
                "files": {
                    "/workspace/research/damage_update/summary.md": {
                        "content": "verified evidence"
                    }
                },
            }

        async def allowed_writer(_request):
            return "allowed"

        assert (
            await middleware.awrap_tool_call(
                SuccessfulWriterRequest(),
                allowed_writer,
            )
            == "allowed"
        )

        writer_failure_call = SuccessfulWriterRequest.tool_call
        writer_failure = ToolMessage(
            content=json.dumps(
                {
                    "status": "failed",
                    "error_code": "SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED",
                    "subagent_type": "document-writer",
                    "deliverable_id": "damage_update",
                    "reason": "writer budget exhausted",
                }
            ),
            tool_call_id="task-writer-1",
            name="task",
            status="error",
        )
        writer_failed_state = {
            "messages": [
                AIMessage(content="", tool_calls=[successful_research_call]),
                successful_research,
                AIMessage(content="", tool_calls=[writer_failure_call]),
                writer_failure,
            ]
        }
        terminal = await graph.compile().ainvoke(writer_failed_state)
        failure = terminal["structured_response"].failed_deliverables[0]
        assert failure.deliverable_id == "damage_update"
        assert failure.error_code == "SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED"

        writer_success_call = {
            "id": "task-writer-approved",
            "name": "task",
            "args": {
                "subagent_type": "document-writer",
                "description": "Write deliverable damage_update",
            },
        }
        reviewer_success_call = {
            "id": "task-reviewer-approved",
            "name": "task",
            "args": {
                "subagent_type": "document-reviewer",
                "description": "Review deliverable damage_update",
            },
        }
        approved_review = DocumentReviewResult(
            deliverable_id="damage_update",
            verdict="approved",
            confidence=1.0,
        )
        approved_state = {
            "messages": [
                AIMessage(content="", tool_calls=[successful_research_call]),
                successful_research,
                AIMessage(content="", tool_calls=[writer_success_call]),
                ToolMessage(
                    content=DocumentDraftResult(
                        deliverable_id="damage_update",
                        operation="update",
                        candidate_doc_id="wrong-doc",
                        candidate_source_path="development/wrong.md",
                        base_sha256="wrong-sha",
                        content="# Approved\n",
                    ).model_dump_json(),
                    tool_call_id="task-writer-approved",
                    name="task",
                ),
                AIMessage(content="", tool_calls=[reviewer_success_call]),
                ToolMessage(
                    content=approved_review.model_dump_json(),
                    tool_call_id="task-reviewer-approved",
                    name="task",
                ),
            ]
        }
        terminal = await graph.compile().ainvoke(approved_state)
        approved_workflow = terminal["structured_response"]
        assert approved_workflow.approved_changes[0].content == "# Approved\n"
        assert approved_workflow.approved_changes[0].operation == "create"
        assert approved_workflow.approved_changes[0].filename == "damage-update.md"
        assert approved_workflow.approved_changes[0].candidate_doc_id is None
        assert approved_workflow.draft_results[0].operation == "create"
        assert approved_workflow.review_results[0].verdict == "approved"


async def test_shared_model_budget_and_deterministic_revision_limits() -> None:
    """全角色共享总预算，checkpoint 历史还必须阻止失败重试和超额返工。"""

    budget = SharedModelCallBudgetMiddleware(limit=2)

    async def model_handler(_request):
        return "ok"

    assert await budget.awrap_model_call(object(), model_handler) == "ok"
    assert await budget.awrap_model_call(object(), model_handler) == "ok"
    try:
        await budget.awrap_model_call(object(), model_handler)
    except SharedModelCallBudgetExceededError as exc:
        assert exc.used_calls == 2
        assert exc.limit == 2
    else:
        raise AssertionError("第三次模型调用应被共享总预算拒绝")

    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="test-key",
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Create a reviewed document",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        plan.final_output["document_progress"] = {"events": []}
        store.save(plan)
        middleware = _DocumentCoordinatorProgressMiddleware(
            store,
            plan.task_plan_id,
            deliverable_ids=("damage_update",),
            max_revision_rounds=1,
        )
        description = "Revise deliverable damage_update using its fixed draft path"
        failed_call = {
            "id": "writer-failed",
            "name": "task",
            "args": {
                "subagent_type": "document-writer",
                "description": description,
            },
        }
        retry_call = {
            "id": "writer-retry",
            "name": "task",
            "args": {
                "subagent_type": "document-writer",
                "description": description,
            },
        }

        class RetryRequest:
            tool_call = retry_call
            state = {
                "messages": [
                    AIMessage(content="", tool_calls=[failed_call]),
                    ToolMessage(
                        content='{"error_code":"SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED"}',
                        tool_call_id="writer-failed",
                        name="task",
                        status="error",
                    ),
                    AIMessage(content="", tool_calls=[retry_call]),
                ]
            }

        called = False

        async def forbidden_handler(_request):
            nonlocal called
            called = True
            return "unexpected"

        rejected = await middleware.awrap_tool_call(
            RetryRequest(),
            forbidden_handler,
        )
        assert called is False
        assert isinstance(rejected, ToolMessage)
        assert rejected.status == "error"
        assert "SUBAGENT_RETRY_FORBIDDEN" in str(rejected.content)

        prior_calls = [
            {
                "id": f"writer-{index}",
                "name": "task",
                "args": {
                    "subagent_type": "document-writer",
                    "description": (
                        f"Writer pass {index} for deliverable damage_update"
                    ),
                },
            }
            for index in (1, 2)
        ]
        current_call = {
            "id": "writer-3",
            "name": "task",
            "args": {
                "subagent_type": "document-writer",
                "description": "Writer pass 3 for deliverable damage_update",
            },
        }

        class RevisionLimitRequest:
            tool_call = current_call
            state = {
                "messages": [
                    *[
                        message
                        for call in prior_calls
                        for message in (
                            AIMessage(content="", tool_calls=[call]),
                            ToolMessage(
                                content='{"status":"completed"}',
                                tool_call_id=str(call["id"]),
                                name="task",
                            ),
                        )
                    ],
                    AIMessage(content="", tool_calls=[current_call]),
                ]
            }

        rejected = await middleware.awrap_tool_call(
            RevisionLimitRequest(),
            forbidden_handler,
        )
        assert isinstance(rejected, ToolMessage)
        assert "SUBAGENT_REVISION_LIMIT_EXCEEDED" in str(rejected.content)


def test_document_content_models_have_streaming_retry_policy() -> None:
    """Researcher 和 Writer 的长内容请求必须流式接收且不得自动重放。"""

    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="test-key",
            OPENAI_BASE_URL="http://127.0.0.1:1",
            LLM_TIMEOUT_SECONDS=60,
            EXTERNAL_CALL_MAX_RETRIES=2,
            AGENT_DOCUMENT_RESEARCHER_TIMEOUT_SECONDS=120,
            AGENT_DOCUMENT_RESEARCHER_MAX_RETRIES=0,
            AGENT_DOCUMENT_COORDINATOR_TIMEOUT_SECONDS=120,
            AGENT_DOCUMENT_SUBAGENT_MAX_STEPS=10,
            AGENT_DOCUMENT_RESEARCHER_MAX_STEPS=12,
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        agent = DeepDocumentAgent(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            document_management_service=FakeManagementService(),  # type: ignore[arg-type]
            task_plan_store=AgentTaskPlanStore(settings),
        )
        standard_model = agent._build_model()
        coordinator_model = agent._build_model(
            timeout_seconds=settings.agent_document_coordinator_timeout_seconds,
            max_retries=0,
            streaming=True,
        )
        researcher_model = agent._build_model(
            timeout_seconds=settings.agent_document_researcher_timeout_seconds,
            max_retries=settings.agent_document_researcher_max_retries,
            streaming=True,
        )
        writer_model = agent._build_model(max_retries=0, streaming=True)

        assert standard_model.request_timeout == 60
        assert standard_model.max_retries == 2
        assert standard_model.streaming is False
        assert coordinator_model.max_retries == 0
        assert coordinator_model.streaming is True
        assert coordinator_model.request_timeout == 120
        assert researcher_model.request_timeout == 120
        assert researcher_model.max_retries == 0
        assert researcher_model.streaming is True
        assert writer_model.request_timeout == 60
        assert writer_model.max_retries == 0
        assert writer_model.streaming is True
        assert settings.agent_document_worker_timeout_seconds == 480
        assert settings.agent_document_max_total_model_calls == 36
        assert settings.agent_document_subagent_max_steps == 10
        assert settings.agent_document_researcher_max_steps == 12
        assert "offset=0、limit=1000" in WRITER_PROMPT
        assert "并行发出所有互不依赖的 edit_file" in WRITER_PROMPT
        assert "offset=0、limit=1000" in REVIEWER_PROMPT


async def test_coordinator_cannot_use_virtual_file_tools() -> None:
    """Coordinator 只能派发 SubAgent，不能接管 Writer 的虚拟草稿。"""

    class Request:
        def __init__(self, tools):
            self.tools = tools

        def override(self, **updates):
            return Request(updates.get("tools", self.tools))

    captured = None

    async def handler(filtered_request):
        nonlocal captured
        captured = filtered_request
        return "ok"

    result = await _CoordinatorToolExclusionMiddleware().awrap_model_call(
        Request(
            [
                {"name": "task"},
                {"name": "write_todos"},
                {"name": "read_file"},
                {"name": "edit_file"},
            ]
        ),
        handler,
    )
    assert result == "ok"
    assert captured is not None
    assert [tool["name"] for tool in captured.tools] == ["task", "write_todos"]


async def test_researcher_excludes_todo_tool_and_prompt_together() -> None:
    """隐藏 write_todos 时不得保留要求模型调用它的框架提示。"""

    class Request:
        def __init__(self, *, system_message, tools, state=None):
            self.system_message = system_message
            self.tools = tools
            self.state = state or {}

        def override(self, **updates):
            return Request(
                system_message=updates.get("system_message", self.system_message),
                tools=updates.get("tools", self.tools),
                state=self.state,
            )

    request = Request(
        system_message=SystemMessage(
            content=[
                {"type": "text", "text": "research instructions"},
                {"type": "text", "text": f"\n\n{WRITE_TODOS_SYSTEM_PROMPT}"},
            ]
        ),
        tools=[
            {"name": "write_todos"},
            {"name": "knowledge_retrieval"},
            {"name": "knowledge_document_read"},
        ],
    )
    captured = None

    async def handler(filtered_request):
        nonlocal captured
        captured = filtered_request
        return "ok"

    result = await _ResearcherToolExclusionMiddleware().awrap_model_call(
        request,
        handler,
    )
    assert result == "ok"
    assert captured is not None
    assert [tool["name"] for tool in captured.tools] == ["knowledge_retrieval"]
    prompt = "\n".join(
        str(block.get("text") or "")
        for block in captured.system_message.content_blocks
        if isinstance(block, dict)
    )
    assert prompt == "research instructions"

    completed_request = Request(
        system_message=SystemMessage(content="research instructions"),
        tools=[
            {"name": "knowledge_retrieval"},
            {"name": "knowledge_document_read"},
            {"name": "write_file"},
        ],
        state={
            "messages": [
                ToolMessage(
                    content=f"evidence {index}",
                    tool_call_id=f"retrieval-{index}",
                    name="knowledge_retrieval",
                    status="success",
                )
                for index in range(
                    1,
                    _ResearcherToolExclusionMiddleware.MAX_RETRIEVAL_CALLS + 1,
                )
            ]
        },
    )
    await _ResearcherToolExclusionMiddleware(
        allow_document_read=True
    ).awrap_model_call(completed_request, handler)
    assert captured is not None
    assert [tool["name"] for tool in captured.tools] == [
        "knowledge_retrieval",
        "knowledge_document_read",
        "write_file",
    ]
    assert "不得再次调用这些工具" in str(captured.system_message.content)

    class ToolRequest:
        tool_call = {
            "id": "retrieval-over-boundary",
            "name": "knowledge_retrieval",
            "args": {"query": "duplicate"},
        }
        state = completed_request.state

    called = False

    async def forbidden_tool_handler(_request):
        nonlocal called
        called = True
        return "unexpected"

    boundary_result = await _ResearcherToolExclusionMiddleware(
        allow_document_read=True
    ).awrap_tool_call(ToolRequest(), forbidden_tool_handler)
    assert called is False
    assert isinstance(boundary_result, ToolMessage)
    assert boundary_result.status == "success"
    assert "next_action" in str(boundary_result.content)


async def test_non_coordinator_todo_exclusion_runs_in_compiled_graph() -> None:
    """编译后的 Agent 也必须在模型边界移除框架注入的 Todo 工具和提示。"""

    class CapturingModel(FakeMessagesListChatModel):
        bound_tool_names: list[str] = []
        received_messages: list[object] = []

        def bind_tools(self, tools, **kwargs):
            self.bound_tool_names = [
                str(tool.get("name", ""))
                if isinstance(tool, dict)
                else str(tool.name)
                for tool in tools
            ]
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.received_messages = list(messages)
            return super()._generate(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            )

    model = CapturingModel(responses=[AIMessage(content="done")])
    graph = create_agent(
        model=model,
        middleware=[
            TodoListMiddleware(),
            _TodoToolExclusionMiddleware(),
        ],
    )

    await graph.ainvoke({"messages": [{"role": "user", "content": "write"}]})

    assert "write_todos" not in model.bound_tool_names
    system_text = "\n".join(
        str(message.content)
        for message in model.received_messages
        if isinstance(message, SystemMessage)
    )
    assert WRITE_TODOS_SYSTEM_PROMPT not in system_text


async def test_create_researcher_does_not_receive_full_document_tool() -> None:
    """纯创建任务只消费检索证据，不把参考文档全文带入模型上下文。"""

    with TemporaryDirectory() as temp_dir:
        settings = Settings(
            _env_file=None,
            OPENAI_API_KEY="test-key",
            AGENT_TASK_PLAN_DIR=temp_dir,
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Create a researched document",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        agent = DeepDocumentAgent(
            settings=settings,
            vector_retriever=FakeRetriever(),
            keyword_retriever=FakeRetriever(),
            document_management_service=FakeManagementService(),  # type: ignore[arg-type]
            task_plan_store=store,
        )

        async def persist() -> None:
            return None

        async def tool_names(decision: DocumentWorkflowDecision) -> list[str]:
            tools = await agent._build_research_tools(
                plan=plan,
                decision=decision,
                user=build_user(),
                mode="hybrid",
                top_k=5,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(can_read_all=True),
                candidates={},
                read_snapshots={},
                used_tools=set(),
                persist_runtime_facts=persist,
            )
            return [tool.name for tool in tools]

        create_decision = DocumentWorkflowDecision(
            execution_mode="agentic",
            objective="Create a governance document",
            deliverables=[
                DocumentDeliverable(
                    deliverable_id="governance_create",
                    title="Governance",
                    operation="create",
                    target_hint="development/governance.md",
                    objective="Create the document from retrieved evidence",
                )
            ],
            web_policy="disabled",
            reason="Requires research and writing",
        )
        create_tool_names = await tool_names(create_decision)
        update_tool_names = await tool_names(build_decision())
        assert "knowledge_retrieval" in create_tool_names
        assert "knowledge_document_read" not in create_tool_names
        assert "knowledge_retrieval" in update_tool_names
        assert "knowledge_document_read" in update_tool_names


async def test_supervisor_collapses_internal_agent_stages() -> None:
    """一个目标文件的研究、写作、审查是阶段，不是三个独立交付物。"""

    settings = Settings(_env_file=None, OPENAI_API_KEY="test-key")
    staged = DocumentWorkflowDecision(
        execution_mode="agentic",
        objective="创建 development/example.md 并完成研究、写作和审查",
        deliverables=[
            DocumentDeliverable(
                deliverable_id="research",
                title="研究证据",
                operation="create",
                objective="收集证据",
                required_capabilities=["knowledge_base_search"],
            ),
            DocumentDeliverable(
                deliverable_id="draft",
                title="文档初稿",
                operation="create",
                objective="编写草稿",
                depends_on=["research"],
                required_capabilities=["document_writing"],
            ),
            DocumentDeliverable(
                deliverable_id="review",
                title="审查方案",
                operation="create",
                objective="审查草稿",
                depends_on=["draft"],
                required_capabilities=["document_review"],
            ),
        ],
        web_policy="fallback",
        reason="需要三个角色协作",
    )
    normalized = DocumentSupervisorAgent(settings).validate_saved_decision(
        staged,
        allowed_web_policy="fallback",
        original_query="请创建 development/example.md，并由 Researcher、Writer、Reviewer 处理。",
    )
    assert len(normalized.deliverables) == 1
    deliverable = normalized.deliverables[0]
    assert deliverable.target_hint == "development/example.md"
    assert deliverable.depends_on == []
    assert set(deliverable.required_capabilities) == {
        "knowledge_base_search",
        "document_writing",
        "document_review",
    }


async def test_real_deep_agent() -> None:
    with TemporaryDirectory() as temp_dir:
        settings = get_settings().model_copy(
            update={
                "agent_task_plan_dir": temp_dir,
                "agent_max_steps": 8,
                "agent_max_tool_calls": 20,
                "agent_document_worker_timeout_seconds": float(
                    os.getenv("REAL_LLM_WORKER_TIMEOUT_SECONDS", "180")
                ),
            }
        )
        store = AgentTaskPlanStore(settings)
        plan = AgentTaskPlanner(settings).build_document_management_plan(
            query="Review the damage rules and update the document with an explicit minimum damage rule.",
            user_id="tool_admin",
            research_policy=AgentResearchPolicy(web_policy="disabled"),
        )
        # 生产入口会在调用 DeepDocumentAgent 前创建进度容器；直接测试需模拟同一前置状态。
        plan.final_output["document_progress"] = {"stage": "deep_agent_running", "events": []}
        store.save(plan)
        runtime = await DeepDocumentRuntime.start(settings)
        try:
            agent = DeepDocumentAgent(
                settings=settings,
                vector_retriever=FakeRetriever(),
                keyword_retriever=FakeRetriever(),
                document_management_service=FakeManagementService(),  # type: ignore[arg-type]
                task_plan_store=store,
                runtime=runtime,
            )
            trace_handler = RealModelTraceHandler()
            result = await agent.run(
                plan=plan,
                decision=build_decision(),
                user=build_user(),
                mode="hybrid",
                top_k=5,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(can_read_all=True),
                langchain_config={"callbacks": [trace_handler]},
            )
        finally:
            await runtime.release(plan.task_plan_id)
            await runtime.close()
        assert result.workflow.approved_changes, result.workflow.model_dump(mode="json")
        proposal = result.workflow.approved_changes[0]
        assert proposal.candidate_doc_id == DOC_ID
        assert proposal.base_sha256 == sha256(ORIGINAL.encode("utf-8")).hexdigest()
        assert "knowledge_document_read" in result.workflow.used_tools
        assert result.resumed_from_checkpoint is False
        assert result.checkpoint_record_version >= 1
        assert (
            trace_handler.call_count
            <= settings.agent_document_max_total_model_calls
        )
        print(f"real_model_call_count={trace_handler.call_count}", flush=True)


async def main() -> None:
    await test_deterministic_boundary()
    await test_recoverable_document_failure_returns_task_plan()
    await test_subagent_model_limit_isolated_as_tool_failure()
    await test_shared_model_budget_and_deterministic_revision_limits()
    test_document_content_models_have_streaming_retry_policy()
    await test_coordinator_cannot_use_virtual_file_tools()
    await test_researcher_excludes_todo_tool_and_prompt_together()
    await test_non_coordinator_todo_exclusion_runs_in_compiled_graph()
    await test_create_researcher_does_not_receive_full_document_tool()
    await test_supervisor_collapses_internal_agent_stages()
    if os.getenv("RUN_REAL_LLM") == "1":
        await test_real_deep_agent()
    print("deep_document_agent_workflow=passed")


if __name__ == "__main__":
    asyncio.run(main())
