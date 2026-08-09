from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger


logger = get_logger(__name__)

# Router 只能从这份有限的意图清单中选择；新增业务意图必须同步扩展 schema 与测试，
# 不能退回到散落在各节点中的关键词判断。
# simple_rag 不等于“一定不检索”。Router 只是表示“无需多步骤 TaskPlan”；后面仍由已有的 node节点 should_retrieve_for_query(...) 决定走 direct_answer 还是 knowledge_retrieval
AgentRouteIntent = Literal[
    # 不创建 TaskPlan，继续旧的“直接回答或知识库检索”逻辑
    "simple_rag",
    # 调用 Planner，将复杂问题拆成子问题，生成 TaskPlan
    "question_decomposition",
    # 创建文档管理 TaskPlan；真正写入仍要经过工具校验与人工确认
    "knowledge_document_management",
    # 单步骤公开网络研究，不创建 TaskPlan
    "web_research",
    # 服务端已绑定 Dataset 的结构化数据 query；真实分流不依赖 Router 模型。
    "structured_data_query",
    # 不调用 Planner 或工具，直接向用户追问
    "clarification_required",
]
# 澄清原因是供 API / SSE / React 稳定消费的机器可读 code，不直接等同于给用户看的问题文本。
AgentClarificationCode = Literal[
    "ambiguous_intent",
    "dataset_query_invalid_intent",
    "router_low_confidence",
    "router_unavailable",
]
# 由调用方提供子 run 配置，使 Router 的模型调用在同一请求 trace 内拥有独立名称。
LangChainConfigFactory = Callable[[str], RunnableConfig]

# Router 不可用或置信度不足时使用的安全兜底问题；避免在意图不明时猜测并执行某种任务。
DEFAULT_CLARIFICATION_QUESTION = (
    "请明确希望进行普通问答、复杂分析、联网检索，还是创建、修改或删除知识库文档。"
)

AGENT_TASK_ROUTER_SYSTEM_PROMPT = """你是 RAG Agent 的任务路由器，只判断用户意图，不回答问题，也不生成执行参数。

可选 intent：
- simple_rag：普通问答、单一事实查询或知识库检索即可回答。
- question_decomposition：需要拆成多个相互关联的子问题后综合回答。
- knowledge_document_management：创建、修改、删除或保存知识库文档。
- web_research：只需一次公开网络检索即可回答的简单 Web 问题，不创建 TaskPlan。
- structured_data_query：一个只需查询已绑定 Dataset 即可回答的结构化数据库问题。
- clarification_required：无法安全判断用户要执行哪类任务，需要追问。

判定边界：
- 解释一个概念、查询一个事实，通常是 simple_rag。
- 明确要求对比两个或更多模块、分析多项关系或综合多个方面时，选择 question_decomposition；
  不要因为最终可以写成一段回答就降为 simple_rag。
- knowledge_document_management 只用于知识库文档、报告或明确 .md/.txt 文件的创建、修改、删除、保存。
  “删除 Redis 缓存”“移除 Docker 容器”“删除数据库记录”不是文档管理。
- web_research 必须有明确 Web 依据且只需单步骤检索。
- 即使全部事实都来自 Web，只要需要多个子问题、比较、依赖或综合，仍选择 question_decomposition。
  不能因为任务不属于现有本地工具，就擅自改判为 web_research。
- 未绑定 Dataset 时不得选择 structured_data_query。
- 用户要求执行不属于上述能力的系统操作，或只说“处理一下”“继续”且上下文不足时，
  选择 clarification_required 并提出具体澄清问题。

示例：
- “FastAPI 是什么？” -> simple_rag
- “对比混合检索与 rerank 的差异和协作关系” -> question_decomposition
- “比较 Milvus 与 Elasticsearch 在混合检索中的职责” -> question_decomposition
- “删除知识库中的旧部署文档” -> knowledge_document_management
- “删除 Redis 测试缓存” -> clarification_required
- “移除本地 Docker 临时容器” -> clarification_required
- “联网搜索 FastAPI 最新部署建议” -> web_research
- “联网比较 PostgreSQL RLS 与 security_invoker，并综合两份官方证据” -> question_decomposition

当前 query 已由 Pipeline 的 Query Rewriter 处理。Router 只根据当前 query 判断意图，
不读取会话历史。若当前 query 仍只有“继续”“处理它”等不完整语义，
选择 clarification_required，不能自行从旧会话猜测对象。
只返回结构化结果，不输出答案、TaskPlan、Tool 参数或文档内容。
"""

