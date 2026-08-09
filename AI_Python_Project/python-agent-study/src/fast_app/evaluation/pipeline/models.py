from dataclasses import dataclass, field
from typing import Literal

from fast_app.evaluation.contracts import get_metric_versions
from fast_app.evaluation.generation.models import GenerationDatasetReport
from fast_app.evaluation.retrieval.models import RetrievalDatasetReport, RetrievalStage
from fast_app.schemas.rag_chat_schema import RagChatResponse


EvaluationCaseStatus = Literal["evaluated", "partial", "skipped", "failed"]
EvaluationRunStatus = Literal[
    "pending",
    "running",
    "partial",
    "completed",
    "failed",
    "cancelled",
]
EvaluationSnapshotSecurityMode = Literal["plain", "redacted", "encrypted"]
EvaluationSnapshotStageStatus = Literal[
    "not_executed",
    "captured",
    "error",
]


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


@dataclass(frozen=True)
class EvaluationError:
    """一次 case 执行或评测失败的稳定错误记录。"""

    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("evaluation error code 不能为空")
        if not self.message.strip():
            raise ValueError("evaluation error message 不能为空")


@dataclass(frozen=True)
class SnapshotValue:
    """一个带完整性哈希的明文、脱敏或密文值。"""

    storage: EvaluationSnapshotSecurityMode
    sha256: str
    is_null: bool = False
    plaintext: str | None = None
    ciphertext: str | None = None
    nonce: str | None = None
    key_id: str | None = None

    def __post_init__(self) -> None:
        if not _is_sha256(self.sha256):
            raise ValueError("snapshot value sha256 必须是 64 位十六进制")
        encrypted_fields = (self.ciphertext, self.nonce, self.key_id)
        has_encrypted_value = all(
            value is not None and value.strip() for value in encrypted_fields
        )
        if self.is_null and (
            self.plaintext is not None
            or any(value is not None for value in encrypted_fields)
        ):
            raise ValueError("null snapshot value 不能保存明文或密文字段")
        if self.storage == "plain":
            if not self.is_null and self.plaintext is None:
                raise ValueError("plain snapshot value 必须保存明文")
            if any(value is not None for value in encrypted_fields):
                raise ValueError("plain snapshot value 不能保存密文字段")
        elif self.storage == "redacted":
            if self.plaintext is not None or any(
                value is not None for value in encrypted_fields
            ):
                raise ValueError("redacted snapshot value 只能保存哈希")
        elif not self.is_null and not has_encrypted_value:
            raise ValueError("encrypted snapshot value 必须提供密文、nonce 和 key_id")
        if self.storage == "encrypted" and self.plaintext is not None:
            raise ValueError("encrypted snapshot value 不能保存明文")


@dataclass(frozen=True)
class SnapshotMapping:
    """一个带完整性哈希的结构化映射快照。"""

    storage: EvaluationSnapshotSecurityMode
    sha256: str
    plaintext: dict[str, object] | None = None
    ciphertext: str | None = None
    nonce: str | None = None
    key_id: str | None = None

    def __post_init__(self) -> None:
        if not _is_sha256(self.sha256):
            raise ValueError("snapshot mapping sha256 必须是 64 位十六进制")
        encrypted_fields = (self.ciphertext, self.nonce, self.key_id)
        has_encrypted_value = all(
            value is not None and value.strip() for value in encrypted_fields
        )
        if self.storage == "plain":
            if self.plaintext is None:
                raise ValueError("plain snapshot mapping 必须保存明文")
            if any(value is not None for value in encrypted_fields):
                raise ValueError("plain snapshot mapping 不能保存密文字段")
        elif self.storage == "redacted":
            if self.plaintext is not None or any(
                value is not None for value in encrypted_fields
            ):
                raise ValueError("redacted snapshot mapping 只能保存哈希")
        elif not has_encrypted_value:
            raise ValueError("encrypted snapshot mapping 必须提供密文、nonce 和 key_id")
        if self.storage == "encrypted" and self.plaintext is not None:
            raise ValueError("encrypted snapshot mapping 不能保存明文")


