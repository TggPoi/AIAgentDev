from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


RetrievalMode = Literal["vector", "keyword", "hybrid"]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)

    mode: RetrievalMode = "hybrid"

    top_k: int = Field(default=5, ge=1, le=50)
    
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()

        if value == "":
            raise ValueError("query 不能只包含空白字符")

        return value


class RetrievedDocument(BaseModel):
    id: str
    content: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    source: str


class SearchResponse(BaseModel):
    query: str
    mode: RetrievalMode
    documents: list[RetrievedDocument] = Field(default_factory=list)


def mock_search(req: SearchRequest) -> SearchResponse:
    docs = [
        RetrievedDocument(
            id="doc_001",
            content="Milvus is used for vector search.",
            score=0.91,
            source="milvus",
        ),
        RetrievedDocument(
            id="doc_002",
            content="ElasticSearch is used for keyword search.",
            score=0.88,
            source="elasticsearch",
        ),
    ]

    filtered_docs = [
        doc for doc in docs
        if doc.score >= req.min_score
    ]

    return SearchResponse(
        query=req.query,
        mode=req.mode,
        documents=filtered_docs[: req.top_k],
    )


def main() -> None:
    req = SearchRequest(
        query="   什么是 Hybrid Retrieval？   ",
        mode="hybrid",
        top_k=5,
        min_score=0.8,
    )

    response = mock_search(req)

    print("=== request ===")
    print(req)

    print("=== response model ===")
    print(response)

    print("=== response dict ===")
    print(response.model_dump())

    try:
        SearchRequest(
            query="",
            mode="graph",
            top_k=1000,
        )
    except ValidationError as e:
        print("=== request 校验失败 ===")
        print(e)


if __name__ == "__main__":
    main()