DATASET_QUERY_ROUTER_CONTEXT_PROMPT = """

本次请求已经由服务端绑定一个非敏感 Dataset，必须只在以下 intent 中选择：
- structured_data_query：问题只需要一次数据库查询或一次 SQL 聚合即可回答。
- simple_rag：问题只需要一次项目知识库检索即可回答，不需要查询数据库。
- question_decomposition：问题需要多个步骤、多个来源、比较/归纳，或可能组合知识库与数据库事实。
- clarification_required：无法判断用户需要数据库事实、知识库事实还是综合分析。

本次请求不得选择 knowledge_document_management 或 web_research。allow_web_fallback 只是后续
Research Worker 的工具许可，不是顶层 web_research 意图。

示例：
- “查询已授权 3D 模型的名称和费用” -> structured_data_query
- “项目设计文档中的美术风格是什么” -> simple_rag
- “结合设计文档与资产库，分析哪些资产适合当前项目” -> question_decomposition
"""

DATASET_QUERY_ALLOWED_INTENTS = {
    "structured_data_query",
    "simple_rag",
    "question_decomposition",
    "clarification_required",
}


class AgentRouteDecision(BaseModel):
    """Router 模型唯一允许输出的结构。"""

    # 拒绝模型额外输出的字段，并统一去掉字符串两端空白，防止 Router 输出悄悄扩张为计划或参数。
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: AgentRouteIntent = Field(
        description="业务路由结论；只决定后续分支，不授予权限或生成工具参数。"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Router 对 intent 的置信度，后端仍会与配置阈值比较。",
    )
    reason: str = Field(
        min_length=1,
        max_length=200,
        description="支持当前路由结论的简短理由，供 trace 和排查。",
    )
    clarification_question: str | None = Field(
        default=None,
        max_length=300,
        description="仅 clarification_required 时返回的单个用户追问；其他意图为空。",
    )

    @field_validator("clarification_question", mode="before")
    @classmethod
    def normalize_empty_clarification_question(cls, value: object) -> object:
        """把结构化模型常见的空字符串占位统一成未提供。"""

        # Function Calling 模型常会为可选字段返回 ""。它与 JSON null 的业务语义
        # 相同；先归一化后，下面的 model validator 仍会拒绝非澄清意图携带非空追问。
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_clarification(self) -> AgentRouteDecision:
        # 用 schema 强制澄清分支一定有可展示的问题，其他分支则不能混入无意义追问。
        if self.intent == "clarification_required":
            if not self.clarification_question or not self.clarification_question.strip():
                raise ValueError("clarification_required 必须提供 clarification_question")
        elif self.clarification_question is not None:
            raise ValueError("非澄清 intent 不允许提供 clarification_question")
        return self


@dataclass(frozen=True)
class AgentTaskRouteResult:
    """Router 结果"""

    # 经过 schema 校验后的最终意图结论。
    decision: AgentRouteDecision
    # 说明结论来自确定性规则、Router 模型还是安全兜底，便于前端和 trace 区分可信度来源。
    source: Literal["rule", "model", "fallback"]
    # 包含规则或模型调用在内的完整 Router 耗时，单位毫秒。
    latency_ms: float
    # 仅澄清结果需要的稳定原因 code；普通路由保持 None。
    clarification_code: AgentClarificationCode | None = None


