from fast_app.domain.knowledge_models import KnowledgeChunk


def build_demo_chunks() -> list[KnowledgeChunk]:
    return [
        KnowledgeChunk(
            id="rag_basic_001",
            title="RAG 基础",
            source="demo",
            content=(
                "RAG 是 Retrieval-Augmented Generation 的缩写，中文通常称为检索增强生成。"
                "它的核心思想是在大模型生成回答之前，先从外部知识库中检索相关内容，"
                "再把检索结果作为上下文提供给大模型，从而提升回答的准确性和可追溯性。"
            ),
        ),
        KnowledgeChunk(
            id="rag_vector_001",
            title="向量检索",
            source="demo",
            content=(
                "向量检索会先把文本转换成 embedding 向量，然后通过向量相似度查找语义接近的内容。"
                "它适合处理表达方式不同但语义相似的问题，例如用户没有使用原文关键词，"
                "但问题含义和某段知识非常接近。"
            ),
        ),
        KnowledgeChunk(
            id="rag_keyword_001",
            title="关键词检索",
            source="demo",
            content=(
                "关键词检索通常基于倒排索引和 BM25 等相关性算法。"
                "它适合处理包含明确关键词、术语、编号、函数名、错误信息的问题。"
                "ElasticSearch 是常见的关键词检索引擎。"
            ),
        ),
        KnowledgeChunk(
            id="rag_hybrid_001",
            title="混合检索",
            source="demo",
            content=(
                "混合检索会同时结合向量检索和关键词检索。"
                "向量检索擅长捕捉语义相似内容，关键词检索擅长匹配精确词项。"
                "在 RAG 系统中，混合检索可以提高召回的稳定性，减少单一检索方式带来的遗漏。"
            ),
        ),
        KnowledgeChunk(
            id="milvus_basic_001",
            title="Milvus 基础",
            source="demo",
            content=(
                "Milvus 是一个向量数据库，常用于存储文本、图片、音频等数据的向量表示。"
                "在 RAG 系统中，Milvus 通常负责根据 query embedding 检索相似的文档 chunk。"
                "使用 Milvus 时，需要保证 collection 的向量维度和 embedding 模型输出维度一致。"
            ),
        ),
        KnowledgeChunk(
            id="es_basic_001",
            title="ElasticSearch 基础",
            source="demo",
            content=(
                "ElasticSearch 是一个分布式搜索引擎，擅长全文检索、关键词匹配、过滤、排序和聚合。"
                "在 RAG 系统中，ElasticSearch 常用于关键词检索，尤其适合匹配错误日志、函数名、"
                "类名、配置项和专业术语。"
            ),
        ),
        KnowledgeChunk(
            id="langgraph_basic_001",
            title="LangGraph 基础",
            source="demo",
            content=(
                "LangGraph 是用于构建状态化 AI 工作流的框架。"
                "它通过 State 保存流程中的共享数据，通过 Node 执行业务步骤，"
                "通过 Edge 控制节点之间的执行顺序。"
            ),
        ),
    ]


def main() -> None:
    chunks = build_demo_chunks()

    print(f"chunk 数量：{len(chunks)}")

    for chunk in chunks:
        print("-" * 80)
        print(f"id: {chunk.id}")
        print(f"title: {chunk.title}")
        print(f"source: {chunk.source}")
        print(f"content: {chunk.content}")
        print(f"content length: {len(chunk.content)}")


if __name__ == "__main__":
    main()


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python src/app/build_demo_chunks.py
# chunk 数量：7
# --------------------------------------------------------------------------------
# id: rag_basic_001
# title: RAG 基础
# source: demo
# content: RAG 是 Retrieval-Augmented Generation 的缩写，中文通常称为检索增强生成。它的核心思想是在大模型生成回答之前，先从外部知识库中检索相关内容，再把检索结果作为上下文提供给大模型，从而提升回答的准确性和可追溯性。
# content length: 121
# --------------------------------------------------------------------------------
# id: rag_vector_001
# title: 向量检索
# source: demo
# content: 向量检索会先把文本转换成 embedding 向量，然后通过向量相似度查找语义接近的内容。它适合处理表达方式不同但语义相似的问题，例如用户没有使用原文关键词，但问题含义和某段知识非常接近。
# content length: 94
# --------------------------------------------------------------------------------
# id: rag_keyword_001
# title: 关键词检索
# source: demo
# content: 关键词检索通常基于倒排索引和 BM25 等相关性算法。它适合处理包含明确关键词、术语、编号、函数名、错误信息的问题。ElasticSearch 是常见的关键词检索引擎。
# content length: 84
# --------------------------------------------------------------------------------
# id: rag_hybrid_001
# title: 混合检索
# source: demo
# content: 混合检索会同时结合向量检索和关键词检索。向量检索擅长捕捉语义相似内容，关键词检索擅长匹配精确词项。在 RAG 系统中，混合检索可以提高召回的稳定性，减少单一检索方式带来的遗漏。
# content length: 88
# --------------------------------------------------------------------------------
# id: milvus_basic_001
# title: Milvus 基础
# source: demo
# content: Milvus 是一个向量数据库，常用于存储文本、图片、音频等数据的向量表示。在 RAG 系统中，Milvus 通常负责根据 query embedding 检索相似的文档 chunk。使用 Milvus 时，需要保证 collection 的向量维度和 embedding 模型输出维度一致。
# content length: 146
# --------------------------------------------------------------------------------
# id: es_basic_001
# title: ElasticSearch 基础
# source: demo
# content: ElasticSearch 是一个分布式搜索引擎，擅长全文检索、关键词匹配、过滤、排序和聚合。在 RAG 系统中，ElasticSearch 常用于关键词检索，尤其适合匹配错误日志、函数名、类名、配置项和专业术语。
# content length: 107
# --------------------------------------------------------------------------------
# id: langgraph_basic_001
# title: LangGraph 基础
# source: demo
# content: LangGraph 是用于构建状态化 AI 工作流的框架。它通过 State 保存流程中的共享数据，通过 Node 执行业务步骤，通过 Edge 控制节点之间的执行顺序。
# content length: 85