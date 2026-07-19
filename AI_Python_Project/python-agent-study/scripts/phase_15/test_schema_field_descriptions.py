"""确保 LLM/Tool/OpenAPI 边界的 Pydantic 字段都有可见说明。"""

from pydantic import BaseModel

from fast_app.agents.tools.document_management_tools import KnowledgeDocumentReplacement
from fast_app.api.agent_task_plan_routes import (
    AgentTaskPlanConfirmResponse,
    AgentTaskPlanControlResponse,
)
from fast_app.api.knowledge_import_routes import (
    ExcelFieldProfile,
    ExcelProfileConfirmRequest,
    ExcelProfileResponse,
    ExcelSheetProfile,
    KnowledgeImportJobListResponse,
    KnowledgeImportJobResponse,
)
from fast_app.domain.agent_task_plan import (
    AgentResearchPolicy,
    AgentTaskSubQuestionResult,
    ResearchEvidenceEvaluation,
)
from fast_app.domain.document_workflow import (
    DocumentChangeProposal,
    DocumentDeliverable,
    DocumentDeliverableFailure,
    DocumentDraftResult,
    DocumentResearchResult,
    DocumentReviewResult,
    DocumentWorkflowDecision,
    DocumentWorkflowResult,
)
from fast_app.services.agent_tasks.agent_task_planner import (
    AgentTaskPlannerPayload,
    AgentTaskPlannerSubQuestionPayload,
)
from fast_app.services.agent_tasks.agent_task_router import AgentRouteDecision
from fast_app.services.agent_tasks.deep_document_agent import (
    DocumentReadInput,
    DocumentWebResearchInput,
)
from fast_app.services.conversation.query_rewrite import QueryRewriteResult
from fast_app.services.research.research_tool_loop import (
    AgentTaskKnowledgeRetrievalToolInput,
    AgentTaskToolSelectionPayload,
)


SCHEMA_BOUNDARY_MODELS: tuple[type[BaseModel], ...] = (
    AgentResearchPolicy,
    AgentRouteDecision,
    AgentTaskKnowledgeRetrievalToolInput,
    AgentTaskPlannerPayload,
    AgentTaskPlannerSubQuestionPayload,
    AgentTaskPlanConfirmResponse,
    AgentTaskPlanControlResponse,
    AgentTaskSubQuestionResult,
    AgentTaskToolSelectionPayload,
    DocumentChangeProposal,
    DocumentDeliverable,
    DocumentDeliverableFailure,
    DocumentDraftResult,
    DocumentReadInput,
    DocumentResearchResult,
    DocumentReviewResult,
    DocumentWebResearchInput,
    DocumentWorkflowDecision,
    DocumentWorkflowResult,
    ExcelFieldProfile,
    ExcelProfileConfirmRequest,
    ExcelProfileResponse,
    ExcelSheetProfile,
    KnowledgeDocumentReplacement,
    KnowledgeImportJobListResponse,
    KnowledgeImportJobResponse,
    QueryRewriteResult,
    ResearchEvidenceEvaluation,
)


def main() -> None:
    missing: list[str] = []
    for model in SCHEMA_BOUNDARY_MODELS:
        properties = model.model_json_schema().get("properties", {})
        missing.extend(
            f"{model.__name__}.{field_name}"
            for field_name, field_schema in properties.items()
            if not field_schema.get("description")
        )
    assert not missing, "缺少 Field(description=...): " + ", ".join(missing)
    print("schema_field_descriptions=passed")


if __name__ == "__main__":
    main()