@dataclass(frozen=True)
class SnapshotScoreBreakdown:
    """冻结某个检索阶段文档的全部已知分数。"""

    score: float
    vector_score: float | None = None
    keyword_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


@dataclass(frozen=True)
class SnapshotDocument:
    """按当时顺序冻结的一个检索或最终上下文文档。"""

    rank: int
    id: str
    source: str
    content: SnapshotValue
    metadata: SnapshotMapping
    scores: SnapshotScoreBreakdown
    title: SnapshotValue | None = None
    doc_id: str | None = None
    logical_chunk_id: str | None = None
    logical_parent_id: str | None = None
    parent_id: str | None = None
    source_revision: str | None = None
    retrieval_sources: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("snapshot document rank 必须大于等于 1")
        if not self.id.strip():
            raise ValueError("snapshot document id 不能为空")
        if not self.source.strip():
            raise ValueError("snapshot document source 不能为空")


@dataclass(frozen=True)
class SnapshotRetrievalStage:
    """vector、keyword、RRF 或 rerank 的有序结果快照。"""

    name: RetrievalStage
    status: EvaluationSnapshotStageStatus
    documents: list[SnapshotDocument] = field(default_factory=list)
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.status == "error" and not (
            self.error_code and self.error_code.strip()
        ):
            raise ValueError("error retrieval stage 必须提供 error_code")
        if self.status != "error" and self.error_code is not None:
            raise ValueError("非 error retrieval stage 不能携带 error_code")
        if self.status == "not_executed" and self.documents:
            raise ValueError("not_executed retrieval stage 不能携带 documents")


@dataclass(frozen=True)
class SnapshotContext:
    """模型实际收到的完整最终 RagContext。"""

    query: SnapshotValue
    context_text: SnapshotValue
    documents: list[SnapshotDocument] = field(default_factory=list)


@dataclass(frozen=True)
class SnapshotRequest:
    """影响本次被测 RAG 行为的请求参数快照。"""

    mode: str
    top_k: int
    candidate_k: int
    min_score: float
    filters: SnapshotMapping

    def __post_init__(self) -> None:
        if self.top_k < 1 or self.candidate_k < self.top_k:
            raise ValueError("snapshot request 必须满足 candidate_k >= top_k >= 1")


@dataclass(frozen=True)
class SnapshotPrincipal:
    """服务端绑定的评测身份及 ACL 快照。"""

    eval_principal_id: SnapshotValue
    permission_scope: SnapshotMapping


@dataclass(frozen=True)
class SnapshotTargetIdentity:
    """被测 Pipeline 和检索、排序、生成配置身份。"""

    pipeline_provider: str
    vector_retriever: str
    keyword_retriever: str
    reranker: str
    generator: str

    def __post_init__(self) -> None:
        values = (
            self.pipeline_provider,
            self.vector_retriever,
            self.keyword_retriever,
            self.reranker,
            self.generator,
        )
        if any(not value.strip() for value in values):
            raise ValueError("snapshot target identity 字段不能为空")


@dataclass(frozen=True)
class EvaluationSnapshotPayload:
    """无需再次调用被测 Pipeline 即可重算指标的冻结数据。"""

    raw_query: SnapshotValue
    effective_query: SnapshotValue
    request: SnapshotRequest
    principal: SnapshotPrincipal
    knowledge_version: int | None
    source_revisions: list[str]
    target: SnapshotTargetIdentity
    retrieval_stages: dict[RetrievalStage, SnapshotRetrievalStage]
    final_context: SnapshotContext | None
    answer: SnapshotValue
    source_ids: list[str]
    prompt_version: str
    metric_versions: dict[str, str]
    request_id: str | None
    trace_id: str | None
    latency_ms: float
    error: EvaluationError | None = None

    def __post_init__(self) -> None:
        if self.latency_ms < 0:
            raise ValueError("evaluation snapshot latency_ms 不能为负数")
        if not self.prompt_version.strip():
            raise ValueError("evaluation snapshot prompt_version 不能为空")


