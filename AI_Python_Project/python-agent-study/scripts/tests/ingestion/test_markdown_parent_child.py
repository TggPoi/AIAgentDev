from __future__ import annotations

import asyncio
from copy import deepcopy

from fast_app.components.retrievers.elasticsearch_keyword_retriever import build_es_query
from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import LoadedDocument
from fast_app.domain.rag_models import RetrievalFilters, RetrievedDoc
from fast_app.graph.rag.rag_graph_nodes import create_build_context_node
from fast_app.graph.rag.rag_graph_state import build_graph_initial_state
from fast_app.graph.rag_agent.rag_agent_nodes import create_agent_build_context_node
from fast_app.graph.rag_agent.rag_agent_state import build_rag_agent_initial_state
from fast_app.ingestion.processing.markdown_hierarchy import (
    MARKDOWN_CHILD_RECORD_TYPE,
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
)
from fast_app.ingestion.processing.metadata_models import build_document_metadata
from fast_app.ingestion.stores.rag_store_writer import (
    build_es_bulk_actions,
    build_es_parent_bulk_actions,
    build_milvus_rows,
    validate_markdown_hierarchy_inputs,
)
from fast_app.services.rag.markdown_parent_context import MarkdownParentContextExpander
from fast_app.services.rag.rag_context_assembler import assemble_rag_context
from fast_app.services.rag.rag_pipeline_service import RagPipeline, docs_to_sources
from fast_app.schemas.rag_chat_schema import RagChatRequest


def document(path: str, content: str) -> LoadedDocument:
    metadata = build_document_metadata(path, "markdown")
    metadata.update(
        {
            "visibility": "department",
            "allowed_departments": ["engineering"],
            "allowed_users": [],
            "permission_source": "test",
        }
    )
    return LoadedDocument(
        source_path=path,
        content=content,
        document_type="markdown",
        metadata=metadata,
    )


def options() -> MarkdownHierarchyOptions:
    return MarkdownHierarchyOptions(
        source="test",
        parent_target_tokens=120,
        parent_max_tokens=180,
        parent_max_chars=1000,
        child_target_tokens=45,
        child_max_tokens=65,
        child_min_tokens=15,
        child_overlap_tokens=10,
    )


def build_fixture():
    rows = "\n".join(f"| item-{index} | {'value ' * 8}|" for index in range(24))
    code = "\n".join(f'print("line-{index}: {"x" * 40}")' for index in range(45))
    content = f"""# Guide

Intro sentence. Another sentence.

## Repeated

First repeated section.

## Repeated

Second repeated section.

### Level 3

#### Level 4

##### Level 5

###### Level 6

<div>html block</div>

Setext title
------------

```python
# this is code, not a heading
{code}
```

| Name | Value |
| --- | --- |
{rows}

> quoted line

- parent
  - nested child
"""
    return MarkdownHierarchyBuilder().build(
        [document("docs/guide.md", content)],
        options(),
    )


def test_builder() -> None:
    result = build_fixture()
    assert result.parents and result.children
    parent_ids = {parent.id for parent in result.parents}
    assert all(child.metadata["parent_id"] in parent_ids for child in result.children)
    assert all(
        parent.metadata["token_count"] <= options().parent_max_tokens
        and parent.metadata["char_count"] <= options().parent_max_chars
        for parent in result.parents
    )
    assert all(
        child.metadata["token_count"] <= options().child_max_tokens
        for child in result.children
    )
    combined = "\n".join(parent.content for parent in result.parents)
    for expected in (
        "# Guide",
        "## Repeated",
        "###### Level 6",
        "<div>html block</div>",
        "Setext title",
        "# this is code, not a heading",
        "| Name | Value |",
        "- nested child",
    ):
        assert expected in combined
    assert all(
        "# this is code, not a heading" not in child.metadata["section_path"]
        for child in result.children
    )
    for child in result.children:
        if "```python" in child.content:
            assert child.content.rstrip().endswith("```")
        if "| item-" in child.content:
            assert "| Name | Value |" in child.content
            assert "| --- | --- |" in child.content

    no_heading = MarkdownHierarchyBuilder().build(
        [document("docs/plain.md", "Short document without heading.")],
        options(),
    )
    assert len(no_heading.parents) == len(no_heading.children) == 1
    assert no_heading.children[0].metadata["section_path"] == ["plain"]
    # 面包屑下沉：父块/子块 content 必须以章节完整路径面包屑开头，
    # 使 LLM 可见文本（唯一进上下文的字段）自描述所属章节。
    for parent in result.parents:
        breadcrumb = " > ".join(parent.metadata["section_path"]) + "\n\n"
        assert parent.content.startswith(breadcrumb)
    for child in result.children:
        breadcrumb = " > ".join(child.metadata["section_path"]) + "\n\n"
        assert child.content.startswith(breadcrumb)
        assert child.search_text == child.content
    assert no_heading.children[0].content.startswith("plain\n\n")


