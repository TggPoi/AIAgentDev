from collections.abc import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from fast_app.schemas.rag_schema import RetrievedDocument, SearchRequest, SearchResponse
from fast_app.services.exceptions import DocumentNotFoundError, NoSearchResultError
from fast_app.services.rag.rag_service import get_document, search, stream_search


router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=SearchResponse)
async def rag_search_endpoint(req: SearchRequest) -> SearchResponse:
    try:
        return await search(req)
    except NoSearchResultError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NO_SEARCH_RESULT",
                "message": str(e),
            },
        ) from e


@router.get("/documents/{doc_id}", response_model=RetrievedDocument)
async def get_document_endpoint(doc_id: str) -> RetrievedDocument:
    try:
        return await get_document(doc_id)
    except DocumentNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DOCUMENT_NOT_FOUND",
                "message": str(e),
            },
        ) from e


async def rag_sse_event_generator(
    req: SearchRequest,
) -> AsyncGenerator[str, None]:
    try:
        async for token in stream_search(req):
            yield f"data: {token}\n\n"

        yield "event: done\ndata: [DONE]\n\n"

    except NoSearchResultError as e:
        yield (
            "event: error\n"
            f"data: NO_SEARCH_RESULT: {str(e)}\n\n"
        )


@router.post("/search/stream")
async def rag_search_stream_endpoint(req: SearchRequest) -> StreamingResponse:
    return StreamingResponse(
        rag_sse_event_generator(req),
        media_type="text/event-stream",
    )