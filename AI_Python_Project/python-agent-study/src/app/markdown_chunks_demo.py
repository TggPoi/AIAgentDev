from pathlib import Path

from app.build_markdown_chunks import build_chunks_from_markdown


def main() -> None:
    file_path = Path("src/app/demo_docs/rag_intro.md")

    chunks = build_chunks_from_markdown(
        file_path=file_path,
        source="demo_docs/rag_intro.md",
        chunk_size=300,
        chunk_overlap=50,
    )

    print(f"chunks_count: {len(chunks)}")

    for chunk in chunks:
        print("-" * 80)
        print(f"id: {chunk.id}")
        print(f"title: {chunk.title}")
        print(f"source: {chunk.source}")
        print(f"metadata: {chunk.metadata}")
        print("content:")
        print(chunk.content)


if __name__ == "__main__":
    main()


'''
(.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python src/app/markdown_chunks_demo.py
chunks_count: 5
--------------------------------------------------------------------------------
id: rag_intro_s001_c001
title: RAG 基础教程
source: demo_docs/rag_intro.md
metadata: {'section_path': ['RAG 基础教程'], 'heading_level': 1, 'section_index': 1, 'chunk_index': 1}
content:
标题路径：RAG 基础教程

RAG 是 Retrieval-Augmented Generation 的缩写，表示检索增强生成。
--------------------------------------------------------------------------------
id: rag_intro_s002_c001
title: 向量检索
source: demo_docs/rag_intro.md
metadata: {'section_path': ['RAG 基础教程', '向量检索'], 'heading_level': 2, 'section_index': 2, 'chunk_index': 1}
content:
标题路径：RAG 基础教程 / 向量检索

向量检索会先把文本转换成 embedding 向量，然后根据向量相似度查找语义接近的文档。

向量检索适合处理同义表达、概念相近、问题和原文不完全一致的场景。
--------------------------------------------------------------------------------
id: rag_intro_s003_c001
title: 关键词检索
source: demo_docs/rag_intro.md
metadata: {'section_path': ['RAG 基础教程', '关键词检索'], 'heading_level': 2, 'section_index': 3, 'chunk_index': 1}
content:
标题路径：RAG 基础教程 / 关键词检索

关键词检索通常基于倒排索引和 BM25 等相关性算法。

它适合匹配错误码、函数名、专有名词、配置项、日志片段等精确词。
--------------------------------------------------------------------------------
id: rag_intro_s004_c001
title: 混合检索
source: demo_docs/rag_intro.md
metadata: {'section_path': ['RAG 基础教程', '混合检索'], 'heading_level': 2, 'section_index': 4, 'chunk_index': 1}
content:
标题路径：RAG 基础教程 / 混合检索

混合检索会同时结合向量检索和关键词检索。

向量检索负责语义召回，关键词检索负责精确匹配。两者结合可以提升 RAG 的召回稳定性。
--------------------------------------------------------------------------------
id: rag_intro_s005_c001
title: RRF 融合
source: demo_docs/rag_intro.md
metadata: {'section_path': ['RAG 基础教程', '混合检索', 'RRF 融合'], 'heading_level': 3, 'section_index': 5, 'chunk_index': 1}
content:
标题路径：RAG 基础教程 / 混合检索 / RRF 融合

RRF 不直接比较不同检索源的原始分数，而是根据每个检索源内部排名进行融合。

这适合 Milvus 和 ElasticSearch 这种异构检索源。

'''