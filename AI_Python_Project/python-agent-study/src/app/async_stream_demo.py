import asyncio


async def mock_llm_stream(prompt: str):
    tokens = [
        "RAG",
        " 是",
        " 检索",
        " 增强",
        " 生成",
        "。",
    ]

    print(f"prompt: {prompt}")

    for token in tokens:
        await asyncio.sleep(0.5)
        yield token


async def main() -> None:
    async for token in mock_llm_stream("什么是 RAG？"):
        # 强制刷新数据流。如果 end=''，则不会在输出后添加换行符；如果 flush=True，则会强制刷新输出缓冲区，使得数据能够立即显示在控制台上。这对于实时显示生成的文本非常有用。
        print(token, end="", flush=True)

    print()


if __name__ == "__main__":
    asyncio.run(main())