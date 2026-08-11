"""轻量 RAG Eval 的稳定输出模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RagEvalMetricName = Literal[
    "retrieval_recall_at_k",
    "retrieval_precision_at_k",
    "retrieval_hit_rate_at_k",
    "retrieval_mrr",
    "generation_faithfulness",
    "generation_answer_relevance",
    "generation_answer_completeness",
    "generation_context_utilization",
]
RagEvalMetricStatus = Literal["evaluated", "skipped", "error"]
RagEvalCaseStatus = Literal["evaluated", "skipped", "failed"]
RagEvalRunStatus = Literal["completed", "partial", "failed"]


class RagEvalError(BaseModel):
    """轻量 Eval 的稳定错误。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, description="供脚本和报告稳定识别的错误码。")
    message: str = Field(min_length=1, description="不包含密钥或完整上下文的错误说明。")
    retryable: bool = Field(
        default=False,
        description="该错误是否可在不改变输入的情况下安全重试。",
    )


class RagEvalMetricResult(BaseModel):
    """八项指标共用的简化标量结果。"""

    model_config = ConfigDict(extra="forbid")

    metric_name: RagEvalMetricName = Field(description="指标的稳定机器名。")
    score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="0 到 1 的指标分数；跳过或错误时为空。",
    )
    threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="本次判定使用的通过阈值；未评测时为空。",
    )
    passed: bool | None = Field(
        default=None,
        description="分数是否达到阈值；未评测时为空。",
    )
    status: RagEvalMetricStatus = Field(description="evaluated、skipped 或 error。")
    short_reason: str = Field(
        min_length=1,
        description="不依赖长 Judge 解释的简短判定说明。",
    )
    error: RagEvalError | None = Field(
        default=None,
        description="指标执行失败的结构化错误；正常或跳过时为空。",
    )

    @model_validator(mode="after")
    def validate_status_fields(self) -> "RagEvalMetricResult":
        evaluated = self.status == "evaluated"
        if evaluated and (
            self.score is None or self.threshold is None or self.passed is None
        ):
            raise ValueError("evaluated metric 必须提供 score、threshold 和 passed")
        if not evaluated and any(
            value is not None for value in (self.score, self.threshold, self.passed)
        ):
            raise ValueError("skipped/error metric 不能提供 score、threshold 或 passed")
        if (self.status == "error") != (self.error is not None):
            raise ValueError("只有 error metric 可以携带 error")
        return self


class RetrievalMetricEvaluation(BaseModel):
    """单条 case 的四个检索指标和诊断信息。"""

    model_config = ConfigDict(extra="forbid")

    requested_k: int = Field(ge=1, description="该 case 请求并计算指标使用的 K。")
    returned_count: int = Field(
        ge=0,
        description="Top K 内去重后的实际返回逻辑 Chunk 数。",
    )
    underfilled: bool = Field(description="实际返回数量是否少于 K。")
    relevant_retrieved_count: int = Field(
        ge=0,
        description="Top K 内命中的黄金相关逻辑 Chunk 数。",
    )
    gold_relevant_count: int = Field(
        ge=0,
        description="该 case 人工审核的黄金相关逻辑 Chunk 总数。",
    )
    first_relevant_rank: int | None = Field(
        default=None,
        ge=1,
        description="首个相关逻辑 Chunk 的去重后排名；未命中时为空。",
    )
    matched_logical_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Top K 中命中的黄金相关逻辑 Chunk ID。",
    )
    false_positive_logical_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Top K 中未被标注为相关的逻辑 Chunk ID。",
    )
    metrics: dict[RagEvalMetricName, RagEvalMetricResult] = Field(
        description="以稳定机器名索引的四个检索指标。",
    )


