from dataclasses import dataclass
from pathlib import Path
import re

from fast_app.domain.knowledge_models import KnowledgeChunk


DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


@dataclass
class MarkdownSection:
    title: str
    level: int
    section_path: list[str]
    content: str


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def read_markdown_file(file_path: str | Path) -> str:
    return Path(file_path).read_text(encoding="utf-8")


def split_markdown_into_sections(markdown_text: str) -> list[MarkdownSection]:
    lines = markdown_text.splitlines()

    sections: list[MarkdownSection] = []
    heading_stack: list[tuple[int, str]] = []

    current_title = "ROOT"
    current_level = 0
    current_content_lines: list[str] = []
    current_path: list[str] = []

    def flush_current_section() -> None:
        content = "\n".join(current_content_lines).strip()

        if not content:
            return

        sections.append(
            MarkdownSection(
                title=current_title,
                level=current_level,
                section_path=current_path.copy(),
                content=content,
            )
        )

    for line in lines:
        match = HEADING_PATTERN.match(line)

        if not match:
            current_content_lines.append(line)
            continue

        flush_current_section()

        hashes, title = match.groups()
        level = len(hashes)
        title = title.strip()

        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()

        heading_stack.append((level, title))

        current_title = title
        current_level = level
        current_path = [item[1] for item in heading_stack]
        current_content_lines = []

    flush_current_section()

    return sections


def split_text_with_overlap(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    text = text.strip()

    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(0, end - chunk_overlap)

    return chunks


def build_chunk_id(
    source_stem: str,
    section_index: int,
    chunk_index: int,
) -> str:
    return f"{source_stem}_s{section_index:03d}_c{chunk_index:03d}"


def build_chunks_from_markdown(
    file_path: str | Path,
    source: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[KnowledgeChunk]:
    path = Path(file_path)
    markdown_text = read_markdown_file(path)
    sections = split_markdown_into_sections(markdown_text)

    source_name = source or str(path)
    source_stem = path.stem

    chunks: list[KnowledgeChunk] = []

    for section_index, section in enumerate(sections, start=1):
        section_chunks = split_text_with_overlap(
            text=section.content,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        for chunk_index, chunk_text in enumerate(section_chunks, start=1):
            chunk_id = build_chunk_id(
                source_stem=source_stem,
                section_index=section_index,
                chunk_index=chunk_index,
            )

            section_path_text = " / ".join(section.section_path)

            content = (
                f"标题路径：{section_path_text}\n\n"
                f"{chunk_text}"
            )

            chunks.append(
                KnowledgeChunk(
                    id=chunk_id,
                    content=content,
                    source=source_name,
                    title=section.title,
                    metadata={
                        "section_path": section.section_path,
                        "heading_level": section.level,
                        "section_index": section_index,
                        "chunk_index": chunk_index,
                    },
                )
            )

    return chunks