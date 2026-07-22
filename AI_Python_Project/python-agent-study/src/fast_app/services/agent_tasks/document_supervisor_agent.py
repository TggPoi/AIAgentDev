"""文档任务复杂度判断器：只决定 direct/agentic 和交付物，不生成写入参数。"""

from __future__ import annotations

import re
from collections.abc import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from fast_app.core.config import Settings
from fast_app.domain.document_workflow import DocumentWorkflowDecision
from fast_app.services.exceptions import AppServiceError


LangChainConfigFactory = Callable[[str], RunnableConfig]

DOCUMENT_SUPERVISOR_PROMPT = """你是知识库文档任务 Supervisor，只判断执行模式和拆分交付物。

选择 direct：单个明确文档的精确替换、删除，或内容和文件名都已明确的简单创建。
选择 agentic：多文档任务、跨来源研究、章节重构、内容综合，或需要独立审查和修订的任务。

你不能生成可信 doc_id、真实路径、ACL、权限或可直接执行的工具参数。
deliverable 表示最终要创建、更新或删除的一份真实文档，不表示内部处理步骤。
Researcher、Writer、Reviewer 是每个 deliverable 都会经过的固定阶段，绝对不能把
“研究证据”“文档初稿”“审查方案”拆成三个 deliverable。用户只要求一个目标文件时，
必须只返回一个 deliverable，并把研究、写作、审查写入其 source_requirements 或
required_capabilities。
deliverable_id 必须唯一；depends_on 只能引用本次 deliverables；不能形成循环依赖。
只返回结构化结果。
"""


class DocumentSupervisorAgent:
    """使用窄结构化输出把简单任务留在旧链路，把复杂任务交给 Deep Agents。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def decide(
        self,
        *,
        query: str,
        web_policy: str,
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> DocumentWorkflowDecision:
        """调用 Supervisor，并用规则复验模型给出的依赖图和联网范围。"""

        model = ChatOpenAI(
            model=self._settings.llm_model_name,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=0.0,
            timeout=self._settings.llm_timeout_seconds,
            **(
                {"extra_body": {"enable_thinking": False}}
                if self._settings.llm_model_name.lower().startswith("qwen")
                else {}
            ),
        ).with_structured_output(DocumentWorkflowDecision, method="function_calling")
        response = await model.ainvoke(
            [
                SystemMessage(content=DOCUMENT_SUPERVISOR_PROMPT),
                HumanMessage(
                    content=(
                        f"用户任务：\n{query}\n\n"
                        f"服务端允许的联网策略：{web_policy}"
                    )
                ),
            ],
            config=(
                langchain_config_factory("document.supervisor")
                if langchain_config_factory is not None
                else None
            ),
        )
        decision = (
            response
            if isinstance(response, DocumentWorkflowDecision)
            else DocumentWorkflowDecision.model_validate(response)
        )
        return self._validate(
            decision,
            allowed_web_policy=web_policy,
            original_query=query,
        )

    def validate_saved_decision(
        self,
        decision: DocumentWorkflowDecision,
        *,
        allowed_web_policy: str,
        original_query: str | None = None,
    ) -> DocumentWorkflowDecision:
        """重试时复验已冻结决定，不再次调用 LLM 改写交付物范围。"""

        return self._validate(
            decision,
            allowed_web_policy=allowed_web_policy,
            original_query=original_query,
        )

    def _validate(
        self,
        decision: DocumentWorkflowDecision,
        *,
        allowed_web_policy: str,
        original_query: str | None = None,
    ) -> DocumentWorkflowDecision:
        """拒绝重复 ID、非法依赖和越权联网，避免把模型输出直接当作控制事实。"""

        decision = _collapse_internal_stage_split(decision, original_query)
        if len(decision.deliverables) > self._settings.agent_document_max_deliverables:
            raise AppServiceError("文档 Supervisor 交付物数量超过服务端上限")
        ids = [item.deliverable_id for item in decision.deliverables]
        if len(ids) != len(set(ids)):
            raise AppServiceError("文档 Supervisor 产生了重复 deliverable_id")
        known = set(ids)
        dependencies: dict[str, set[str]] = {}
        for item in decision.deliverables:
            deps = set(item.depends_on)
            if item.deliverable_id in deps or not deps.issubset(known):
                raise AppServiceError("文档 Supervisor 产生了非法依赖")
            dependencies[item.deliverable_id] = deps
        _ensure_acyclic(dependencies)

        allowed_rank = {"disabled": 0, "fallback": 1, "required": 2}
        requested = decision.web_policy
        allowed = allowed_web_policy if allowed_web_policy in allowed_rank else "disabled"
        if allowed_rank[requested] > allowed_rank[allowed]:
            decision = decision.model_copy(update={"web_policy": allowed})
        if decision.execution_mode == "agentic" and not decision.deliverables:
            raise AppServiceError("agentic 文档任务缺少交付物")
        return decision


def _ensure_acyclic(dependencies: dict[str, set[str]]) -> None:
    """用拓扑消除检查循环；这里只验证，不承担运行时调度。"""

    remaining = {key: set(value) for key, value in dependencies.items()}
    while remaining:
        ready = {key for key, value in remaining.items() if not value}
        if not ready:
            raise AppServiceError("文档 Supervisor 交付物依赖存在循环")
        remaining = {
            key: value - ready for key, value in remaining.items() if key not in ready
        }


def _collapse_internal_stage_split(
    decision: DocumentWorkflowDecision,
    original_query: str | None,
) -> DocumentWorkflowDecision:
    """把“研究→草稿→审查”误拆分恢复成一个最终文档交付物。

    该规则只在原请求明确出现一个 Markdown/TXT 目标，且多个模型交付物具有
    相同文档操作并呈线性依赖时生效。它只修正 Supervisor 的编排粒度；目标路径
    仍是未受信的 hint，真实写入继续由后续服务端路径和权限校验决定。
    """

    if decision.execution_mode != "agentic" or len(decision.deliverables) < 2:
        return decision
    paths = {
        item.replace("\\", "/")
        for item in re.findall(
            r"[A-Za-z0-9_./\\\-\u4e00-\u9fff]+\.(?:md|txt)",
            original_query or "",
            flags=re.IGNORECASE,
        )
    }
    operations = {item.operation for item in decision.deliverables}
    dependencies = [item.depends_on for item in decision.deliverables]
    # 每个阶段最多依赖一个前序阶段，是 LLM 把流水线节点误当交付物的典型形状。
    looks_like_stage_chain = all(len(items) <= 1 for items in dependencies)
    if len(paths) != 1 or len(operations) != 1 or not looks_like_stage_chain:
        return decision
    source_requirements = list(
        dict.fromkeys(
            requirement
            for item in decision.deliverables
            for requirement in item.source_requirements
        )
    )
    capabilities = list(
        dict.fromkeys(
            capability
            for item in decision.deliverables
            for capability in item.required_capabilities
        )
    )
    deliverable = decision.deliverables[-1].model_copy(
        update={
            "deliverable_id": "document-output",
            "title": decision.deliverables[-1].title,
            "operation": next(iter(operations)),
            "target_hint": next(iter(paths)),
            "objective": decision.objective,
            "depends_on": [],
            "source_requirements": source_requirements,
            "required_capabilities": capabilities,
        }
    )
    return decision.model_copy(
        update={
            "deliverables": [deliverable],
            "reason": (
                f"{decision.reason}；内部研究、写作和审查阶段已合并到同一文档交付物。"
            )[:500],
        }
    )


__all__ = ["DocumentSupervisorAgent"]
