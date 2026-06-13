import hashlib

from fast_app.domain.knowledge_models import KnowledgeChunk, LoadedDocument
from fast_app.ingestion.document_loaders import MarkdownDocumentLoader

def read_markdown_documents(base_dir: str) -> list[LoadedDocument]:
    return MarkdownDocumentLoader().load(base_dir)

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
    from fast_app.ingestion.chunk_builders import ChunkBuildOptions, TextSplitter

    return TextSplitter().split(
        text=text,
        options=ChunkBuildOptions(
            source="compat",
            max_chars=max_chars,
            overlap_chars=0,
            max_tokens=10_000,
            min_chars=1,
        ),
    )


# chunk拆分
def build_markdown_chunks(
    documents: list[LoadedDocument],
    source: str,
    max_chars: int,
) -> list[KnowledgeChunk]:
    from fast_app.ingestion.chunk_builders import (
        ChunkBuildOptions,
        MarkdownChunkBuilder,
    )

    return MarkdownChunkBuilder().build(
        documents=documents,
        options=ChunkBuildOptions(
            source=source,
            max_chars=max_chars,
            overlap_chars=0,
            max_tokens=10_000,
            min_chars=1,
        ),
    )
