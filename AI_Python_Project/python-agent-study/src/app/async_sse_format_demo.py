import asyncio
from collections.abc import AsyncGenerator

# syncGenerator[str, None] 这个异步生成器每次 yield 出来的值是 str
# None 不接收外部 send 进来的值
async def mock_sse_stream(prompt: str) -> AsyncGenerator[str, None]:
    tokens = ["RAG", " 是", " 检索", " 增强", " 生成", "。"]

    for token in tokens:
        await asyncio.sleep(0.5)
        yield f"data: {token}\n\n"

    yield "event: done\ndata: [DONE]\n\n"


async def main() -> None:
    async for chunk in mock_sse_stream("什么是 RAG？"):
        print(repr(chunk))


if __name__ == "__main__":
    asyncio.run(main())