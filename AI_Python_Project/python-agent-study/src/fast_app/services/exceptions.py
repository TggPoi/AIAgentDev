class AppServiceError(Exception):
    """业务异常基类。"""

    error_code = "APP_SERVICE_ERROR"
    error_category = "user_error"
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.public_message = message


class DocumentNotFoundError(AppServiceError):
    """文档不存在。"""

    error_code = "DOCUMENT_NOT_FOUND"
    status_code = 404


class NoSearchResultError(AppServiceError):
    """检索结果为空。"""

    error_code = "NO_SEARCH_RESULT"
    status_code = 404


class AuthenticationError(AppServiceError):
    """认证失败。"""

    error_code = "AUTHENTICATION_FAILED"
    status_code = 401


class PromptInjectionBlockedError(AppServiceError):
    """Prompt Injection 或敏感信息窃取请求被安全策略拦截。"""

    error_code = "PROMPT_INJECTION_BLOCKED"
    status_code = 400


class ToolExecutionRequiresConfirmationError(AppServiceError):
    """高风险 Agent 工具执行需要权限网关或 TaskPlan 人工确认。"""

    error_code = "TOOL_EXECUTION_REQUIRES_CONFIRMATION"
    status_code = 403


class ToolPermissionDeniedError(AppServiceError):
    """当前用户没有调用目标 Agent 工具的权限。"""

    error_code = "TOOL_PERMISSION_DENIED"
    status_code = 403


class AgentTaskPlanBusyError(AppServiceError):
    """同一 TaskPlan 已被当前进程中的另一个控制请求占用。"""

    error_code = "AGENT_TASK_PLAN_BUSY"
    status_code = 409


class KnowledgeVersionNotReadyError(AppServiceError):
    """客户端要求的最低正式知识版本尚未发布。"""

    error_code = "KNOWLEDGE_VERSION_NOT_READY"
    status_code = 409


class DocumentAgentCheckpointConflictError(AppServiceError):
    """Deep Agent 运行记录版本与调用方期望不一致。"""

    error_code = "DOCUMENT_AGENT_CHECKPOINT_CONFLICT"
    status_code = 409


class DocumentAgentCheckpointUnavailableError(AppServiceError):
    """新格式 TaskPlan 声明 checkpoint，但持久化数据不可恢复。"""

    error_code = "DOCUMENT_AGENT_CHECKPOINT_UNAVAILABLE"
    error_category = "system_error"
    status_code = 503


class ExternalServiceError(AppServiceError):
    """外部服务调用失败。"""

    error_code = "EXTERNAL_SERVICE_ERROR"
    error_category = "external_service_error"
    status_code = 503


class LLMCallError(ExternalServiceError):
    """大模型调用异常。"""

    error_code = "LLM_CALL_ERROR"


class ExternalServiceTimeoutError(ExternalServiceError):
    """外部服务调用超时。"""

    error_code = "EXTERNAL_SERVICE_TIMEOUT"
