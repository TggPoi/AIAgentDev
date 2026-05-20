# dataclass：内部业务数据对象

from dataclasses import dataclass


@dataclass
class RetrievedDoc:
    # 文档 ID
    id: str

    # 文档内容
    content: str

    # 相关性分数
    score: float

    # 文档来源，例如 milvus / elasticsearch
    source: str


@dataclass
class RagContext:
    # 拼接后的上下文字符串
    text: str

    # 参与构造上下文的文档
    docs: list[RetrievedDoc]