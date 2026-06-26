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
