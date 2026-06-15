from fast_app.components.embeddings.base import BaseEmbeddingClient


class MockEmbeddingClient(BaseEmbeddingClient):
    """本地稳定 mock embedding 客户端。

    这个类不调用外部 embedding 服务，只根据文本稳定生成固定维度向量。
    它主要用于本地验证 ingestion / retrieval / evaluation 的工程链路。

    注意：mock embedding 不能代表真实语义相似度，只能保证同一段文本每次
    生成相同向量，方便本地重复测试。
    """

    def __init__(self, dim: int):
        self.dim = dim

    async def embed_query(self, text: str) -> list[float]:
        return self._vector_for_text(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for_text(text) for text in texts]

    def _vector_for_text(self, text: str) -> list[float]:
        # seed 由文本字符编码求和得到。
        # 同一段文本会得到相同 seed，从而生成相同向量。
        seed = sum(ord(char) for char in text) or 1

        # 使用取模让每个维度落在 0 到 1 之间。
        # 这只是为了构造合法向量，不表示真实语义。
        return [((seed + index) % 997) / 997 for index in range(self.dim)]
