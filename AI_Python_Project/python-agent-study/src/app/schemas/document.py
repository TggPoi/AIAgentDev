from typing import Literal, TypedDict

# 这个文件只负责定义数据结构。

RetrievalSource = Literal["milvus", "elasticsearch", "mock"]


class RetrievedDoc(TypedDict):
    id: str
    content: str
    score: float
    source: RetrievalSource