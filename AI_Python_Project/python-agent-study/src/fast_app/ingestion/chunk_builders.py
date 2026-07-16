from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fast_app.domain.knowledge_models import KnowledgeChunk, LoadedDocument
from fast_app.ingestion.markdown_chunker import parse_heading
from fast_app.ingestion.metadata_models import (
    build_chunk_id,
    build_chunk_metadata,
    build_document_metadata,
)

# 构造chunk的可选配置
@dataclass(frozen=True)
class ChunkBuildOptions:
    source: str
    max_chars: int
    overlap_chars: int
    max_tokens: int
    min_chars: int

# 一个 Markdown 文档中的一个章节
@dataclass(frozen=True)
class MarkdownSection:
    source_path: str
    document_type: str
    document_metadata: dict[str, Any]
    section_path: list[str]
    heading_level: int
    section_index: int
    content: str

# 先让 ChunkBuilder 具备 token 长度控制入口。后续可以替换成真实 tokenizer
class SimpleTokenCounter:
    def count(self, text: str) -> int:
        ascii_count = sum(1 for char in text if ord(char) < 128)
        non_ascii_count = len(text) - ascii_count
        return ascii_count // 4 + non_ascii_count

# 支持 overlap支持 min_chars支持 token 估算边界
class TextSplitter:
    def __init__(self, token_counter: SimpleTokenCounter | None = None):
        self.token_counter = token_counter or SimpleTokenCounter()

    def split(self, text: str, options: ChunkBuildOptions) -> list[str]:
        normalized = text.strip()

        if not normalized:
            return []

        if (
            len(normalized) <= options.max_chars
            and self.token_counter.count(normalized) <= options.max_tokens
        ):
            return [normalized]
        # 正文内容过长，进行切割工作
        parts: list[str] = []
        window_size = self._window_size(options)
        overlap_chars = max(0, min(options.overlap_chars, window_size - 1))
        step = max(1, window_size - overlap_chars)
        start = 0

        while start < len(normalized):
            part = normalized[start : start + window_size].strip()
            if len(part) >= options.min_chars:
                parts.append(part)
            start += step

        return parts
    # 获取滑动窗口 当前窗口要滑动的字符距离
    def _window_size(self, options: ChunkBuildOptions) -> int:
        return max(
            1,
            options.min_chars,
            min(options.max_chars, options.max_tokens),
        )


class MarkdownChunkBuilder:
    def __init__(self, splitter: TextSplitter | None = None):
        self.splitter = splitter or TextSplitter()

    def build(
        self,
        documents: list[LoadedDocument],
        options: ChunkBuildOptions,
    ) -> list[KnowledgeChunk]:
        chunks: list[KnowledgeChunk] = []

        for document in documents:
            sections = self._build_sections(document)
            chunk_index = 0

            for section in sections:
                parts = self.splitter.split(section.content, options)

                for part in parts:
                    chunk_index += 1
                    chunks.append(
                        self._build_chunk(
                            section=section,
                            options=options,
                            content=part,
                            chunk_index=chunk_index,
                        )
                    )

        return chunks

    def _build_sections(self, document: LoadedDocument) -> list[MarkdownSection]:
        sections: list[MarkdownSection] = []
        heading_stack: list[tuple[int, str]] = []
        section_lines: list[str] = []
        section_index = 0
        current_title = Path(document.source_path).stem
        current_heading_level = 0

        def flush_section() -> None:
            content = "\n".join(section_lines).strip()

            if not content:
                return

            section_path = [title for _, title in heading_stack] or [current_title]

            sections.append(
                MarkdownSection(
                    source_path=document.source_path,
                    document_type=document.document_type,
                    document_metadata=self._document_metadata(document),
                    section_path=section_path,
                    heading_level=current_heading_level,
                    section_index=section_index,
                    content=content,
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
                # 按标题级别而非列表长度回退；文档即使从 ## 开始，同级标题也不会嵌套。
                heading_stack = [item for item in heading_stack if item[0] < level]
                heading_stack.append((level, title))
                continue

            section_lines.append(line)

        flush_section()
        return sections

    def _build_chunk(
        self,
        section: MarkdownSection,
        options: ChunkBuildOptions,
        content: str,
        chunk_index: int,
    ) -> KnowledgeChunk:
        doc_id = str(section.document_metadata["doc_id"])
        title = section.section_path[-1]
        chunk_id = build_chunk_id(
            doc_id=doc_id,
            section_path=section.section_path,
            chunk_index=chunk_index,
        )

        return KnowledgeChunk(
            id=chunk_id,
            content=content,
            source=options.source,
            title=title,
            metadata=build_chunk_metadata(
                document_metadata=section.document_metadata,
                chunk_id=chunk_id,
                title=title,
                section_path=section.section_path,
                heading_level=section.heading_level,
                section_index=section.section_index,
                chunk_index=chunk_index,
            ),
        )

    def _document_metadata(self, document: LoadedDocument) -> dict[str, Any]:
        metadata = dict(document.metadata)

        if "doc_id" not in metadata:
            metadata.update(
                build_document_metadata(
                    source_path=document.source_path,
                    document_type=document.document_type,
                )
            )

        return metadata
