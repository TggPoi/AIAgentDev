import asyncio

from pydantic import ValidationError

from app.schemas.rag_schema import RagRequest
from app.services.async_rag_pipeline import RagPipelineError, run_rag, run_rag_stream


async def run_normal_demo() -> None:
    print("=== normal response ===")

    try:
        req = RagRequest(
            query="   什么是混合检索？   ",
            mode="hybrid",
            top_k=5,
            min_score=0.8,
        )

        response = await run_rag(req)

        print(response)
        print(response.model_dump())

    except ValidationError as e:
        print("请求参数校验失败:")
        print(e)

    except RagPipelineError as e:
        print("RAG Pipeline 执行失败:")
        print(e)


async def run_stream_demo() -> None:
    print()
    print("=== streaming response ===")

    try:
        req = RagRequest(
            query="什么是混合检索？",
            mode="hybrid",
            top_k=5,
            min_score=0.8,
        )

        async for token in run_rag_stream(req):
            print(token, end="", flush=True)

        print()

    except ValidationError as e:
        print("请求参数校验失败:")
        print(e)

    except RagPipelineError as e:
        print("RAG Pipeline 执行失败:")
        print(e)

#传入一个没有在系统中定义的字段 unknown_field=True，同时 query 字段只包含空格，这两个都会导致 RagRequest 的校验失败，从而触发 ValidationError 异常
async def run_validation_error_demo() -> None:
    print()
    print("=== validation error demo ===")

    try:
        RagRequest(
            query="   ",
            mode="graph",
            top_k=100,
            unknown_field=True,
        )
    except ValidationError as e:
        print(e)


async def main() -> None:
    await run_normal_demo()
    await run_stream_demo()
    await run_validation_error_demo()


if __name__ == "__main__":
    asyncio.run(main())