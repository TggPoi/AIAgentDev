import asyncio

import httpx


async def fetch_one(client: httpx.AsyncClient, index: int) -> None:
    response = await client.get(
        "https://httpbin.org/get",
        params={"index": index},
    )
    response.raise_for_status()

    data = response.json()
    print(f"index={index}, args={data['args']}")


async def main() -> None:
    # 等待响应期间不阻塞整个事件循环
    async with httpx.AsyncClient(timeout=10.0) as client:
        await fetch_one(client, 1)
        await fetch_one(client, 2)
        await fetch_one(client, 3)


if __name__ == "__main__":
    asyncio.run(main())