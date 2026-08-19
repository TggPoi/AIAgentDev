"""案例演示：character-art-style.md 在 v2 策略下的真实切块产出。

用法（工程根目录 python-agent-study 下执行）：
    $env:PYTHONPATH = "src"; .\.venv\Scripts\python.exe .\.tmp\demo_art_style_v2.py

只读验证，不写任何数据库。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.domain.knowledge_models import LoadedDocument
from fast_app.ingestion.processing.markdown_hierarchy import (
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
)


def main() -> None:
    path = ROOT / "docs" / "knowledge-base-acl-test" / "art" / "character-art-style.md"
    content = path.read_text(encoding="utf-8")
    document = LoadedDocument(
        source_path="docs/knowledge-base-acl-test/art/character-art-style.md",
        content=content,
        document_type="markdown",
        metadata={"doc_id": "demo-art-style"},
    )
    builder = MarkdownHierarchyBuilder()

    sections = builder._parse_sections(document)
    print(f"=== 章节数: {len(sections)} ===")
    for section in sections:
        heading_only = all(b.kind == "heading" for b in section.blocks)
        print(
            f"Section{section.section_index} path={section.section_path} "
            f"blocks={len(section.blocks)} 仅标题={heading_only}"
        )

    options = MarkdownHierarchyOptions(source="art-demo")
    result = builder.build([document], options)
    print(f"\n=== 父块数: {len(result.parents)} 子块数: {len(result.children)} ===")
    for parent in result.parents:
        tokens = builder.token_counter.count(parent.content)
        first_line = parent.content.splitlines()[0]
        print(f"父块 tokens={tokens} 首行={first_line!r}")
    print()
    for child in result.children:
        tokens = builder.token_counter.count(child.content)
        lines = child.content.splitlines()
        print(f"子块 tokens={tokens} 面包屑={lines[0]!r}")
        body_first = lines[2] if len(lines) > 2 else ""
        print(f"        正文首行={body_first!r}")


if __name__ == "__main__":
    main()
