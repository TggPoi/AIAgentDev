from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    # 禁止客户端传入未声明字段
    model_config = ConfigDict(extra="forbid")

    # 用户消息，不能为空，最长 2000
    message: str = Field(
        min_length=1,
        max_length=2000,
        description="用户输入消息",
    )

    # 会话 ID，可选
    session_id: str | None = Field(
        default=None,
        description="会话 ID",
    )

    # 是否启用流式输出，默认不启用
    stream: bool = Field(
        default=False,
        description="是否启用流式输出",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()

        if normalized == "":
            raise ValueError("message 不能只包含空白字符")

        return normalized


class ChatResponse(BaseModel):
    answer: str
    session_id: str