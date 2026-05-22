from fastapi import APIRouter, HTTPException

from fast_app.schemas.rag_schema import SearchRequest, SearchResponse
from fast_app.services.exceptions import NoSearchResultError
from fast_app.services.rag_service import search
from fast_app.schemas.rag_schema import RetrievedDocument
from fast_app.services.exceptions import DocumentNotFoundError
from fast_app.services.rag_service import get_document


router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=SearchResponse)
def rag_search_endpoint(req: SearchRequest) -> SearchResponse:
    try:
        return search(req)
    
    #将Service层业务异常转换为HTTP异常，返回给客户端
    except NoSearchResultError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NO_SEARCH_RESULT",
                "message": str(e),
            },
        ) from e
    


@router.get("/documents/{doc_id}", response_model=RetrievedDocument)
def get_document_endpoint(doc_id: str) -> RetrievedDocument:
    try:
        return get_document(doc_id)
    except DocumentNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DOCUMENT_NOT_FOUND",
                "message": str(e),
            },
        ) from e