@dataclass(frozen=True)
class EvaluationSnapshot:
    """版本化、安全模式明确且可校验完整性的评测快照。"""

    snapshot_id: str
    snapshot_version: str
    captured_at: str
    security_mode: EvaluationSnapshotSecurityMode
    content_replayable: bool
    payload_hash: str
    payload: EvaluationSnapshotPayload

    def __post_init__(self) -> None:
        if not self.snapshot_id.strip():
            raise ValueError("evaluation snapshot_id 不能为空")
        if not self.snapshot_version.strip():
            raise ValueError("evaluation snapshot_version 不能为空")
        if not _is_sha256(self.payload_hash):
            raise ValueError("evaluation snapshot payload_hash 必须是 64 位十六进制")
        if self.content_replayable != (self.security_mode != "redacted"):
            raise ValueError("只有 plain 或 encrypted snapshot 可以重放内容指标")


@dataclass(frozen=True)
class EvaluationContractVersions:
    """保证历史报告可解释和可重放的契约版本快照。"""

    dataset_version: str = "legacy.v1"
    metric_versions: dict[str, str] = field(default_factory=get_metric_versions)
    threshold_profile_version: str | None = None
    judge_version: str | None = None

    def __post_init__(self) -> None:
        if not self.dataset_version.strip():
            raise ValueError("evaluation dataset_version 不能为空")
        if any(
            not name.strip() or not version.strip()
            for name, version in self.metric_versions.items()
        ):
            raise ValueError("evaluation metric_versions 的名称和版本不能为空")
        if (
            self.threshold_profile_version is not None
            and not self.threshold_profile_version.strip()
        ):
            raise ValueError("threshold_profile_version 提供后不能为空")
        if self.judge_version is not None and not self.judge_version.strip():
            raise ValueError("judge_version 提供后不能为空")


@dataclass(frozen=True)
class OfflineRagEvalCaseOutput:
    """单条评测样例的 pipeline 原始输出。"""

    case_id: str
    response: RagChatResponse | None
    status: EvaluationCaseStatus = "evaluated"
    case_hard_failure: bool = False
    reason: str | None = None
    errors: list[EvaluationError] = field(default_factory=list)
    snapshot: EvaluationSnapshot | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("offline eval output case_id 不能为空")
        if self.status not in {"evaluated", "partial", "skipped", "failed"}:
            raise ValueError(f"未知 evaluation case status: {self.status}")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("evaluation case reason 提供后不能为空")
        if self.status == "evaluated" and self.response is None:
            raise ValueError("evaluated case 必须携带 response")
        if self.status == "evaluated" and self.errors:
            raise ValueError("evaluated case 不能携带 errors")
        if self.status == "skipped" and self.reason is None:
            raise ValueError("skipped case 必须提供 reason")
        if self.status == "failed" and not self.errors:
            raise ValueError("failed case 必须携带至少一个 error")
        if self.status in {"skipped", "failed"} and self.case_hard_failure:
            raise ValueError("skipped 或 failed case 不能标记指标硬失败")


@dataclass(frozen=True)
class OfflineRagEvalReport:
    """一次完整离线 RAG 评测的总报告。

    它把三类信息放在一起：
    - pipeline 原始 responses
    - 基于 sources 的检索评测报告
    - 基于 answer 的生成评测报告
    """

    dataset_name: str
    case_count: int
    response_count: int
    retrieval_report: RetrievalDatasetReport
    generation_report: GenerationDatasetReport
    status: EvaluationRunStatus = "completed"
    outputs: list[OfflineRagEvalCaseOutput] = field(default_factory=list)
    contract_versions: EvaluationContractVersions = field(
        default_factory=EvaluationContractVersions
    )
    errors: list[EvaluationError] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.dataset_name.strip():
            raise ValueError("offline eval dataset_name 不能为空")
        if self.status not in {
            "pending",
            "running",
            "partial",
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError(f"未知 evaluation run status: {self.status}")
        if self.status == "failed" and not self.errors:
            raise ValueError("failed eval run 必须携带至少一个 error")
