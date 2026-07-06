from pydantic import BaseModel, Field


class RetrievalPermissionScope(BaseModel):
    """服务端生成的知识库检索权限范围。

    这个模型只由认证后的用户上下文转换得到，不能从请求体读取。
    """

    can_read_all: bool = Field(default=False, description="是否允许读取全部知识库文档。")
    user_id: str | None = Field(default=None, description="当前检索用户 ID，用于私有文档或审计扩展。")
    department_codes: list[str] = Field(
        default_factory=list,
        description="用户可读取的部门 code 列表，会下推到检索过滤条件。",
    )
    allow_public: bool = Field(default=True, description="是否允许读取 public 范围的公共文档。")


__all__ = ["RetrievalPermissionScope"]
