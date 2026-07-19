"""文档任务复杂度判断器：只决定 direct/agentic 和交付物，不生成写入参数。"""

from __future__ import annotations

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
        return self._validate(decision, allowed_web_policy=web_policy)

    def validate_saved_decision(
        self,
        decision: DocumentWorkflowDecision,
        *,
        allowed_web_policy: str,
    ) -> DocumentWorkflowDecision:
        """重试时复验已冻结决定，不再次调用 LLM 改写交付物范围。"""

        return self._validate(decision, allowed_web_policy=allowed_web_policy)

    def _validate(
        self,
        decision: DocumentWorkflowDecision,
        *,
        allowed_web_policy: str,
    ) -> DocumentWorkflowDecision:
        """拒绝重复 ID、非法依赖和越权联网，避免把模型输出直接当作控制事实。"""

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


__all__ = ["DocumentSupervisorAgent"]
