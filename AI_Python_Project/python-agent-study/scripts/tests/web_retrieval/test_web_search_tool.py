from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.agents.tools.web_search_tools import search_web_with_bocha
from fast_app.core.config import Settings


async def main() -> None:
    if "--real" in sys.argv:
        query = " ".join(sys.argv[2:]) or "FastAPI official documentation ASGI"
        async with httpx.AsyncClient() as client:
            results = await search_web_with_bocha(
                settings=Settings(),
                http_client=client,
                query=query,
                count=5,
                site="fastapi.tiangolo.com",
            )
        print("\n".join(result.url for result in results))
        assert any("fastapi.tiangolo.com" in result.url for result in results)
        print("web_search_real=passed")
        return

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["summary"] is True
        assert payload["query"].startswith("site:fastapi.tiangolo.com ")
        return httpx.Response(
            200,
            json={
                "webPages": {
                    "value": [
                        {
                            "name": "FastAPI",
                            "url": "https://fastapi.tiangolo.com/",
                            "summary": "FastAPI 官方文档。",
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await search_web_with_bocha(
            settings=Settings(BOCHA_API_KEY="test-key"),
            http_client=client,
            query="FastAPI official documentation ASGI",
            count=3,
            site="fastapi.tiangolo.com",
        )

    assert results[0].url == "https://fastapi.tiangolo.com/"
    assert results[0].summary == "FastAPI 官方文档。"
    print("web_search_tool=passed")


if __name__ == "__main__":
    asyncio.run(main())
