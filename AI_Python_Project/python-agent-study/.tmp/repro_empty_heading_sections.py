"""复现缺陷：空标题章节（一级标题下无正文直接接二级标题）。

用法（工程根目录 python-agent-study 下执行）：
    $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe .\.tmp\repro_empty_heading_sections.py

只读验证：调用真实的 MarkdownHierarchyBuilder，打印 section / 父块 / 子块产出，
不写任何数据库。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fast_app.domain.knowledge_models import LoadedDocument
from fast_app.ingestion.processing.markdown_hierarchy import (
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
)


CASE_A = """# 部署指南
## 回滚操作
出现问题时执行回滚。
1. 停止服务
## 监控
观察错误率指标。
"""

CASE_B = """# 一级空
## 二级空
### 三级有正文
这一节才有内容。
"""

CASE_C = """# 只有一个空标题
"""


def run_case(name: str, content: str) -> None:
    print("=" * 70)
    print(f"用例 {name}")
    print("=" * 70)
    document = LoadedDocument(
        source_path=f"docs/{name}.md",
        content=content,
        document_type="markdown",
        metadata={"doc_id": f"doc-{name}"},
    )
    builder = MarkdownHierarchyBuilder()

    sections = builder._parse_sections(document)  # 仅诊断用途：观察章节切分
    print(f"--- _parse_sections 产出 {len(sections)} 个章节 ---")
    for section in sections:
        body_tokens = sum(
            builder.token_counter.count(b.content)
            for b in section.blocks
            if b.kind != "heading"
        )
        heading_only = all(b.kind == "heading" for b in section.blocks)
        print(
            f"  Section{section.section_index} path={section.section_path} "
            f"blocks={len(section.blocks)} 正文token={body_tokens} "
            f"仅含标题={heading_only}"
        )

    options = MarkdownHierarchyOptions(source=f"repro-{name}")
    result = builder.build([document], options)
    print(f"--- build 产出 父块={len(result.parents)} 子块={len(result.children)} ---")
    for parent in result.parents:
        print(
            f"  父块 id={parent.id[:12]} tokens={builder.token_counter.count(parent.content)} "
            f"content={parent.content!r}"
        )
    for child in result.children:
        print(
            f"  子块 id={child.id[:12]} tokens={builder.token_counter.count(child.content)} "
            f"content={child.content!r}"
        )
        print(f"          search_text={child.search_text!r}")
    print()


if __name__ == "__main__":
    run_case("A-一级标题空正文", CASE_A)
    run_case("B-连续多级空标题", CASE_B)
    run_case("C-全文只有一个空标题", CASE_C)
