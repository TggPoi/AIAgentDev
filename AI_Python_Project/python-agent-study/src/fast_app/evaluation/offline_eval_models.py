from dataclasses import dataclass, field

from fast_app.evaluation.generation_eval_models import GenerationDatasetReport
from fast_app.evaluation.retrieval_eval_models import RetrievalDatasetReport
from fast_app.schemas.rag_chat_schema import RagChatResponse


@dataclass(frozen=True)
class OfflineRagEvalCaseOutput:
    """单条评测样例的 pipeline 原始输出。"""

    case_id: str
    response: RagChatResponse


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
    outputs: list[OfflineRagEvalCaseOutput] = field(default_factory=list)
