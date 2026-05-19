from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        min_length=1,
        max_length=2000,
        description="用户输入消息",
    )
    session_id: str | None = Field(
        default=None,
        alias="sessionId",
        description="会话 ID",
    )
    stream: bool = Field(
        default=True,
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
    session_id: str = Field(alias="sessionId")
    sources: list[str] = Field(default_factory=list)


def main() -> None:
    req = ChatRequest(
        message="   什么是 RAG？   ",
        sessionId="session_001",
        stream=True,
    )

    print("=== request ===")
    print(req)
    print(req.message)
    print(req.session_id)

    response = ChatResponse(
        answer="RAG 是检索增强生成。",
        sessionId=req.session_id or "new_session",
        sources=["doc_001", "doc_002"],
    )

    print("=== response dict ===")
    print(response.model_dump())
    print(response.model_dump(by_alias=True))
    print(response.model_dump(by_alias=True, exclude_none=True))

    try:
        ChatRequest(
            message="hello",
            unknownField="xxx",
        )
    except ValidationError as e:
        print("=== extra forbid ===")
        print(e)


if __name__ == "__main__":
    main()