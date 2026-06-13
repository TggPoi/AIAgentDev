import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from elasticsearch import AsyncElasticsearch
from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.embeddings.qwen_embedding_client import QwenEmbeddingClient
from fast_app.components.retrievers.milvus_vector_retriever import build_milvus_uri
from fast_app.core.config import Settings, get_settings
from fast_app.domain.knowledge_models import KnowledgeChunk
from fast_app.ingestion.chunk_builders import ChunkBuildOptions, MarkdownChunkBuilder
from fast_app.ingestion.markdown_chunker import read_markdown_documents
from fast_app.ingestion.markdown_ingestion_service import MarkdownIngestionService


class MockEmbeddingClient(BaseEmbeddingClient):
    def __init__(self, dim: int):
        self.dim = dim

    async def embed_query(self, text: str) -> list[float]:
        return self._vector_for_text(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for_text(text) for text in texts]

    def _vector_for_text(self, text: str) -> list[float]:
        seed = sum(ord(char) for char in text) or 1
        return [((seed + index) % 997) / 997 for index in range(self.dim)]


def apply_arg_overrides(args: argparse.Namespace) -> None:
    # 避免 .env 中 DEBUG=release 这类非布尔值影响脚本加载 Settings。
    os.environ["DEBUG"] = "true"

    if args.knowledge_base_dir:
        os.environ["KNOWLEDGE_BASE_DIR"] = args.knowledge_base_dir
    if args.source_name:
        os.environ["INGESTION_SOURCE_NAME"] = args.source_name
    if args.max_chars is not None:
        os.environ["MARKDOWN_CHUNK_MAX_CHARS"] = str(args.max_chars)
    if args.overlap_chars is not None:
        os.environ["MARKDOWN_CHUNK_OVERLAP_CHARS"] = str(args.overlap_chars)
    if args.max_tokens is not None:
        os.environ["MARKDOWN_CHUNK_MAX_TOKENS"] = str(args.max_tokens)
    if args.min_chars is not None:
        os.environ["MARKDOWN_CHUNK_MIN_CHARS"] = str(args.min_chars)

    get_settings.cache_clear()


def assert_markdown_documents(settings: Settings) -> None:
    root = Path(settings.knowledge_base_dir)

    if not root.exists():
        raise AssertionError(f"knowledge base dir does not exist: {root}")

    if not root.is_dir():
        raise AssertionError(f"knowledge base path is not directory: {root}")


