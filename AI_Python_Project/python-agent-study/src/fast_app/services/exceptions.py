from typing import Literal


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


class CurrentPasswordInvalidError(AppServiceError):
    """修改密码时当前密码校验失败。"""

    error_code = "AUTH_CURRENT_PASSWORD_INVALID"
    status_code = 400


class PasswordPolicyError(AppServiceError):
    """新密码不满足服务端强度策略或与当前密码相同。"""

    error_code = "AUTH_PASSWORD_POLICY_FAILED"
    status_code = 400


class AccessManagementPermissionDeniedError(AppServiceError):
    """当前 actor 不具备目标账号管理范围。"""

    error_code = "ACCESS_MANAGEMENT_PERMISSION_DENIED"
    status_code = 403


class ManagedUserNotFoundError(AppServiceError):
    """管理范围内不存在目标账号。"""

    error_code = "MANAGED_USER_NOT_FOUND"
    status_code = 404


class UserListCursorInvalidError(AppServiceError):
    """用户列表 cursor 无法解析。"""

    error_code = "USER_LIST_CURSOR_INVALID"
    status_code = 400


class ManagedUserConflictError(AppServiceError):
    """用户名、邮箱或并发账号状态与当前写请求冲突。"""

    error_code = "MANAGED_USER_CONFLICT"
    status_code = 409


class ManagedUserAccessInvalidError(AppServiceError):
    """账号访问快照不满足服务端目录或组织约束。"""

    error_code = "MANAGED_USER_ACCESS_INVALID"
    status_code = 422
    _PUBLIC_FIELDS = frozenset(
        {
            "username",
            "account_type",
            "department_access",
            "direct_permission_codes",
        }
    )

    def __init__(
        self,
        message: str,
        *,
        field: Literal[
            "username",
            "account_type",
            "department_access",
            "direct_permission_codes",
        ],
        field_code: Literal["invalid"] = "invalid",
    ):
        if field not in self._PUBLIC_FIELDS:
            raise ValueError("ManagedUserAccessInvalidError field 不在公开 allowlist")
        if field_code != "invalid":
            raise ValueError("ManagedUserAccessInvalidError field_code 不受支持")
        super().__init__(message)
        self.public_message = "账号访问设置不合法"
        self.field = field
        self.field_code = field_code


class ManagedUserSelfOperationError(AppServiceError):
    """高风险用户管理写操作不能以当前 actor 自身为目标。"""

    error_code = "MANAGED_USER_SELF_OPERATION_FORBIDDEN"
    status_code = 409


class LastSystemAdminProtectedError(AppServiceError):
    """操作会使系统失去最后一个 active 系统管理员。"""

    error_code = "LAST_SYSTEM_ADMIN_PROTECTED"
    status_code = 409


class DocumentAccessPermissionDeniedError(AppServiceError):
    """当前 actor 不具备目标文档所属部门的 grant 管理权限。"""

    error_code = "DOCUMENT_ACCESS_PERMISSION_DENIED"
    status_code = 403


class DocumentAccessGrantNotFoundError(AppServiceError):
    """目标账号、文档或 grant 不存在于可操作范围。"""

    error_code = "DOCUMENT_ACCESS_GRANT_NOT_FOUND"
    status_code = 404


class DocumentAccessGrantInvalidError(AppServiceError):
    """grant 请求不满足跨部门精确文档授权语义。"""

    error_code = "DOCUMENT_ACCESS_GRANT_INVALID"
    status_code = 422


class DocumentAccessGrantConflictError(AppServiceError):
    """并发请求已经创建相同 active 文档授权。"""

    error_code = "DOCUMENT_ACCESS_GRANT_CONFLICT"
    status_code = 409


class KnowledgeDocumentNotFoundError(AppServiceError):
    """文档不存在或当前用户不可见；统一隐藏资源存在性。"""

    error_code = "KNOWLEDGE_DOCUMENT_NOT_FOUND"
    status_code = 404


class KnowledgeDocumentCursorInvalidError(AppServiceError):
    """知识文档列表 cursor 无法解析。"""

    error_code = "KNOWLEDGE_DOCUMENT_CURSOR_INVALID"
    status_code = 400


class KnowledgeDocumentContentTooLargeError(AppServiceError):
    """固定 revision 的源文件超过服务端读取上限。"""

    error_code = "KNOWLEDGE_DOCUMENT_CONTENT_TOO_LARGE"
    status_code = 413


class KnowledgeDocumentPreviewUnsupportedError(AppServiceError):
    """源文件类型不能生成安全文本预览。"""

    error_code = "KNOWLEDGE_DOCUMENT_PREVIEW_UNSUPPORTED"
    status_code = 415


class KnowledgeDocumentPreviewFailedError(AppServiceError):
    """受支持格式的源文件无法安全解析为文本预览。"""

    error_code = "KNOWLEDGE_DOCUMENT_PREVIEW_FAILED"
    status_code = 422


class KnowledgeDocumentContentUnavailableError(AppServiceError):
    """manifest 固定 revision 与 GitLab 文件内容无法一致读取。"""

    error_code = "KNOWLEDGE_DOCUMENT_CONTENT_UNAVAILABLE"
    status_code = 409


