from fastapi import APIRouter, HTTPException

from fast_app.schemas.rag_schema import RetrievedDocument, SearchRequest, SearchResponse
from fast_app.services.exceptions import DocumentNotFoundError, NoSearchResultError
from fast_app.services.rag_service import get_document, search


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