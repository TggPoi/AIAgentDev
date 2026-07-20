"""Deep Agent PostgreSQL checkpoint、sync durability 和任务互斥回归。"""

from __future__ import annotations

import asyncio
import base64
from tempfile import TemporaryDirectory
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

import fast_app.services.agent_tasks.deep_document_agent as deep_agent_module
from fast_app.core.config import get_settings
from fast_app.domain.agent_task_plan import AgentResearchPolicy
from fast_app.domain.document_workflow import DocumentWorkflowResult
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.services.agent_tasks.agent_task_executor import _TASK_PLAN_LOCKS
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.agent_tasks.agent_task_planner import AgentTaskPlanner
from fast_app.services.agent_tasks.deep_document_agent import DeepDocumentAgent
from fast_app.services.agent_tasks.deep_document_runtime import (
    DeepDocumentRuntime,
    DocumentRuntimeReadSnapshot,
    build_document_acl_fingerprint,
    decode_langgraph_aes_key,
)
from fast_app.services.exceptions import (
    AgentTaskPlanBusyError,
    DocumentAgentCheckpointConflictError,
    DocumentAgentCheckpointUnavailableError,
)
from scripts.phase_15.test_deep_document_agent_workflow import (
    FakeManagementService,
    FakeRetriever,
    build_decision,
    build_user,
)


class MarkerState(TypedDict):
    marker: str


class FakeDeepState(TypedDict, total=False):
    messages: list[Any]
    files: dict[str, Any]
    structured_response: dict[str, Any]


class SlowMemorySaver(InMemorySaver):
    """延迟 checkpoint 写入，用于证明 sync 会阻塞下一节点。"""

    def __init__(self) -> None:
        super().__init__()
        self.armed = False
        self.completed = asyncio.Event()

    async def aput(self, config, checkpoint, metadata, new_versions):
        await asyncio.sleep(0.02)
        result = await super().aput(config, checkpoint, metadata, new_versions)
        if self.armed:
            self.completed.set()
        return result


