from typing import TypedDict

#定义document对象的数据结构

class DocumentMetadata(TypedDict):
    source: str
    chunk_index: int

# 表示一个文本 chunk
class Document(TypedDict):
    id: str
    content: str
    metadata: DocumentMetadata