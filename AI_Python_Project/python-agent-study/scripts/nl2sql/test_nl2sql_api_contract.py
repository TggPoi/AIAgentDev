from __future__ import annotations

import asyncio

from fast_app.api.rag_chat_routes import (
    nl2sql_sse_event_generator,
    rag_chat_endpoint,
    rag_chat_stream_endpoint,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.rag_chat_schema import RagChatRequest
from fast_app.schemas.rag_chat_schema import RagChatResponse
from fast_app.services.exceptions import Nl2SqlLegacyStreamUnsupportedError
from fast_app.services.nl2sql.models import (
    DatasetAuthorization,
    DatasetDefinition,
    Nl2SqlQueryResult,
)


class Pipeline:
    async def run(self, request: object) -> RagChatResponse:
        assert getattr(request, "_nl2sql_authorization") is not None
        return RagChatResponse(
            query="查询资产",
            answer="查询返回 1 个资产。",
            sources=[],
            route_intent="structured_data_query",
            route_confidence=0.99,
            route_source="model",
            nl2sql_result=QueryService.result(),
        )


class EmptyRows:
    def all(self) -> list[object]:
        return []


class Session:
    async def scalar(self, _: object) -> int:
        return 0

    async def scalars(self, _: object) -> EmptyRows:
        return EmptyRows()


class QueryService:
    @staticmethod
    def result() -> Nl2SqlQueryResult:
        return Nl2SqlQueryResult(
            query_id="query_api_contract",
            request_id="request_api_contract",
            trace_id="trace_api_contract",
            dataset_id="game_test",
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

    async def authorize_action(self, **_: object) -> tuple[DatasetDefinition, DatasetAuthorization]:
        return (
            DatasetDefinition(
                dataset_id="game_test",
                name="游戏测试",
                domain="game",
                database_key="game_test",
                privacy_classification="non_sensitive",
                scope_column="project_id",
                allowed_views=("analytics.asset_catalog",),
                report_supported=True,
                enabled=True,
            ),
            DatasetAuthorization(dataset_id="game_test", scope_ids=("game_p1",)),
        )

    async def query(self, **kwargs: object) -> Nl2SqlQueryResult:
        return self.result().model_copy(update={"dataset_id": str(kwargs["dataset_id"])})


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
        Pipeline(),  # type: ignore[arg-type]
        Session(),  # type: ignore[arg-type]
        QueryService(),  # type: ignore[arg-type]
    )
    assert response.route_intent == "structured_data_query"
    assert response.route_source == "model"
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
            Pipeline(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
        )
    except Nl2SqlLegacyStreamUnsupportedError:
        pass
    else:
        raise AssertionError("legacy stream accepted NL2SQL")
    print("NL2SQL API and SSE contract checks passed")


if __name__ == "__main__":
    asyncio.run(main())
