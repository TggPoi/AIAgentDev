class AppServiceError(Exception):
    """业务异常基类。"""


class DocumentNotFoundError(AppServiceError):
    """文档不存在。"""


class NoSearchResultError(AppServiceError):
    """检索结果为空。"""


class ExternalServiceError(AppServiceError):
    """外部服务调用失败。"""