from fastapi import APIRouter

from fast_app.schemas.rag_schema import SearchRequest, SearchResponse
from fast_app.services.rag_service import search


router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=SearchResponse)
def rag_search_endpoint(req: SearchRequest) -> SearchResponse:
    return search(req)