class GenerationEvaluationRequest(BaseModel):
    """发送到隔离 DeepEval Worker 的单 case 输入。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, description="当前黄金 case 的稳定 ID。")
    question: str = Field(min_length=1, description="用户原始问题。")
    answer: str = Field(description="真实结构化流聚合出的最终安全答案。")
    retrieval_context: list[str] = Field(
        default_factory=list,
        description="模型实际使用的完整最终 RagContext；通常以一个原样文本元素传给 DeepEval。",
    )
    required_key_facts: list[str] = Field(
        default_factory=list,
        description="Golden V2 required_key_facts 的事实文本，用于完整性 Judge。",
    )
    metrics: list[RagEvalMetricName] = Field(
        description="本次需要 Worker 计算的生成指标机器名。",
    )
    thresholds: dict[RagEvalMetricName, float] = Field(
        default_factory=dict,
        description="按指标机器名覆盖的 0 到 1 通过阈值。",
    )
    include_judge_reason: bool = Field(
        default=False,
        description="是否把 Judge 的诊断理由写入 short_reason。",
    )

    @model_validator(mode="after")
    def validate_generation_metrics(self) -> "GenerationEvaluationRequest":
        invalid = [name for name in self.metrics if not name.startswith("generation_")]
        if invalid:
            raise ValueError(f"生成 Worker 不能执行检索指标: {invalid}")
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("生成指标不能重复")
        invalid_thresholds = [
            name
            for name, value in self.thresholds.items()
            if not name.startswith("generation_") or not 0.0 <= value <= 1.0
        ]
        if invalid_thresholds:
            raise ValueError(f"生成指标阈值名称或范围非法: {invalid_thresholds}")
        return self


class GenerationEvaluationResponse(BaseModel):
    """隔离 DeepEval Worker 返回的单 case 结果。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, description="与请求一致的黄金 case ID。")
    judge_model: str | None = Field(
        default=None,
        description="实际使用的独立 Judge 模型名；配置失败时为空。",
    )
    metrics: dict[RagEvalMetricName, RagEvalMetricResult] = Field(
        default_factory=dict,
        description="按机器名索引且单项失败隔离的生成指标。",
    )

    @model_validator(mode="after")
    def validate_metric_keys(self) -> "GenerationEvaluationResponse":
        if any(name != result.metric_name for name, result in self.metrics.items()):
            raise ValueError("生成指标 dict key 必须等于结果 metric_name")
        return self


