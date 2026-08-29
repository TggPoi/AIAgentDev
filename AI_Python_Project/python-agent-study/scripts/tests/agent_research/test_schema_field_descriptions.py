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
from fast_app.domain.research_task_plan import (
    AgentTaskDatasetScope,
    AgentTaskEvidencePublicView,
    AgentTaskExpectedEvidence,
    AgentTaskPlannerCandidate,
    AgentTaskPlanReviewDecision,
    AgentTaskRequirement,
    CapabilitySnapshotPublicView,
    RequirementSourcePolicy,
    ResolvedPlanningRequest,
    ResearchTaskPolicy,
    ResearchTaskPlanPublicView,
    ResearchProgressEvent,
    ResearchTaskProgress,
    ResearchTaskSubQuestion,
    ResearchTaskSubQuestionCandidate,
    ResearchTaskSubQuestionResult,
    ResearchWorkerCheckpoint,
    ResearchWorkerCheckpointUpdate,
    ResearchWorkerProgress,
)
from fast_app.evaluation.cases.models import (
    EvalRetrievalFilters,
    ExpectedSource,
    RagEvalCase,
    RagEvalDataset,
    RequiredKeyFact,
)
from fast_app.rag_eval.config import RagEvalJudgeSettings
from fast_app.rag_eval.models import (
    GenerationEvaluationRequest,
    GenerationEvaluationResponse,
    RagEvalCaseReport,
    RagEvalError,
    RagEvalMetricResult,
    RagEvalMetricSummary,
    RagEvalRunReport,
    RetrievalMetricEvaluation,
)
from fast_app.rag_eval.streaming import RagEvalStreamEvent, RagStreamExecutionResult
from fast_app.rag_eval.target import RagEvalAuth
from fast_app.services.agent_tasks.agent_task_router import AgentRouteDecision
from fast_app.services.agent_tasks.deep_document_agent import (
    DocumentNl2SqlInput,
    DocumentReadInput,
    DocumentWebResearchInput,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse
from fast_app.schemas.rag_stream_schema import (
    RagAnswerDeltaEventData,
    RagDoneEventData,
    RagErrorEventData,
    RagGuardEventData,
    RagSourcesEventData,
    RagSseEventFrame,
)
from fast_app.schemas.agent_task_plan_schema import (
    AgentTaskPlanListItem,
    AgentTaskPlanListResponse,
)
from fast_app.schemas.agent_task_plan_stream_schema import (
    TaskPlanAnswerDeltaData,
    TaskPlanAnswerDeltaFrame,
    TaskPlanDocumentProgressData,
    TaskPlanDocumentProgressFrame,
    TaskPlanDoneData,
    TaskPlanDoneFrame,
    TaskPlanErrorData,
    TaskPlanErrorFrame,
    TaskPlanEventData,
    TaskPlanExecutionStartedData,
    TaskPlanExecutionStartedFrame,
    TaskPlanFinalSynthesisData,
    TaskPlanFinalSynthesisFrame,
    TaskPlanGuardData,
    TaskPlanGuardFrame,
    TaskPlanRequirementProgressData,
    TaskPlanRequirementProgressFrame,
    TaskPlanResearchProgressData,
    TaskPlanResearchProgressFrame,
    TaskPlanSourcesData,
    TaskPlanSourcesFrame,
    TaskPlanStatusData,
    TaskPlanStatusFrame,
    TaskPlanStepData,
    TaskPlanStepFrame,
    TaskPlanSubQuestionCompletedData,
    TaskPlanSubQuestionCompletedFrame,
)
from fast_app.schemas.auth_schema import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    CurrentUserResponse,
    LogoutRequest,
    LogoutResponse,
    UserCapabilitiesResponse,
)
from fast_app.schemas.document_access_schema import (
    CreateDocumentAccessGrantsRequest,
    CreateDocumentAccessGrantsResponse,
    DocumentAccessGrantItem,
    DocumentAccessGrantListResponse,
    DocumentAccessGrantUser,
)
from fast_app.schemas.error_schema import (
    RequestValidationErrorResponse,
    RequestValidationFieldError,
)
from fast_app.schemas.conversation_schema import (
    ConversationItem,
    ConversationListResponse,
    ConversationMessageItem,
    ConversationMessageListResponse,
    CreateConversationRequest,
    UpdateConversationRequest,
)
from fast_app.schemas.knowledge_document_schema import (
    KnowledgeDocumentContentResponse,
    KnowledgeDocumentDetail,
    KnowledgeDocumentItem,
    KnowledgeDocumentListResponse,
)
from fast_app.schemas.user_admin_schema import (
    AccessCatalogItem,
    AccessCatalogResponse,
    CreateManagedUserRequest,
    ManagedDepartmentAccess,
    ManagedDepartmentAccessInput,
    ManagedUserDetail,
    ManagedUserListResponse,
    ManagedUserPasswordResetResponse,
    ManagedUserStatusResponse,
    ManagedUserSummary,
    ReplaceManagedUserAccessRequest,
    ResetManagedUserPasswordRequest,
    UpdateManagedUserStatusRequest,
)
from fast_app.services.nl2sql.models import (
    Nl2SqlDatasetItem,
    Nl2SqlQueryRequest,
    Nl2SqlQueryResult,
    SqlGenerationResult,
)
from fast_app.services.conversation.query_rewrite import QueryResolutionDecision, QueryRewriteResult
from fast_app.services.research.research_tool_loop import (
    AgentTaskKnowledgeRetrievalToolInput,
    AgentTaskToolSelectionPayload,
)
from fast_app.services.rag.direct_web_search_planner import (
    DirectWebCandidateSelection,
    DirectWebSearchPlan,
)