def test_empty_heading_sections() -> None:
    """空标题章节不产出空壳块：标题块并入下一个有正文的章节。"""

    # 用例 A：一级标题无正文，直接接两个二级节。
    case_a = (
        "# 部署指南\n"
        "## 回滚操作\n"
        "出现问题时执行回滚。\n"
        "1. 停止服务\n"
        "## 监控\n"
        "观察错误率指标。\n"
    )
    result_a = MarkdownHierarchyBuilder().build(
        [document("docs/case-a.md", case_a)], options()
    )
    assert len(result_a.parents) == len(result_a.children) == 2
    # 空壳检查：任何父块/子块的正文部分（去掉面包屑）都不能只剩标题行。
    for chunk in [*result_a.parents, *result_a.children]:
        body = chunk.content.split("\n\n", 1)[1]
        assert not all(line.startswith("#") for line in body.splitlines())
    # 一级标题块应并入回滚节，而不是独立成空壳章节。
    rollback_parent = next(
        parent
        for parent in result_a.parents
        if parent.metadata["section_path"] == ["部署指南", "回滚操作"]
    )
    assert "# 部署指南" in rollback_parent.content

    # 用例 B：连续多级空标题，全部并入第一个有正文的章节。
    case_b = "# 一级空\n## 二级空\n### 三级有正文\n这一节才有内容。\n"
    result_b = MarkdownHierarchyBuilder().build(
        [document("docs/case-b.md", case_b)], options()
    )
    assert len(result_b.parents) == len(result_b.children) == 1
    parent_b = result_b.parents[0]
    assert parent_b.metadata["section_path"] == ["一级空", "二级空", "三级有正文"]
    for heading in ("# 一级空", "## 二级空", "### 三级有正文"):
        assert heading in parent_b.content

    # 用例 C：全文只有一个空标题，兜底产出避免文档 0 chunk 不可检索。
    result_c = MarkdownHierarchyBuilder().build(
        [document("docs/case-c.md", "# 只有一个空标题\n")], options()
    )
    assert len(result_c.parents) == len(result_c.children) == 1
    assert "# 只有一个空标题" in result_c.parents[0].content


def test_stable_ids() -> None:
    before = MarkdownHierarchyBuilder().build(
        [
            document(
                "docs/stable.md",
                "# First\n\nOld text.\n\n# Second\n\nStable text.",
            )
        ],
        options(),
    )
    after = MarkdownHierarchyBuilder().build(
        [
            document(
                "docs/stable.md",
                "# First\n\nChanged text. " + ("More text. " * 100) + "\n\n# Second\n\nStable text.",
            )
        ],
        options(),
    )
    before_ids = {
        child.id
        for child in before.children
        if child.metadata["section_path"] == ["Second"]
    }
    after_ids = {
        child.id
        for child in after.children
        if child.metadata["section_path"] == ["Second"]
    }
    assert before_ids == after_ids


