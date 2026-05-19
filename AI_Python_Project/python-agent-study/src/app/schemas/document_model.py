from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    source: str
    chunk_index: int = Field(ge=0)


class Document(BaseModel):
    id: str
    content: str = Field(min_length=1)
    metadata: DocumentMetadata