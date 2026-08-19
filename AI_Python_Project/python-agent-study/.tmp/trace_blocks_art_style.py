"""教学取数：打印"3. 面部与表情规范"章节的逐 block token 数，用于装箱推演。"""

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
    section = next(s for s in sections if s.section_path[-1] == "3. 面部与表情规范")

    prefix = builder._breadcrumb(section.section_path)
    prefix_tokens = builder.token_counter.count(prefix)
    print(f"面包屑 prefix = {prefix!r}")
    print(f"prefix_tokens = {prefix_tokens}")
    print()

    total = 0
    for i, block in enumerate(section.blocks, start=1):
        tokens = builder.token_counter.count(block.content)
        total += tokens
        head = block.content.splitlines()[0][:30]
        print(f"block{i:>2} kind={block.kind:<18} tokens={tokens:>3}  首行={head!r}")
    print(f"\n全部 block token 总和 = {total}")

    options = MarkdownHierarchyOptions(source="art-demo")
    print(f"\n父块有效预算: target={options.parent_target_tokens - prefix_tokens} "
          f"max={options.parent_max_tokens - prefix_tokens}")
    print(f"子块有效预算: target={options.child_target_tokens - prefix_tokens} "
          f"max={options.child_max_tokens - prefix_tokens}")


if __name__ == "__main__":
    main()