def assert_chunks(chunks: list[KnowledgeChunk]) -> None:
    if not chunks:
        raise AssertionError("expected non-empty chunks")

    ids = [chunk.id for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise AssertionError("expected stable unique chunk ids")

    for chunk in chunks:
        if not chunk.id:
            raise AssertionError("expected chunk.id")
        if not chunk.content.strip():
            raise AssertionError(f"expected non-empty content: {chunk.id}")
        if not chunk.title:
            raise AssertionError(f"expected chunk.title: {chunk.id}")
        if not chunk.source:
            raise AssertionError(f"expected chunk.source: {chunk.id}")

        chunk_id = chunk.metadata.get("chunk_id")
        if chunk_id != chunk.id:
            raise AssertionError(f"expected metadata.chunk_id to equal chunk.id: {chunk.id}")

        metadata_title = chunk.metadata.get("title")
        if metadata_title != chunk.title:
            raise AssertionError(
                f"expected metadata.title to equal chunk.title: {chunk.id}"
            )

        doc_id = chunk.metadata.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id.startswith("doc_"):
            raise AssertionError(f"expected metadata.doc_id: {chunk.id}")

        section_path = chunk.metadata.get("section_path")
        if not isinstance(section_path, list) or not section_path:
            raise AssertionError(f"expected metadata.section_path list: {chunk.id}")

        source_path = chunk.metadata.get("source_path")
        if not isinstance(source_path, str) or not source_path:
            raise AssertionError(f"expected metadata.source_path string: {chunk.id}")

        document_type = chunk.metadata.get("document_type")
        if document_type not in {"markdown", "text", "pdf"}:
            raise AssertionError(f"expected metadata.document_type: {chunk.id}")

        file_name = chunk.metadata.get("file_name")
        if not isinstance(file_name, str) or not file_name:
            raise AssertionError(f"expected metadata.file_name string: {chunk.id}")

        file_extension = chunk.metadata.get("file_extension")
        if not isinstance(file_extension, str) or not file_extension:
            raise AssertionError(
                f"expected metadata.file_extension string: {chunk.id}"
            )

        chunk_index = chunk.metadata.get("chunk_index")
        if not isinstance(chunk_index, int) or chunk_index < 1:
            raise AssertionError(f"expected metadata.chunk_index positive int: {chunk.id}")


def print_chunk_summary(
    settings: Settings,
    chunks: list[KnowledgeChunk],
    sample_size: int,
) -> None:
    print("========== Markdown ingestion dry run ==========")
    print(f"knowledge_base_dir: {settings.knowledge_base_dir}")
    print(f"source_name: {settings.ingestion_source_name}")
    print(f"max_chars: {settings.markdown_chunk_max_chars}")
    print(f"overlap_chars: {settings.markdown_chunk_overlap_chars}")
    print(f"max_tokens: {settings.markdown_chunk_max_tokens}")
    print(f"min_chars: {settings.markdown_chunk_min_chars}")
    print(f"chunk_count: {len(chunks)}")

    print("\nchunk samples:")
    for chunk in chunks[:sample_size]:
        sample = {
            "id": chunk.id,
            "title": chunk.title,
            "source": chunk.source,
            "content_preview": " ".join(chunk.content.split())[:120],
            "metadata": chunk.metadata,
        }
        print(json.dumps(sample, ensure_ascii=False, indent=2))


def build_chunks(settings: Settings) -> list[KnowledgeChunk]:
    assert_markdown_documents(settings)

    documents = read_markdown_documents(settings.knowledge_base_dir)
    if not documents:
        raise AssertionError(
            f"expected at least one .md file under {settings.knowledge_base_dir}"
        )

    chunks = MarkdownChunkBuilder().build(
        documents=documents,
        options=ChunkBuildOptions(
            source=settings.ingestion_source_name,
            max_chars=settings.markdown_chunk_max_chars,
            overlap_chars=settings.markdown_chunk_overlap_chars,
            max_tokens=settings.markdown_chunk_max_tokens,
            min_chars=settings.markdown_chunk_min_chars,
        ),
    )
    assert_chunks(chunks)
    return chunks


async def run_dry_run(settings: Settings, sample_size: int) -> None:
    chunks = build_chunks(settings)
    print_chunk_summary(settings, chunks, sample_size)


def build_embedding_client(
    settings: Settings,
    use_mock_embeddings: bool,
) -> BaseEmbeddingClient:
    if use_mock_embeddings:
        return MockEmbeddingClient(dim=settings.embedding_dim)

    return QwenEmbeddingClient(settings=settings)


async def run_write_stores(args: argparse.Namespace, settings: Settings) -> None:
    if not args.yes:
        raise AssertionError(
            "writing stores will delete and recreate current ES index and Milvus "
            "collection; pass --yes to confirm"
        )

    print("========== Markdown ingestion write stores ==========")
    print(f"ES URL: {settings.elasticsearch_url}")
    print(f"ES index: {settings.elasticsearch_index_name}")
    print(f"Milvus URI: {build_milvus_uri(settings.milvus_host, settings.milvus_port)}")
    print(f"Milvus collection: {settings.milvus_collection_name}")
    print(f"Embedding model: {settings.embedding_model_name}")
    print(f"Embedding dim: {settings.embedding_dim}")
    print(f"use_mock_embeddings: {args.mock_embeddings}")

    elasticsearch_client = AsyncElasticsearch(hosts=[settings.elasticsearch_url])
    milvus_client = MilvusClient(
        uri=build_milvus_uri(settings.milvus_host, settings.milvus_port)
    )

    try:
        service = MarkdownIngestionService(
            settings=settings,
            embedding_client=build_embedding_client(settings, args.mock_embeddings),
            elasticsearch_client=elasticsearch_client,
            milvus_client=milvus_client,
        )
        result = await service.ingest()

        print("\ningestion result:")
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))

        if result.document_count < 1:
            raise AssertionError("expected document_count >= 1")
        if result.chunk_count < 1:
            raise AssertionError("expected chunk_count >= 1")
        if result.es_success_count != result.chunk_count:
            raise AssertionError(
                "expected es_success_count to equal chunk_count: "
                f"{result.es_success_count} != {result.chunk_count}"
            )

    finally:
        await elasticsearch_client.close()
        milvus_client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test Markdown ingestion chunking and optional ES/Milvus writes.",
    )
    parser.add_argument(
        "--knowledge-base-dir",
        default=None,
        help="覆盖 KNOWLEDGE_BASE_DIR，默认读取 Settings。",
    )
    parser.add_argument(
        "--source-name",
        default=None,
        help="覆盖 INGESTION_SOURCE_NAME，默认读取 Settings。",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=None,
        help="覆盖 MARKDOWN_CHUNK_MAX_CHARS，默认读取 Settings。",
    )
    parser.add_argument(
        "--overlap-chars",
        type=int,
        default=None,
        help="覆盖 MARKDOWN_CHUNK_OVERLAP_CHARS，默认读取 Settings。",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="覆盖 MARKDOWN_CHUNK_MAX_TOKENS，默认读取 Settings。",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=None,
        help="覆盖 MARKDOWN_CHUNK_MIN_CHARS，默认读取 Settings。",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=3,
        help="dry-run 时打印多少个 chunk 样例。",
    )
    parser.add_argument(
        "--write-stores",
        action="store_true",
        help="执行真实 ES/Milvus 删除重建和写入。",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认允许删除并重建当前配置中的 ES index 和 Milvus collection。",
    )
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="写入 ES/Milvus 时使用本地 mock embedding，避免调用真实 embedding 服务。",
    )
    return parser.parse_args()


async def main_async() -> int:
    args = parse_args()
    apply_arg_overrides(args)
    settings = get_settings()

    try:
        await run_dry_run(settings, args.sample_size)

        if args.write_stores:
            await run_write_stores(args, settings)

        return 0

    except AssertionError as exc:
        print(f"\n测试断言失败: {exc}", file=sys.stderr)
        return 1

    except Exception as exc:
        print(f"\n测试执行失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