class KnowledgeDocumentSourceUnavailableError(AppServiceError):
    """GitLab 读取或文档解析服务当前不可用。"""

    error_code = "KNOWLEDGE_DOCUMENT_SOURCE_UNAVAILABLE"
    error_category = "external_service_error"
    status_code = 503


class ConversationNotFoundError(AppServiceError):
    """当前用户命名空间内不存在目标会话。"""

    error_code = "CONVERSATION_NOT_FOUND"
    status_code = 404


class ConversationCursorInvalidError(AppServiceError):
    """会话或消息 cursor 无法解析。"""

    error_code = "CONVERSATION_CURSOR_INVALID"
    status_code = 400


class ConversationConflictError(AppServiceError):
    """会话 ID 或并发持久化事实冲突。"""

    error_code = "CONVERSATION_CONFLICT"
    status_code = 409


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


class AgentTaskPlanNotFoundError(AppServiceError):
    """TaskPlan 不存在或不属于当前公开 API 请求用户。"""

    error_code = "AGENT_TASK_PLAN_NOT_FOUND"
    status_code = 404


class AgentTaskPlanCursorInvalidError(AppServiceError):
    """TaskPlan 列表 cursor 无法解析。"""

    error_code = "AGENT_TASK_PLAN_CURSOR_INVALID"
    status_code = 400


class AgentTaskPlanLeaseLostError(AppServiceError):
    """当前协程持有的 TaskPlan fencing token 已失效。"""

    error_code = "AGENT_TASK_PLAN_LEASE_LOST"
    error_category = "system_error"
    status_code = 409


class AgentTaskPlanVersionConflictError(AppServiceError):
    """TaskPlan 或 RuntimeRecord 的数据库原子 CAS 未命中。"""

    error_code = "AGENT_TASK_PLAN_VERSION_CONFLICT"
    status_code = 409


class AgentTaskPlanIdempotencyConflictError(AppServiceError):
    """同一 Idempotency-Key 被用于不同请求。"""

    error_code = "AGENT_TASK_PLAN_IDEMPOTENCY_CONFLICT"
    status_code = 409


class AgentTaskCapacityExceededError(AppServiceError):
    """全服务复杂 Agent 容量槽已经用尽。"""

    error_code = "AGENT_CAPACITY_EXCEEDED"
    status_code = 429

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AgentTaskPlanningContextUnresolvedError(AppServiceError):
    """有限历史不足以可靠解析当前指代。"""

    error_code = "AGENT_TASK_PLANNING_CONTEXT_UNRESOLVED"
    status_code = 400


class AgentTaskPlanningServiceUnavailableError(AppServiceError):
    """Query Rewriter 的模型或结构化输出临时不可用。"""

    error_code = "AGENT_TASK_PLANNING_SERVICE_UNAVAILABLE"
    error_category = "external_service_error"
    status_code = 503


class AgentTaskPlannerUnavailableError(AppServiceError):
    """Planner 或 Reviewer 技术调用最终失败。"""

    error_code = "AGENT_TASK_PLANNER_UNAVAILABLE"
    error_category = "external_service_error"
    status_code = 503


class AgentTaskSourceUnavailableError(AppServiceError):
    """请求策略或稳定配置不允许 TaskPlan 所需来源。"""

    error_code = "AGENT_TASK_SOURCE_UNAVAILABLE"
    status_code = 422


class AgentTaskPlanQualityRejectedError(AppServiceError):
    """Reviewer 修订后仍无法形成合格 Research TaskPlan。"""

    error_code = "AGENT_TASK_PLAN_QUALITY_REJECTED"
    status_code = 422


class AgentTaskPlanSchemaUnsupportedError(AppServiceError):
    """读取到不受支持的 Research TaskPlan Schema。"""

    error_code = "AGENT_TASK_PLAN_SCHEMA_UNSUPPORTED"
    status_code = 409


class AgentTaskEvidenceStateInvalidError(AppServiceError):
    """Result、Registry 或 Requirement Evidence 状态不一致。"""

    error_code = "AGENT_TASK_EVIDENCE_STATE_INVALID"
    error_category = "system_error"
    status_code = 500


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


class Nl2SqlDisabledError(AppServiceError):
    error_code = "NL2SQL_DISABLED"
    status_code = 503


class Nl2SqlPermissionDeniedError(AppServiceError):
    error_code = "NL2SQL_PERMISSION_DENIED"
    status_code = 403


class Nl2SqlSensitiveReportForbiddenError(AppServiceError):
    error_code = "NL2SQL_SENSITIVE_REPORT_FORBIDDEN"
    status_code = 403


class Nl2SqlUnsafeSqlError(AppServiceError):
    error_code = "NL2SQL_UNSAFE_SQL"
    status_code = 400


class Nl2SqlRepairableSqlError(Nl2SqlUnsafeSqlError):
    """仅表示模型 SQL 语法解析失败；允许外部模型修复一次。"""

    error_code = "NL2SQL_SQL_SYNTAX_INVALID"


class Nl2SqlExecutionError(AppServiceError):
    error_code = "NL2SQL_EXECUTION_FAILED"
    status_code = 400


class Nl2SqlLegacyStreamUnsupportedError(AppServiceError):
    error_code = "NL2SQL_LEGACY_STREAM_UNSUPPORTED"
    status_code = 400