class AgentTaskRouter:
    """使用窄规则和独立小模型判断任务类型，不生成任何 TaskPlan。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def route(
        self,
        *,
        query: str,
        langchain_config_factory: LangChainConfigFactory | None = None,
        dataset_query_bound: bool = False,
    ) -> AgentTaskRouteResult:
        started_at = perf_counter()
        # 先处理具有明确语义的低成本规则；命中后不调用模型，结果也更可预测。
        rule_decision = (
            None
            if dataset_query_bound
            else _route_with_high_confidence_rules(query)
        )
        if rule_decision is not None:
            return AgentTaskRouteResult(
                decision=rule_decision,
                source="rule",
                latency_ms=(perf_counter() - started_at) * 1000,
            )

        try:
            # Router 使用独立配置的小模型，只允许按 AgentRouteDecision schema 返回路由事实。
            model = ChatOpenAI(
                model=self._settings.agent_router_model_name,
                api_key=self._settings.agent_router_api_key,
                base_url=self._settings.agent_router_base_url,
                temperature=self._settings.agent_router_temperature,
                timeout=self._settings.agent_router_timeout_seconds,
                max_retries=self._settings.agent_router_max_retries,
                # Qwen3.6 默认开启 thinking，但 DashScope 不允许 thinking 模式与
                # function-calling 的 required tool_choice 同时使用。Router 只做分类，
                # 关闭思考模式还能减少延迟；其他 OpenAI 兼容模型不注入供应商参数。
                **(
                    {"extra_body": {"enable_thinking": False}}
                    if self._settings.agent_router_model_name.lower().startswith("qwen")
                    else {}
                ),
            ).with_structured_output(
                AgentRouteDecision,
                method=self._settings.agent_router_structured_output_method,
            )
            # SDK timeout 之外再包一层 wait_for，即使底层 provider 没有正确结束，也在 Router 配置的超时时间后停止等待
            response = await asyncio.wait_for(
                model.ainvoke(
                    _build_router_messages(
                        query=query,
                        dataset_query_bound=dataset_query_bound,
                    ),
                    config=(
                        langchain_config_factory("task_router.structured")
                        if langchain_config_factory is not None
                        else None
                    ),
                ),
                timeout=self._settings.agent_router_timeout_seconds,
            )

            # 根据模型响应包装接下来的路由决策
            decision = (
                response
                if isinstance(response, AgentRouteDecision)
                # 某些 structured-output provider 返回 dict；同样经过 Pydantic schema 复验。
                else AgentRouteDecision.model_validate(response)
            )
        except Exception as exc:
            # 不确定时安全收口为澄清，Router 无法可靠判断时不退化为任意业务意图，而是要求用户明确下一步。
            logger.warning(
                "agent_task_router %s",
                format_log_fields(
                    event="agent_task_router.unavailable",
                    model=self._settings.agent_router_model_name,
                    error_type=type(exc).__name__,
                ),
            )
            return AgentTaskRouteResult(
                decision=_clarification_decision(
                    reason="router_unavailable",
                    confidence=0.0,
                ),
                source="fallback",
                latency_ms=(perf_counter() - started_at) * 1000,
                clarification_code="router_unavailable",
            )

        if decision.intent == "clarification_required":
            # 模型主动请求澄清是正常路由结果，不视为 Router 故障。
            return AgentTaskRouteResult(
                decision=decision,
                source="model",
                latency_ms=(perf_counter() - started_at) * 1000,
                clarification_code="ambiguous_intent",
            )

        if (
            dataset_query_bound
            and decision.intent not in DATASET_QUERY_ALLOWED_INTENTS
        ):
            return AgentTaskRouteResult(
                decision=_clarification_decision(
                    reason="dataset_query_invalid_intent",
                    confidence=decision.confidence,
                ),
                source="fallback",
                latency_ms=(perf_counter() - started_at) * 1000,
                clarification_code="dataset_query_invalid_intent",
            )

        if decision.confidence < self._settings.agent_router_confidence_threshold:
            # 即使模型给出了具体 intent，低于confidence_threshold 端阈值也不进入执行路径。更改为澄清 要求用户补充上下文，避免误导用户执行错误任务。
            return AgentTaskRouteResult(
                decision=_clarification_decision(
                    reason="router_low_confidence",
                    confidence=decision.confidence,
                ),
                source="fallback",
                latency_ms=(perf_counter() - started_at) * 1000,
                clarification_code="router_low_confidence",
            )

        return AgentTaskRouteResult(
            decision=decision,
            source="model",
            latency_ms=(perf_counter() - started_at) * 1000,
        )


def _build_router_messages(
    *,
    query: str,
    dataset_query_bound: bool = False,
) -> list[SystemMessage | HumanMessage]:
    return [
        SystemMessage(
            content=(
                AGENT_TASK_ROUTER_SYSTEM_PROMPT
                + (
                    DATASET_QUERY_ROUTER_CONTEXT_PROMPT
                    if dataset_query_bound
                    else ""
                )
            )
        ),
        HumanMessage(content=f"当前 query：\n{query}"),
    ]


def _route_with_high_confidence_rules(query: str) -> AgentRouteDecision | None:
    """第一层规则校验，明确语义命中 可以避免直接进入llm 路由增加耗时"""

    # 规则只检查当前 query，绝不把 history 拼进来，避免旧对话意图意外触发新任务。
    text = query.strip()
    # 文件扩展名只是“目标像文档”的强信号；真正进入文档管理还需要同时存在动作词。
    target_path = re.search(r"[A-Za-z0-9_\-./\\]+?\.(?:md|txt)\b", text, re.I)
    document_target = bool(target_path) or any(
        word in text for word in ("知识库", "文档", "文件", "报告")
    )
    document_action = any(
        word in text
        for word in (
            "创建",
            "新增",
            "新建",
            "修改",
            "更新",
            "改写",
            "替换",
            "删除",
            "移除",
            "下线",
            "保存",
            "写入",
        )
    )
    explanatory_question = any(
        word in text for word in ("是什么", "为什么", "如何实现", "原理", "解释", "介绍")
    )
    if document_target and document_action and not explanatory_question:
        # “如何修改文档”等解释型问题仍交给语义 Router；这里仅短路明确的文档操作请求。
        return AgentRouteDecision(
            intent="knowledge_document_management",
            confidence=1.0,
            reason="explicit_document_operation",
        )

    # Web 的简单/复杂边界交给结构化 Router；仅凭“联网”关键词无法判断是否需要 TaskPlan。
    return None


def _clarification_decision(*, reason: str, confidence: float) -> AgentRouteDecision:
    # 统一构造 fallback 澄清结果，确保所有安全收口路径都有同一份可展示问题。
    return AgentRouteDecision(
        intent="clarification_required",
        confidence=confidence,
        reason=reason,
        clarification_question=DEFAULT_CLARIFICATION_QUESTION,
    )


__all__ = [
    "AgentClarificationCode",
    "AgentRouteDecision",
    "AgentRouteIntent",
    "AgentTaskRouteResult",
    "AgentTaskRouter",
]
