# TypedDict：流程状态 模拟的是后面 LangGraph 中的State

from typing import TypedDict

from app.domain.rag_models import RagContext, RetrievedDoc


class RagState(TypedDict):
    # 用户问题
    query: str

    # 检索到的文档
    docs: list[RetrievedDoc]

    # 构造出来的上下文
    context: RagContext | None

    # 最终回答
    answer: str | None