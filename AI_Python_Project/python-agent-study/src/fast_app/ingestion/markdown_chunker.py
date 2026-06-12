import hashlib
from pathlib import Path

from fast_app.domain.knowledge_models import KnowledgeChunk, MarkdownDocument

# 从知识库目录递归读取 .md 文件 保留 source_path 使用 UTF-8 读取中文 Markdown 返回原始 MarkdownDocument
def read_markdown_documents(base_dir: str) -> list[MarkdownDocument]:
    root = Path(base_dir)
    documents: list[MarkdownDocument] = []

    for path in sorted(root.rglob("*.md")):
        documents.append(
            MarkdownDocument(
                source_path=path.as_posix(),
                content=path.read_text(encoding="utf-8"),
            )
        )

    return documents

# 标题识别 helper
def parse_heading(line: str) -> tuple[int, str] | None:
    stripped = line.strip()

    if not stripped.startswith("#"):
        return None

    marker, _, title = stripped.partition(" ")

    if not marker or set(marker) != {"#"}:
        return None

    level = len(marker)

    if level < 1 or level > 6 or not title.strip():
        return None

    return level, title.strip()

# 稳定 id helper ；同一份 Markdown 在相同章节位置生成的 chunk id 稳定
def build_chunk_id(source_path: str, section_path: list[str], chunk_index: int) -> str:
    raw = "|".join([source_path, *section_path, str(chunk_index)])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"md_{digest}"

# 简易版本的切分函数
def split_text(text: str, max_chars: int) -> list[str]:
    normalized = text.strip()

    if len(normalized) <= max_chars:
        return [normalized]

    parts: list[str] = []
    start = 0

    while start < len(normalized):
        part = normalized[start : start + max_chars].strip()
        if part:
            parts.append(part)
        start += max_chars

    return parts


# chunk拆分
def build_markdown_chunks(
    documents: list[MarkdownDocument],
    source: str,
    max_chars: int,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []

    for document in documents:
        heading_stack: list[str] = []
        section_lines: list[str] = []
        section_index = 0
        chunk_index = 0
        current_title = Path(document.source_path).stem
        current_heading_level = 0

        def flush_section() -> None:
            nonlocal chunk_index

            content = "\n".join(section_lines).strip()
            if not content:
                return

            for part in split_text(content, max_chars):
                chunk_index += 1
                section_path = heading_stack[:] or [current_title]

                chunks.append(
                    KnowledgeChunk(
                        id=build_chunk_id(
                            source_path=document.source_path,
                            section_path=section_path,
                            chunk_index=chunk_index,
                        ),
                        content=part,
                        source=source,
                        title=section_path[-1],
                        metadata={
                            "section_path": section_path,
                            "heading_level": current_heading_level,
                            "section_index": section_index,
                            "chunk_index": chunk_index,
                            "source_path": document.source_path,
                        },
                    )
                )

        for line in document.content.splitlines():
            heading = parse_heading(line)

            if heading is not None:
                flush_section()
                section_lines = []
                section_index += 1

                level, title = heading
                current_heading_level = level
                current_title = title
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(title)
                continue

            section_lines.append(line)

        flush_section()

    return chunks