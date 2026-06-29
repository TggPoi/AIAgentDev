from pydantic import BaseModel, Field


class RetrievalPermissionScope(BaseModel):
    """服务端生成的知识库检索权限范围。

    这个模型只由认证后的用户上下文转换得到，不能从请求体读取。
    """

    can_read_all: bool = False
    user_id: str | None = None
    department_codes: list[str] = Field(default_factory=list)
    allow_public: bool = True


__all__ = ["RetrievalPermissionScope"]