def test_store_contract() -> None:
    result = build_fixture()
    validate_markdown_hierarchy_inputs(result.children, result.parents)
    es_children = build_es_bulk_actions("v2", result.children)
    es_parents = build_es_parent_bulk_actions("v2", result.parents)
    vectors = [[0.0, 1.0] for _ in result.children]
    milvus_rows = build_milvus_rows(
        Settings(EMBEDDING_DIM=2),
        result.children,
        vectors,
    )
    assert all(row["_source"]["record_type"] == "markdown_child" for row in es_children)
    assert all(
        row["_source"]["search_text"] == chunk.search_text
        for row, chunk in zip(es_children, result.children, strict=True)
    )
    assert all(row["_source"]["record_type"] == "markdown_parent" for row in es_parents)
    assert len(milvus_rows) == len(result.children)
    assert {row["id"] for row in milvus_rows}.isdisjoint(
        {parent.id for parent in result.parents}
    )
    keyword_query = build_es_query("guide", RetrievalFilters(can_read_all=True))
    assert {"term": {"record_type": "markdown_parent"}} in keyword_query["bool"]["must_not"]


class FakeElasticsearch:
    def __init__(self, parent_sources: list[dict]) -> None:
        self.parent_sources = parent_sources
        self.calls: list[dict] = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "hits": {
                "hits": [
                    {"_id": source["id"], "_source": source}
                    for source in self.parent_sources
                ]
            }
        }


class RecordingGuard:
    def __init__(self) -> None:
        self.contents: list[str] = []
        self.sources: list[str] = []

    async def filter_retrieved_docs(self, docs, *, source: str):
        self.contents = [doc.content for doc in docs]
        self.sources.append(source)
        return docs