SCHEMA_BOUNDARY_MODELS: tuple[type[BaseModel], ...] = (
    AccessCatalogItem,
    AccessCatalogResponse,
    AgentResearchPolicy,
    AgentRouteDecision,
    AgentTaskDatasetScope,
    AgentTaskKnowledgeRetrievalToolInput,
    AgentTaskEvidencePublicView,
    AgentTaskExpectedEvidence,
    AgentTaskPlannerCandidate,
    AgentTaskPlanReviewDecision,
    AgentTaskRequirement,
    AgentTaskPlanConfirmResponse,
    AgentTaskPlanControlResponse,
    AgentTaskPlanListItem,
    AgentTaskPlanListResponse,
    TaskPlanEventData,
    TaskPlanExecutionStartedData,
    TaskPlanStatusData,
    TaskPlanResearchProgressData,
    TaskPlanSubQuestionCompletedData,
    TaskPlanRequirementProgressData,
    TaskPlanDocumentProgressData,
    TaskPlanStepData,
    TaskPlanFinalSynthesisData,
    TaskPlanSourcesData,
    TaskPlanAnswerDeltaData,
    TaskPlanGuardData,
    TaskPlanDoneData,
    TaskPlanErrorData,
    TaskPlanExecutionStartedFrame,
    TaskPlanStatusFrame,
    TaskPlanResearchProgressFrame,
    TaskPlanSubQuestionCompletedFrame,
    TaskPlanRequirementProgressFrame,
    TaskPlanDocumentProgressFrame,
    TaskPlanStepFrame,
    TaskPlanFinalSynthesisFrame,
    TaskPlanSourcesFrame,
    TaskPlanAnswerDeltaFrame,
    TaskPlanGuardFrame,
    TaskPlanDoneFrame,
    TaskPlanErrorFrame,
    AgentTaskSubQuestionResult,
    AgentTaskToolSelectionPayload,
    DocumentChangeProposal,
    DocumentDeliverable,
    DocumentDeliverableFailure,
    DocumentDraftResult,
    DocumentNl2SqlInput,
    DocumentReadInput,
    DocumentResearchResult,
    DocumentReviewResult,
    DocumentWebResearchInput,
    DocumentWorkflowDecision,
    DocumentWorkflowResult,
    DirectWebCandidateSelection,
    DirectWebSearchPlan,
    ExcelFieldProfile,
    ExcelProfileConfirmRequest,
    ExcelProfileResponse,
    ExcelSheetProfile,
    EvalRetrievalFilters,
    ExpectedSource,
    KnowledgeDocumentReplacement,
    KnowledgeDocumentContentResponse,
    KnowledgeDocumentDetail,
    KnowledgeDocumentItem,
    KnowledgeDocumentListResponse,
    KnowledgeImportJobListResponse,
    KnowledgeImportJobResponse,
    CreateDocumentAccessGrantsRequest,
    CreateDocumentAccessGrantsResponse,
    ConversationItem,
    ConversationListResponse,
    ConversationMessageItem,
    ConversationMessageListResponse,
    CreateConversationRequest,
    CreateManagedUserRequest,
    DocumentAccessGrantItem,
    DocumentAccessGrantListResponse,
    DocumentAccessGrantUser,
    ManagedDepartmentAccess,
    ManagedDepartmentAccessInput,
    ManagedUserDetail,
    ManagedUserListResponse,
    ManagedUserPasswordResetResponse,
    ManagedUserStatusResponse,
    ManagedUserSummary,
    ReplaceManagedUserAccessRequest,
    ResetManagedUserPasswordRequest,
    QueryRewriteResult,
    QueryResolutionDecision,
    RagEvalCase,
    RagEvalDataset,
    RagEvalJudgeSettings,
    RagEvalAuth,
    RagEvalError,
    RagEvalMetricResult,
    RetrievalMetricEvaluation,
    GenerationEvaluationRequest,
    GenerationEvaluationResponse,
    RagEvalCaseReport,
    RagEvalMetricSummary,
    RagEvalRunReport,
    RagEvalStreamEvent,
    RagStreamExecutionResult,
    RagChatRequest,
    RagChatResponse,
    RagAnswerDeltaEventData,
    RagDoneEventData,
    RagErrorEventData,
    RagGuardEventData,
    RagSourcesEventData,
    RagSseEventFrame,
    ResearchEvidenceEvaluation,
    Nl2SqlDatasetItem,
    Nl2SqlQueryRequest,
    Nl2SqlQueryResult,
    SqlGenerationResult,
    CapabilitySnapshotPublicView,
    ChangePasswordRequest,
    ChangePasswordResponse,
    CurrentUserResponse,
    LogoutRequest,
    LogoutResponse,
    RequirementSourcePolicy,
    ResolvedPlanningRequest,
    ResearchTaskPolicy,
    ResearchTaskPlanPublicView,
    ResearchProgressEvent,
    ResearchTaskProgress,
    ResearchTaskSubQuestion,
    ResearchTaskSubQuestionCandidate,
    ResearchTaskSubQuestionResult,
    ResearchWorkerCheckpoint,
    ResearchWorkerCheckpointUpdate,
    ResearchWorkerProgress,
    RequiredKeyFact,
    RequestValidationErrorResponse,
    RequestValidationFieldError,
    UserCapabilitiesResponse,
    UpdateManagedUserStatusRequest,
    UpdateConversationRequest,
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
