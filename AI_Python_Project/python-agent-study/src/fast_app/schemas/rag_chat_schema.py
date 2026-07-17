from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from fast_app.domain.knowledge_permissions import RetrievalPermissionScope
from fast_app.domain.user_context import CurrentUserContext


RetrievalMode = Literal["vector", "keyword", "hybrid"]

# 检索过滤
class RagRetrievalFilters(BaseModel):
    source_path: str | None = Field(default=None, description="限定检索的原始文档路径")
    section_path: list[str] = Field(default_factory=list, description="限定检索的章节路径")

class RagChatRequest(BaseModel):
    # 禁止客户端传入未声明字段
    model_config = ConfigDict(extra="forbid")
    # 当前认证用户 ID 的内部副本；不进入请求体，避免客户端伪造 user_id。
    _current_user_id: str | None = PrivateAttr(default=None)
    # 当前认证用户上下文；由依赖注入层写入，供 RAG Agent 工具权限链路读取。
    _current_user_context: CurrentUserContext | None = PrivateAttr(default=None)
    # 客户端传入的原始 session_id；服务端会再生成带 user_id 的 scoped session_id。
    _external_session_id: str | None = PrivateAttr(default=None)
    # 服务端根据当前用户生成的知识库检索权限范围；客户端不能伪造。
    _retrieval_permission_scope: RetrievalPermissionScope | None = PrivateAttr(
        default=None
    )

    session_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="多轮对话会话 ID；为空时按单轮请求处理",
    )

    # 用户问题
    query: str = Field(
        min_length=1,
        max_length=500,
        description="用户问题",
    )

    # 检索模式
    mode: RetrievalMode = Field(
        default="hybrid",
        description="检索模式：vector / keyword / hybrid",
    )

    # 最多使用多少个文档
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="最多返回文档数量",
    )

    # 最低分数阈值
    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="最低文档分数",
    )

    candidate_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="每个召回源先取多少候选文档；为空时使用 top_k",
    )

    filters: RagRetrievalFilters = Field(
        default_factory=RagRetrievalFilters,
        description="metadata 过滤条件",
    )

    allow_web_fallback: bool = Field(
        default=False,
        description="复杂研究本地证据不足时，是否允许把公开问题发送给 WebSearch。",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()

        if normalized == "":
            raise ValueError("query 不能只包含空白字符")

        return normalized

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if normalized == "":
            raise ValueError("session_id 不能只包含空白字符")

        return normalized

# 不同检索阶段分数拆解
class RagScoreBreakdown(BaseModel):
    vector_score: float | None = Field(default=None, description="Milvus 向量检索原始分数")
    keyword_score: float | None = Field(default=None, description="ElasticSearch 关键词检索原始分数")
    rrf_score: float | None = Field(default=None, description="RRF 融合分数")
    rerank_score: float | None = Field(default=None, description="Rerank 精排分数")

# 检索来源
class RagSource(BaseModel):
    id: str = Field(description="命中的 chunk id")
    source: str = Field(description="检索来源，例如 milvus / elasticsearch")
    retrieval_sources: list[str] = Field(
        default_factory=list,
        description="实际命中过该 chunk 的召回来源列表",
    )
    title: str | None = Field(default=None, description="命中 chunk 所属标题")
    section_path: list[str] = Field(default_factory=list, description="命中 chunk 所属标题路径")
    metadata: dict[str, Any] = Field(default_factory=dict, description="命中 chunk 的结构化 metadata")
    score: float = Field(description="当前最终排序分数")
    scores: RagScoreBreakdown = Field(description="多阶段分数明细")
    content_preview: str = Field(description="命中文档内容预览")
    
# 最终检索结果
class RagChatResponse(BaseModel):
    request_id: str | None = Field(
        default=None,
        description="本次请求的 request_id，用于和后端日志对齐",
    )

    trace_id: str | None = Field(
        default=None,
        description="本次请求的 trace_id，当前阶段默认与 request_id 相同",
    )
    query: str = Field(description="实际用于回答或检索的 query，可能是多轮改写后的问题。")
    answer: str = Field(description="RAG / Agent 生成的最终回答文本。")
    sources: list[RagSource] = Field(
        description="本次回答引用或检索到的来源列表；无检索时为空列表。",
    )
    clarification_required: bool = Field(
        default=False,
        description="Router 是否要求用户补充任务意图。",
    )
    clarification_code: str | None = Field(
        default=None,
        description="澄清原因：ambiguous_intent / router_low_confidence / router_unavailable。",
    )
    clarification_question: str | None = Field(
        default=None,
        description="需要用户回答的澄清问题。",
    )
    route_intent: str | None = Field(
        default=None,
        description="结构化 Router 选择的业务意图。",
    )
    route_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="结构化 Router 的置信度。",
    )
    agent_task_plan_id: str | None = Field(
        default=None,
        description="当 Agent 生成多步骤任务计划时返回的 task_plan_id",
    )
    agent_task_status: str | None = Field(
        default=None,
        description="多步骤任务计划状态；普通 RAG 请求为空",
    )
    agent_task_plan: dict[str, Any] | None = Field(
        default=None,
        description="Agent 多步骤任务计划摘要；普通 RAG 请求为空",
    )
    task_confirmation_required: bool = Field(
        default=False,
        description="TaskPlan 是否等待人工确认后继续执行。",
    )
    task_confirm_endpoint: str | None = Field(
        default=None,
        description="TaskPlan 确认执行接口；无需确认时为空。",
    )