async def test_expansion_and_context() -> None:
    result = build_fixture()
    children_by_parent = {
        parent.id: [
            chunk
            for chunk in result.children
            if chunk.metadata["parent_id"] == parent.id
        ]
        for parent in result.parents
    }
    parent = max(
        result.parents,
        key=lambda item: len(children_by_parent[item.id]),
    )
    all_parent_children = children_by_parent[parent.id]
    assert len(all_parent_children) >= 3
    children = all_parent_children[:2]
    retrieved = [
        RetrievedDoc(
            id=chunk.id,
            content=chunk.content,
            score=0.9 - index * 0.1,
            source="milvus",
            title=chunk.title,
            metadata=deepcopy(chunk.metadata),
            retrieval_sources=["milvus", "elasticsearch"],
        )
        for index, chunk in enumerate(children)
    ]
    parent_source = build_es_parent_bulk_actions("v2", [parent])[0]["_source"]
    client = FakeElasticsearch([parent_source])
    settings = Settings(RAG_PARENT_EXPANSION_ENABLED=True)
    expander = MarkdownParentContextExpander(settings, client)
    filters = RetrievalFilters(
        user_id="user-1",
        department_codes=["engineering"],
        allow_public=True,
    )
    expanded = await expander.expand(retrieved, filters)
    assert len(expanded) == 1
    assert expanded[0].id == parent.id
    assert expanded[0].metadata["chunk_level"] == "parent"
    assert expanded[0].metadata["matched_child_ids"] == [doc.id for doc in retrieved]
    assert client.calls and "query" in client.calls[0]
    query_filters = client.calls[0]["query"]["bool"]["filter"]
    assert {"ids": {"values": [parent.id]}} in query_filters
    assert any(
        clause.get("bool", {}).get("minimum_should_match") == 1
        for clause in query_filters
    )

    guard = RecordingGuard()
    context = await assemble_rag_context(
        settings=settings,
        query="question",
        docs=retrieved,
        filters={
            "user_id": "user-1",
            "department_codes": ["engineering"],
            "allow_public": True,
        },
        source="test.parent_guard",
        parent_expander=expander,
        prompt_guard=guard,
    )
    assert guard.contents == [parent.content]
    unhit_marker = next(
        line
        for line in all_parent_children[2].content.splitlines()
        if line.strip()
        and line in parent.content
        and all(line not in doc.content for doc in retrieved)
    )
    assert unhit_marker in guard.contents[0]
    assert context.docs[0].id == parent.id
    assert parent.content in context.context_text
    source = docs_to_sources(context.docs)[0]
    assert source.id == parent.id
    assert source.parent_id == parent.id
    assert source.chunk_level == "parent"
    assert source.matched_child_ids == [doc.id for doc in retrieved]
    assert all_parent_children[2].id not in source.matched_child_ids

    missing = MarkdownParentContextExpander(
        settings,
        FakeElasticsearch([]),
    )
    fallback = await missing.expand(retrieved, filters)
    assert len(fallback) == 1
    assert fallback[0].metadata["chunk_level"] == "child"
    assert fallback[0].metadata["parent_expansion_degraded"] is True

    mismatched_source = deepcopy(parent_source)
    mismatched_source["metadata"]["chunk_strategy_version"] = "stale"
    mismatched = MarkdownParentContextExpander(
        settings,
        FakeElasticsearch([mismatched_source]),
    )
    version_fallback = await mismatched.expand(retrieved, filters)
    assert version_fallback[0].metadata["parent_expansion_degraded"] is True

    pipeline_settings = Settings(
        RAG_PARENT_EXPANSION_ENABLED=True,
        LANGSMITH_TRACING=False,
    )
    req = RagChatRequest(query="question")
    shared_client = FakeElasticsearch([parent_source])
    shared_expander = MarkdownParentContextExpander(
        pipeline_settings,
        shared_client,
    )
    classic = RagPipeline(
        settings=pipeline_settings,
        vector_retriever=None,  # type: ignore[arg-type]
        keyword_retriever=None,  # type: ignore[arg-type]
        llm_client=None,  # type: ignore[arg-type]
        reranker=None,  # type: ignore[arg-type]
        prompt_guard=None,
        parent_expander=shared_expander,
    )
    classic_context = await classic._assemble_context(
        req,
        retrieved,
        source="classic.test",
    )
    graph_state = build_graph_initial_state(req, "run")
    graph_state["docs"] = retrieved
    graph_result = await create_build_context_node(
        settings=pipeline_settings,
        parent_expander=shared_expander,
    )(graph_state)
    agent_state = build_rag_agent_initial_state(req, "run")
    agent_state["docs"] = retrieved
    agent_result = await create_agent_build_context_node(
        settings=pipeline_settings,
        parent_expander=shared_expander,
    )(agent_state)
    assert [
        source.id
        for source in docs_to_sources(classic_context.docs)
    ] == [
        source.id
        for source in docs_to_sources(graph_result["docs"])
    ] == [
        source.id
        for source in docs_to_sources(agent_result["docs"])
    ] == [parent.id]

    legacy_graph_state = build_graph_initial_state(req, "stream")
    legacy_graph_state["docs"] = retrieved
    legacy_graph_result = await create_build_context_node(
        settings=pipeline_settings,
        parent_expander=shared_expander,
    )(legacy_graph_state)
    legacy_agent_state = build_rag_agent_initial_state(req, "stream")
    legacy_agent_state["docs"] = retrieved
    legacy_agent_result = await create_agent_build_context_node(
        settings=pipeline_settings,
        parent_expander=shared_expander,
    )(legacy_agent_state)
    legacy_classic = await classic._assemble_context(
        req,
        retrieved,
        source="classic.legacy_stream.test",
        expand_parents=False,
    )
    assert [doc.id for doc in legacy_classic.docs] == [
        doc.id for doc in legacy_graph_result["docs"]
    ] == [doc.id for doc in legacy_agent_result["docs"]] == [
        doc.id for doc in retrieved
    ]


async def main() -> None:
    test_builder()
    test_empty_heading_sections()
    test_stable_ids()
    test_store_contract()
    await test_expansion_and_context()
    print("markdown parent-child checks passed")


if __name__ == "__main__":
    asyncio.run(main())