def test_key_validation() -> None:
    key = bytes(range(32))
    assert decode_langgraph_aes_key(base64.b64encode(key).decode("ascii")) == key
    for invalid in ("", "not-base64", base64.b64encode(b"x" * 31).decode("ascii")):
        try:
            decode_langgraph_aes_key(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("非法或非 32 字节密钥必须被拒绝")


async def test_sync_durability_waits_for_checkpoint() -> None:
    saver = SlowMemorySaver()
    graph = StateGraph(MarkerState)

    def first_node(state: MarkerState) -> MarkerState:
        saver.completed.clear()
        saver.armed = True
        return {"marker": state["marker"] + "-first"}

    def second_node(state: MarkerState) -> MarkerState:
        assert saver.completed.is_set(), "下一节点启动前 checkpoint 尚未完成"
        return {"marker": state["marker"] + "-second"}

    graph.add_node("first", first_node)
    graph.add_node("second", second_node)
    graph.add_edge(START, "first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)
    result = await graph.compile(checkpointer=saver).ainvoke(
        {"marker": "sync"},
        config={"configurable": {"thread_id": "sync-durability"}},
        durability="sync",
    )
    assert result["marker"] == "sync-first-second"


async def test_postgres_encryption_resume_and_record_version() -> None:
    settings = get_settings()
    task_plan_id = "task_plan_checkpoint_runtime_test"
    marker = "private-checkpoint-marker-20260719"
    runtime = await DeepDocumentRuntime.start(settings)
    try:
        await runtime.release(task_plan_id)
        record = await runtime.create_record(
            task_plan_id=task_plan_id,
            acl_fingerprint="acl-v1",
        )
        updated = await runtime.update_record(
            task_plan_id,
            expected_version=record.record_version,
            updates={"used_tools": ["knowledge_retrieval"]},
        )
        assert updated.record_version == 2
        try:
            await runtime.update_record(
                task_plan_id,
                expected_version=1,
                updates={"status": "failed"},
            )
        except DocumentAgentCheckpointConflictError:
            pass
        else:
            raise AssertionError("旧 record_version 必须触发冲突")

        graph = StateGraph(MarkerState)
        graph.add_node("write", lambda state: {"marker": state["marker"] + "-saved"})
        graph.add_edge(START, "write")
        graph.add_edge("write", END)
        config = {
            "configurable": {"thread_id": runtime.thread_id(task_plan_id)}
        }
        first_app = graph.compile(checkpointer=runtime.checkpointer)
        first = await first_app.ainvoke(
            {"marker": marker},
            config=config,
            durability="sync",
        )
        assert first["marker"] == marker + "-saved"

        def plaintext_blob_count() -> int:
            with runtime.pool.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT count(*)
                        FROM checkpoint_blobs
                        WHERE thread_id = %s
                          AND position(convert_to(%s, 'UTF8') in blob) > 0
                        """,
                        (runtime.thread_id(task_plan_id), marker),
                    )
                    return int(cursor.fetchone()["count"])

        assert await asyncio.to_thread(plaintext_blob_count) == 0
    finally:
        await runtime.close()

    # 模拟进程重启：重新创建连接池、Saver 和编译图，再用相同 thread_id 恢复。
    runtime = await DeepDocumentRuntime.start(settings)
    try:
        graph = StateGraph(MarkerState)
        graph.add_node("write", lambda state: {"marker": state["marker"] + "-saved"})
        graph.add_edge(START, "write")
        graph.add_edge("write", END)
        resumed = await graph.compile(checkpointer=runtime.checkpointer).ainvoke(
            None,
            config={
                "configurable": {"thread_id": runtime.thread_id(task_plan_id)}
            },
            durability="sync",
        )
        assert resumed["marker"] == marker + "-saved"
        assert await runtime.has_checkpoint(task_plan_id)
        await runtime.release(task_plan_id)
        assert await runtime.load_record(task_plan_id) is None
    finally:
        await runtime.close()


async def test_deep_agent_forces_sync_and_stable_thread() -> None:
    settings = get_settings()
    runtime = await DeepDocumentRuntime.start(settings)
    captured: dict[str, object] = {}

    class CaptureGraph:
        async def ainvoke(self, graph_input, *, config, durability):
            captured.update(
                graph_input=graph_input,
                config=config,
                durability=durability,
            )
            return {"structured_response": DocumentWorkflowResult()}

    original_factory = deep_agent_module.create_deep_agent
    deep_agent_module.create_deep_agent = lambda **kwargs: CaptureGraph()
    try:
        with TemporaryDirectory() as temp_dir:
            local_settings = settings.model_copy(
                update={"agent_task_plan_dir": temp_dir}
            )
            store = AgentTaskPlanStore(local_settings)
            plan = AgentTaskPlanner(local_settings).build_document_management_plan(
                query="Update the damage rules",
                user_id="tool_admin",
                research_policy=AgentResearchPolicy(web_policy="disabled"),
            )
            store.save(plan)
            agent = DeepDocumentAgent(
                settings=local_settings,
                vector_retriever=FakeRetriever(),
                keyword_retriever=FakeRetriever(),
                document_management_service=FakeManagementService(),  # type: ignore[arg-type]
                task_plan_store=store,
                runtime=runtime,
            )
            result = await agent.run(
                plan=plan,
                decision=build_decision(),
                user=build_user(),
                mode="hybrid",
                top_k=5,
                candidate_k=None,
                min_score=0.0,
                filters=RetrievalFilters(can_read_all=True),
                langchain_config={"configurable": {"thread_id": "untrusted"}},
            )
            assert captured["durability"] == "sync"
            assert captured["graph_input"] is not None
            config = captured["config"]
            assert isinstance(config, dict)
            assert config["configurable"]["thread_id"] == runtime.thread_id(
                plan.task_plan_id
            )
            assert result.checkpoint_record_version >= 1
            await runtime.release(plan.task_plan_id)
    finally:
        deep_agent_module.create_deep_agent = original_factory
        await runtime.close()


async def test_deep_agent_resumes_without_repeating_completed_node() -> None:
    settings = get_settings()
    runtime = await DeepDocumentRuntime.start(settings)
    calls = {"completed_node": 0, "failing_node": 0}

    def checkpointing_factory(**kwargs):
        graph = StateGraph(FakeDeepState)

        def completed_node(state: FakeDeepState) -> FakeDeepState:
            calls["completed_node"] += 1
            return {"files": dict(state.get("files") or {})}

        def failing_node(state: FakeDeepState) -> FakeDeepState:
            calls["failing_node"] += 1
            if calls["failing_node"] == 1:
                raise RuntimeError("simulated process interruption")
            return {
                "structured_response": DocumentWorkflowResult().model_dump(
                    mode="json"
                )
            }

        graph.add_node("completed_node", completed_node)
        graph.add_node("failing_node", failing_node)
        graph.add_edge(START, "completed_node")
        graph.add_edge("completed_node", "failing_node")
        graph.add_edge("failing_node", END)
        return graph.compile(checkpointer=kwargs["checkpointer"])

    original_factory = deep_agent_module.create_deep_agent
    deep_agent_module.create_deep_agent = checkpointing_factory
    try:
        with TemporaryDirectory() as temp_dir:
            local_settings = settings.model_copy(
                update={"agent_task_plan_dir": temp_dir}
            )
            store = AgentTaskPlanStore(local_settings)
            plan = AgentTaskPlanner(local_settings).build_document_management_plan(
                query="Update the damage rules",
                user_id="tool_admin",
                research_policy=AgentResearchPolicy(web_policy="disabled"),
            )
            store.save(plan)
            agent = DeepDocumentAgent(
                settings=local_settings,
                vector_retriever=FakeRetriever(),
                keyword_retriever=FakeRetriever(),
                document_management_service=FakeManagementService(),  # type: ignore[arg-type]
                task_plan_store=store,
                runtime=runtime,
            )
            common = {
                "plan": plan,
                "decision": build_decision(),
                "user": build_user(),
                "mode": "hybrid",
                "top_k": 5,
                "candidate_k": None,
                "min_score": 0.0,
                "filters": RetrievalFilters(can_read_all=True),
            }
            try:
                await agent.run(**common)
            except RuntimeError as exc:
                assert "simulated process interruption" in str(exc)
            else:
                raise AssertionError("第一次运行应在第二节点中断")

            result = await agent.run(**common, resume=True)
            assert result.resumed_from_checkpoint is True
            assert calls == {"completed_node": 1, "failing_node": 2}
            await runtime.release(plan.task_plan_id)
    finally:
        deep_agent_module.create_deep_agent = original_factory
        await runtime.close()


async def test_acl_source_and_missing_checkpoint_recovery_rules() -> None:
    settings = get_settings()
    runtime = await DeepDocumentRuntime.start(settings)
    try:
        with TemporaryDirectory() as temp_dir:
            local_settings = settings.model_copy(
                update={"agent_task_plan_dir": temp_dir}
            )
            store = AgentTaskPlanStore(local_settings)
            plan = AgentTaskPlanner(local_settings).build_document_management_plan(
                query="Update the damage rules",
                user_id="tool_admin",
                research_policy=AgentResearchPolicy(web_policy="disabled"),
            )
            store.save(plan)
            management = FakeManagementService()
            agent = DeepDocumentAgent(
                settings=local_settings,
                vector_retriever=FakeRetriever(),
                keyword_retriever=FakeRetriever(),
                document_management_service=management,  # type: ignore[arg-type]
                task_plan_store=store,
                runtime=runtime,
            )
            user = build_user()
            filters = RetrievalFilters(can_read_all=True)
            current_acl = build_document_acl_fingerprint(user, filters)

            await runtime.release(plan.task_plan_id)
            await runtime.create_record(
                task_plan_id=plan.task_plan_id,
                acl_fingerprint="stale-acl",
            )
            prepared = await agent._prepare_runtime(
                plan=plan,
                user=user,
                filters=filters,
                resume=True,
            )
            assert prepared[4] is False
            assert "acl_changed" in prepared[5]
            assert prepared[0].acl_fingerprint == current_acl

            await runtime.release(plan.task_plan_id)
            source_record = await runtime.create_record(
                task_plan_id=plan.task_plan_id,
                acl_fingerprint=current_acl,
            )
            await runtime.update_record(
                plan.task_plan_id,
                expected_version=source_record.record_version,
                updates={
                    "read_snapshots": {
                        "doc_damage_rules": DocumentRuntimeReadSnapshot(
                            doc_id="doc_damage_rules",
                            source_path="development/damage-rules.md",
                            sha256="0" * 64,
                        )
                    }
                },
            )
            prepared = await agent._prepare_runtime(
                plan=plan,
                user=user,
                filters=filters,
                resume=True,
            )
            assert prepared[4] is False
            assert "source_changed" in prepared[5]

            await runtime.release(plan.task_plan_id)
            await runtime.create_record(
                task_plan_id=plan.task_plan_id,
                acl_fingerprint=current_acl,
            )
            plan.final_output["deep_agent_checkpoint"] = {
                "status": "resumable",
                "durability": "sync",
            }
            store.save(plan)
            try:
                await agent._prepare_runtime(
                    plan=plan,
                    user=user,
                    filters=filters,
                    resume=True,
                )
            except DocumentAgentCheckpointUnavailableError:
                pass
            else:
                raise AssertionError("新格式运行记录缺少 checkpoint 时必须拒绝静默重跑")
            await runtime.release(plan.task_plan_id)
    finally:
        await runtime.close()


async def test_same_task_fail_fast_lock() -> None:
    task_plan_id = "task_plan_lock_test"
    entered = asyncio.Event()
    unblock = asyncio.Event()

    async def holder() -> None:
        async with _TASK_PLAN_LOCKS.hold(task_plan_id):
            entered.set()
            await unblock.wait()

    first = asyncio.create_task(holder())
    await entered.wait()
    try:
        try:
            async with _TASK_PLAN_LOCKS.hold(task_plan_id):
                raise AssertionError("并发请求不应取得同一任务锁")
        except AgentTaskPlanBusyError as exc:
            assert exc.error_code == "AGENT_TASK_PLAN_BUSY"
            assert exc.status_code == 409
    finally:
        unblock.set()
        await first


async def main() -> None:
    test_key_validation()
    await test_sync_durability_waits_for_checkpoint()
    await test_postgres_encryption_resume_and_record_version()
    await test_deep_agent_forces_sync_and_stable_thread()
    await test_deep_agent_resumes_without_repeating_completed_node()
    await test_acl_source_and_missing_checkpoint_recovery_rules()
    await test_same_task_fail_fast_lock()
    print("deep_document_checkpoint_runtime=passed")


if __name__ == "__main__":
    asyncio.run(main())
