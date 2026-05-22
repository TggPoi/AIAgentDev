from fast_app.schemas.rag_schema import (
    RetrievedDocument,
    SearchRequest,
    SearchResponse,
)
from fast_app.services.exceptions import NoSearchResultError
from fast_app.services.exceptions import DocumentNotFoundError


def search(req: SearchRequest) -> SearchResponse:
    mock_docs = [
        RetrievedDocument(
            id="doc_001",
            content=f"Milvus vector result for: {req.query}",
            score=0.91,
            source="milvus",
        ),
        RetrievedDocument(
            id="doc_002",
            content=f"ElasticSearch keyword result for: {req.query}",
            score=0.88,
            source="elasticsearch",
        ),
        RetrievedDocument(
            id="doc_003",
            content="Low score document",
            score=0.3,
            source="mock",
        ),
    ]

    filtered_docs = [
        doc for doc in mock_docs
        if doc.score >= req.min_score
    ]

    if len(filtered_docs) == 0:
        raise NoSearchResultError(
            f"没有找到满足 min_score={req.min_score} 的文档"
        )

    return SearchResponse(
        query=req.query,
        mode=req.mode,
        documents=filtered_docs[: req.top_k],
    )



def get_document(doc_id: str) -> RetrievedDocument:
    mock_docs = {
        "doc_001": RetrievedDocument(
            id="doc_001",
            content="Milvus vector result",
            score=0.91,
            source="milvus",
        ),
        "doc_002": RetrievedDocument(
            id="doc_002",
            content="ElasticSearch keyword result",
            score=0.88,
            source="elasticsearch",
        ),
    }

    doc = mock_docs.get(doc_id)

    if doc is None:
        raise DocumentNotFoundError(f"文档不存在: {doc_id}")

    return doc