class RagEvalCaseReport(BaseModel):
    """稳定 JSON/Markdown 报告中的单 case 结果。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, description="黄金 case 的稳定 ID。")
    status: RagEvalCaseStatus = Field(description="evaluated、skipped 或 failed。")
    answerable: bool = Field(description="Golden 是否声明当前身份可回答。")
    expected_route: str = Field(description="Golden 期望的普通 RAG 路由。")
    actual_route: str | None = Field(
        default=None,
        description="结构化 SSE 返回的实际 Router 意图；非 RagAgent 可为空。",
    )
    knowledge_retrieval_performed: bool = Field(
        description="快照是否证明确实执行过检索阶段。",
    )
    request_id: str | None = Field(default=None, description="真实请求 ID。")
    trace_id: str | None = Field(default=None, description="真实追踪 ID。")
    knowledge_version: int | None = Field(
        default=None,
        ge=0,
        description="实际流或快照记录的知识版本。",
    )
    snapshot_id: str | None = Field(
        default=None,
        min_length=1,
        description="冻结评测快照 ID；未执行目标的 skipped case 为空。",
    )
    snapshot_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="冻结评测快照 payload 的 SHA-256；skipped case 为空。",
    )
    latency_ms: float = Field(ge=0, description="case 真实流式执行耗时毫秒。")
    metrics: dict[RagEvalMetricName, RagEvalMetricResult] = Field(
        default_factory=dict,
        description="该 case 已选择的八项指标结果。",
    )
    error: RagEvalError | None = Field(
        default=None,
        description="case 路由或流执行失败；成功和跳过时为空。",
    )
    skipped_reason: str | None = Field(
        default=None,
        description="仅 skipped case 的稳定跳过原因。",
    )

    @model_validator(mode="after")
    def validate_case_status(self) -> "RagEvalCaseReport":
        if any(name != result.metric_name for name, result in self.metrics.items()):
            raise ValueError("case metric dict key 必须等于结果 metric_name")
        if self.status == "skipped":
            if not self.skipped_reason:
                raise ValueError("skipped case 必须提供 skipped_reason")
            if self.error is not None:
                raise ValueError("skipped case 不能携带 error")
        else:
            if self.snapshot_id is None or self.snapshot_hash is None:
                raise ValueError("已执行 case 必须携带 snapshot_id 和 snapshot_hash")
            if (self.status == "failed") != (self.error is not None):
                raise ValueError("只有 failed case 必须携带 case error")
        return self


class RagEvalMetricSummary(BaseModel):
    """数据集级指标宏平均和计数。"""

    model_config = ConfigDict(extra="forbid")

    metric_name: RagEvalMetricName = Field(description="指标稳定机器名。")
    mean_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="只对 evaluated case 求宏平均；没有分数时为空。",
    )
    evaluated_count: int = Field(ge=0, description="参与宏平均的 case 数。")
    passed_count: int = Field(ge=0, description="达到单项阈值的 case 数。")
    skipped_count: int = Field(ge=0, description="该指标不适用的 case 数。")
    error_count: int = Field(ge=0, description="该指标执行失败的 case 数。")
    baseline_delta: float | None = Field(
        default=None,
        ge=-1,
        le=1,
        description="相对基线宏平均变化；未提供或基线无分数时为空。",
    )


class RagEvalRunReport(BaseModel):
    """一次 provider 真实流式轻量评测的稳定报告。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = Field(description="轻量报告 Schema 版本。")
    run_id: str = Field(min_length=1, description="本次运行的唯一 ID。")
    created_at: datetime = Field(description="带时区的报告生成时间。")
    status: RagEvalRunStatus = Field(description="completed、partial 或 failed。")
    pipeline_provider: Literal["classic", "langgraph", "rag_agent"] = Field(
        description="本次唯一选择的真实 Pipeline provider。",
    )
    mode: Literal["retrieval", "generation", "all"] = Field(
        description="本次执行的指标层。",
    )
    dataset_id: str = Field(min_length=1, description="Golden 数据集稳定 ID。")
    dataset_version: str = Field(min_length=1, description="Golden 数据集版本。")
    dataset_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Golden 数据集规范化内容哈希。",
    )
    source_revision: str = Field(min_length=1, description="被测知识源 revision。")
    tested_model: str = Field(min_length=1, description="被测生成器模型身份。")
    judge_model: str | None = Field(
        default=None,
        description="生成层使用的独立 Judge 模型；纯检索运行时为空。",
    )
    selected_metrics: list[RagEvalMetricName] = Field(
        description="本次按 CLI 选择的指标机器名。",
    )
    case_count: int = Field(ge=0, description="本次选中的 Golden case 数。")
    evaluated_case_count: int = Field(ge=0, description="成功进入评测的 case 数。")
    failed_case_count: int = Field(ge=0, description="路由或执行失败的 case 数。")
    skipped_case_count: int = Field(ge=0, description="非 RAG profile 跳过的 case 数。")
    duration_ms: float = Field(ge=0, description="整次评测墙钟耗时毫秒。")
    metric_summaries: dict[RagEvalMetricName, RagEvalMetricSummary] = Field(
        default_factory=dict,
        description="八项指标的数据集级宏平均与计数。",
    )
    cases: list[RagEvalCaseReport] = Field(description="按输入顺序保存的 case 报告。")
    baseline_report: str | None = Field(
        default=None,
        description="用于计算变化量的基线报告路径；未比较时为空。",
    )

    @model_validator(mode="after")
    def validate_report_consistency(self) -> "RagEvalRunReport":
        if self.created_at.utcoffset() is None:
            raise ValueError("报告 created_at 必须包含时区")
        if len(self.cases) != self.case_count:
            raise ValueError("报告 case_count 必须等于 cases 数量")
        if (
            self.evaluated_case_count
            + self.failed_case_count
            + self.skipped_case_count
            != self.case_count
        ):
            raise ValueError("报告 case 状态计数之和必须等于 case_count")
        if not self.selected_metrics or len(set(self.selected_metrics)) != len(
            self.selected_metrics
        ):
            raise ValueError("报告 selected_metrics 必须非空且唯一")
        if set(self.metric_summaries) != set(self.selected_metrics):
            raise ValueError("报告 metric_summaries 必须覆盖全部 selected_metrics")
        if any(
            name != summary.metric_name
            for name, summary in self.metric_summaries.items()
        ):
            raise ValueError("报告 summary key 必须等于 metric_name")
        return self


__all__ = [
    "RagEvalError",
    "RagEvalCaseReport",
    "RagEvalCaseStatus",
    "RagEvalMetricName",
    "RagEvalMetricResult",
    "RagEvalMetricStatus",
    "RagEvalMetricSummary",
    "RagEvalRunReport",
    "RagEvalRunStatus",
    "GenerationEvaluationRequest",
    "GenerationEvaluationResponse",
    "RetrievalMetricEvaluation",
]
