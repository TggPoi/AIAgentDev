from fast_app.schemas.rag_schema import (
    RetrievedDocument,
    SearchRequest,
    SearchResponse,
)


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

    return SearchResponse(
        query=req.query,
        mode=req.mode,
        documents=filtered_docs[: req.top_k],
    )