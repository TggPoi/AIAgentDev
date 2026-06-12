import asyncio

import httpx


async def call_fake_rerank_api() -> None:
    url = "https://httpbin.org/post"

    query = "什么是混合检索？"
    docs = [
        "混合检索会结合向量检索和关键词检索。",
        "FastAPI 是一个 Python Web 框架。",
        "RRF 可以融合多个检索源的排序结果。",
    ]

    payload = {
        "model": "qwen3-rerank",
        "input": {
            "query": query,
            "documents": docs,
        },
        "parameters": {
            "return_documents": False,
            "top_n": 2,
        },
    }

    headers = {
        "Authorization": "Bearer fake-api-key",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        data = response.json()

        print("status_code:", response.status_code)
        print("server received headers Authorization:")
        print(data["headers"].get("Authorization"))
        print("server received json:")
        print(data["json"])

    except httpx.HTTPStatusError as exc:
        print("HTTP 状态错误")
        print("status:", exc.response.status_code)
        print("body:", exc.response.text)

    except httpx.RequestError as exc:
        print("请求失败")
        print("error:", repr(exc))


if __name__ == "__main__":
    asyncio.run(call_fake_rerank_api())