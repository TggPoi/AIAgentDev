from __future__ import annotations

import asyncio

from fast_app.api.rag_chat_routes import (
    nl2sql_sse_event_generator,
    rag_chat_endpoint,
    rag_chat_stream_endpoint,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.services.exceptions import Nl2SqlLegacyStreamUnsupportedError
from fast_app.services.nl2sql.models import Nl2SqlQueryResult


class PipelineMustNotRun:
    async def run(self, _: object) -> object:
        raise AssertionError("NL2SQL query must bypass RAG pipeline")


class QueryService:
    async def query(self, **kwargs: object) -> Nl2SqlQueryResult:
        return Nl2SqlQueryResult(
            query_id="query_api_contract",
            request_id="request_api_contract",
            trace_id="trace_api_contract",
            dataset_id=str(kwargs["dataset_id"]),
            parameterized_sql="SELECT asset_name FROM analytics.asset_catalog LIMIT 2",
            columns=["asset_name"],
            rows=[{"asset_name": "角色资产01"}],
            row_count=1,
            truncated=False,
            execution_ms=3,
            attempt_count=1,
            summary="查询返回 1 个资产。",
            warnings=[],
            markdown_table="| asset_name |\n| --- |\n| 角色资产01 |",
        )


async def main() -> None:
    request = RagChatRequest(
        query="查询资产",
        dataset_id="game_test",
        nl2sql_action="query",
    )
    user = CurrentUserContext(
        user_id="api_contract",
        is_authenticated=True,
        auth_source="jwt",
    )
    response = await rag_chat_endpoint(
        request,
        user,
        PipelineMustNotRun(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        QueryService(),  # type: ignore[arg-type]
    )
    assert response.route_intent == "structured_data_query"
    assert response.nl2sql_result is not None
    assert response.nl2sql_result.query_id == "query_api_contract"

    events = [
        chunk
        async for chunk in nl2sql_sse_event_generator(response.nl2sql_result)
    ]
    assert [chunk.splitlines()[0] for chunk in events] == [
        "event: nl2sql_sql_generated",
        "event: nl2sql_result",
        "event: done",
    ]
    try:
        await rag_chat_stream_endpoint(
            request,
            user,
            PipelineMustNotRun(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )
    except Nl2SqlLegacyStreamUnsupportedError:
        pass
    else:
        raise AssertionError("legacy stream accepted NL2SQL")
    print("NL2SQL API and SSE contract checks passed")


if __name__ == "__main__":
    asyncio.run(main())
