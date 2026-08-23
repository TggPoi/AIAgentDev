import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from elasticsearch import AsyncElasticsearch
from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.embeddings.mock_embedding_client import MockEmbeddingClient
from fast_app.components.embeddings.qwen_embedding_client import QwenEmbeddingClient
from fast_app.core.config import Settings, get_settings
from fast_app.domain.knowledge_models import KnowledgeChunk, LoadedDocument
from fast_app.ingestion.processing.chunk_builders import ChunkBuildOptions, MarkdownChunkBuilder
from fast_app.ingestion.processing.markdown_hierarchy import (
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
    MarkdownParentChunk,
)
from fast_app.ingestion.processing.document_loaders import (
    build_default_document_loader,
)
from fast_app.ingestion.markdown_ingestion_service import MarkdownIngestionService
from fast_app.ingestion.validation.ingestion_validation import validate_ingestion_result
from fast_app.ingestion.stores.rag_store_admin import StoreResetOptions, reset_rag_stores
from fast_app.db.session import create_database_engine
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock


def apply_arg_overrides(args: argparse.Namespace) -> None:
    # 当前工程的 .env 可能出现 DEBUG=release，CLI 不依赖 debug 语义，统一转成可解析布尔值。
    os.environ["DEBUG"] = "true"
    # 命令行参数名：--knowledge-base-dir 其中的 - 符号会被argparse解析为 _ 
    if getattr(args, "knowledge_base_dir", None):
        os.environ["KNOWLEDGE_BASE_DIR"] = args.knowledge_base_dir
    if getattr(args, "source_name", None):
        os.environ["INGESTION_SOURCE_NAME"] = args.source_name
    if getattr(args, "write_mode", None):
        os.environ["INGESTION_WRITE_MODE"] = args.write_mode
    if getattr(args, "elasticsearch_index_name", None):
        os.environ["ELASTICSEARCH_INDEX_NAME"] = args.elasticsearch_index_name
    if getattr(args, "milvus_collection_name", None):
        os.environ["MILVUS_COLLECTION_NAME"] = args.milvus_collection_name
    if getattr(args, "max_chars", None) is not None:
        os.environ["MARKDOWN_CHUNK_MAX_CHARS"] = str(args.max_chars)
    if getattr(args, "overlap_chars", None) is not None:
        os.environ["MARKDOWN_CHUNK_OVERLAP_CHARS"] = str(args.overlap_chars)
    if getattr(args, "max_tokens", None) is not None:
        os.environ["MARKDOWN_CHUNK_MAX_TOKENS"] = str(args.max_tokens)
    if getattr(args, "min_chars", None) is not None:
        os.environ["MARKDOWN_CHUNK_MIN_CHARS"] = str(args.min_chars)
    for argument, environment_name in (
        ("parent_target_tokens", "MARKDOWN_PARENT_TARGET_TOKENS"),
        ("parent_max_tokens", "MARKDOWN_PARENT_MAX_TOKENS"),
        ("parent_max_chars", "MARKDOWN_PARENT_MAX_CHARS"),
        ("child_target_tokens", "MARKDOWN_CHILD_TARGET_TOKENS"),
        ("child_max_tokens", "MARKDOWN_CHILD_MAX_TOKENS"),
        ("child_min_tokens", "MARKDOWN_CHILD_MIN_TOKENS"),
        ("child_overlap_tokens", "MARKDOWN_CHILD_OVERLAP_TOKENS"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            os.environ[environment_name] = str(value)
    if getattr(args, "no_es_auth", False):
        os.environ["ELASTICSEARCH_USERNAME"] = ""
        os.environ["ELASTICSEARCH_PASSWORD"] = ""

    # get_settings() 使用了 @lru_cache。
    # 修改 os.environ 后必须清缓存，否则后续拿到的可能还是旧 Settings。
    get_settings.cache_clear()


def build_milvus_uri(settings: Settings) -> str:
    return f"http://{settings.milvus_host}:{settings.milvus_port}"


def build_elasticsearch_client(settings: Settings) -> AsyncElasticsearch:
    # CLI 没有 FastAPI app.state，所以需要自己创建 ES client。
    # 这里集中处理 URL、超时和可选 basic_auth，避免每个子命令重复写连接逻辑。
    kwargs: dict[str, Any] = {
        "hosts": [settings.elasticsearch_url],
        "request_timeout": settings.elasticsearch_request_timeout,
    }

    username = settings.elasticsearch_username.strip()
    password = settings.elasticsearch_password.strip()
    # 目前本地开发环境没有开启认证
    if bool(username) != bool(password):
        raise RuntimeError(
            "ELASTICSEARCH_USERNAME 和 ELASTICSEARCH_PASSWORD 必须同时配置。"
            "如果本地 ES 没有开启认证，请在 CLI 命令中添加 --no-es-auth。"
        )

    if username and password:
        _validate_ascii_basic_auth(
            username=username,
            password=password,
        )
        kwargs["basic_auth"] = (
            username,
            password,
        )

    return AsyncElasticsearch(**kwargs)


def _validate_ascii_basic_auth(username: str, password: str) -> None:
    try:
        f"{username}:{password}".encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            "Elasticsearch basic_auth 只能使用 ASCII 字符。"
            "当前 ELASTICSEARCH_USERNAME 或 ELASTICSEARCH_PASSWORD 包含中文或其他非 ASCII 字符。"
            "如果本地 ES 没有开启认证，请在 CLI 命令中添加 --no-es-auth；"
            "如果开启了认证，请把 .env 中的 ES 用户名和密码改成实际 ASCII 凭据。"
        ) from exc


def build_milvus_client(settings: Settings) -> MilvusClient:
    # MilvusClient 是同步客户端，CLI 在需要写入或 reset 时创建，用完后显式 close。
    return MilvusClient(uri=build_milvus_uri(settings))


def build_embedding_client(
    settings: Settings,
    use_mock_embeddings: bool,
) -> BaseEmbeddingClient:
    # --mock-embeddings 用于本地验证写入链路。
    # 不传该参数时，使用真实 QwenEmbeddingClient。
    if use_mock_embeddings:
        return MockEmbeddingClient(dim=settings.embedding_dim)

    return QwenEmbeddingClient(settings=settings)


def build_chunks(
    settings: Settings,
) -> tuple[list[LoadedDocument], list[MarkdownParentChunk], list[KnowledgeChunk]]:
    # dry-run 和真实 ingestion 都需要先确认知识库目录存在。
    # 这里提前失败，比后面 loader 递归读取时才失败更容易定位问题。
    root = Path(settings.knowledge_base_dir)

    if not root.exists():
        raise RuntimeError(f"知识库目录不存在: {root}")

    if not root.is_dir():
        raise RuntimeError(f"知识库路径不是目录: {root}")

    document_loader = build_default_document_loader()
    # Loader 负责把本地文件读成 LoadedDocument。
    # ChunkBuilder 再负责把 LoadedDocument 切成 KnowledgeChunk。
    documents = document_loader.load(settings.knowledge_base_dir)
    markdown_documents = [
        document for document in documents if document.document_type == "markdown"
    ]
    legacy_documents = [
        document for document in documents if document.document_type != "markdown"
    ]
    hierarchy = MarkdownHierarchyBuilder().build(
        documents=markdown_documents,
        options=MarkdownHierarchyOptions(
            source=settings.ingestion_source_name,
            parent_target_tokens=settings.markdown_parent_target_tokens,
            parent_max_tokens=settings.markdown_parent_max_tokens,
            parent_max_chars=settings.markdown_parent_max_chars,
            child_target_tokens=settings.markdown_child_target_tokens,
            child_max_tokens=settings.markdown_child_max_tokens,
            child_min_tokens=settings.markdown_child_min_tokens,
            child_overlap_tokens=settings.markdown_child_overlap_tokens,
        ),
    )
    legacy_chunks = MarkdownChunkBuilder().build(
        documents=legacy_documents,
        options=ChunkBuildOptions(
            source=settings.ingestion_source_name,
            max_chars=settings.markdown_chunk_max_chars,
            overlap_chars=settings.markdown_chunk_overlap_chars,
            max_tokens=settings.markdown_chunk_max_tokens,
            min_chars=settings.markdown_chunk_min_chars,
        ),
    )

    return documents, hierarchy.parents, [*hierarchy.children, *legacy_chunks]


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


async def run_dry_run(args: argparse.Namespace, settings: Settings) -> int:
    # dry-run 只验证“读取 + 切分 + metadata”。
    # 它不会调用 embedding，也不会连接 ES / Milvus。
    documents, parents, chunks = build_chunks(settings)

    print_json(
        {
            "command": "dry-run",
            "knowledge_base_dir": settings.knowledge_base_dir,
            "source_name": settings.ingestion_source_name,
            "write_mode": settings.ingestion_write_mode,
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "parent_count": len(parents),
            "child_count": sum(
                chunk.metadata.get("record_type") == "markdown_child"
                for chunk in chunks
            ),
            "chunk_options": {
                "max_chars": settings.markdown_chunk_max_chars,
                "overlap_chars": settings.markdown_chunk_overlap_chars,
                "max_tokens": settings.markdown_chunk_max_tokens,
                "min_chars": settings.markdown_chunk_min_chars,
            },
            "sample_chunks": [
                {
                    "id": chunk.id,
                    "title": chunk.title,
                    "source": chunk.source,
                    "content_preview": " ".join(chunk.content.split())[:120],
                    "metadata": chunk.metadata,
                }
                for chunk in chunks[: args.sample_size]
            ],
            "sample_parents": [
                {
                    "id": parent.id,
                    "title": parent.title,
                    "content_preview": " ".join(parent.content.split())[:120],
                    "metadata": parent.metadata,
                }
                for parent in parents[: args.sample_size]
            ],
        }
    )
    return 0


async def run_validate(args: argparse.Namespace, settings: Settings) -> int:
    # validate 只验证本地文档读取、chunk 构造和 metadata 规范。
    # 它不调用 embedding，也不连接 ES / Milvus，适合作为阶段 10 的快速回归检查。
    documents, parents, chunks = build_chunks(settings)
    report = validate_ingestion_result(
        documents=documents,
        chunks=chunks,
        parents=parents,
    )

    print_json(
        {
            "command": "validate",
            "knowledge_base_dir": settings.knowledge_base_dir,
            "passed": report.passed,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "report": asdict(report),
        }
    )

    if not report.passed:
        return 1

    return 0


async def run_ingest(args: argparse.Namespace, settings: Settings) -> int:
    # ingest 会真实写入 ES / Milvus。
    # upsert / replace_docs 都会修改存储数据，recreate 还会删除重建结构，所以必须显式 --yes。
    if not args.yes:
        raise RuntimeError("执行真实 ingestion 需要显式传入 --yes")

    elasticsearch_client = build_elasticsearch_client(settings)
    milvus_client = build_milvus_client(settings)
    engine = create_database_engine(settings)

    try:
        # CLI 只负责创建依赖和调用 service。
        # 真正的 ingestion 主流程仍然放在 MarkdownIngestionService 中。
        service = MarkdownIngestionService(
            settings=settings,
            embedding_client=build_embedding_client(
                settings=settings,
                use_mock_embeddings=args.mock_embeddings,
            ),
            elasticsearch_client=elasticsearch_client,
            milvus_client=milvus_client,
            store_mutation_lock=StoreMutationLock(engine),
        )
        result = await service.ingest()

        print_json(
            {
                "command": "ingest",
                "write_mode": settings.ingestion_write_mode,
                "use_mock_embeddings": args.mock_embeddings,
                "result": asdict(result),
            }
        )
        return 0

    finally:
        # ES 是异步客户端，需要 await close。
        # MilvusClient 是同步客户端，直接 close。
        await elasticsearch_client.close()
        milvus_client.close()
        await engine.dispose()


async def run_reset_stores(args: argparse.Namespace, settings: Settings) -> int:
    # reset-stores 是危险操作：会删除或重建 ES index / Milvus collection。
    # 这里先检查 --yes，再创建外部 client。
    if not args.yes:
        raise RuntimeError("重建 ES / Milvus 存储需要显式传入 --yes")

    elasticsearch_client = build_elasticsearch_client(settings)
    milvus_client = build_milvus_client(settings)
    engine = create_database_engine(settings)

    try:
        # CLI 不直接调用 indices.delete 或 drop_collection。
        # 结构级危险操作统一交给 rag_store_admin.reset_rag_stores。
        async with StoreMutationLock(engine).hold():
            result = await reset_rag_stores(
                elasticsearch_client=elasticsearch_client,
                milvus_client=milvus_client,
                settings=settings,
                options=StoreResetOptions(
                    target=args.target,
                    recreate_schema=not args.drop_only,
                    confirm=True,
                ),
            )

        print_json(
            {
                "command": "reset-stores",
                "target": args.target,
                "drop_only": args.drop_only,
                "result": asdict(result),
            }
        )
        return 0

    finally:
        await elasticsearch_client.close()
        milvus_client.close()
        await engine.dispose()


def add_ingestion_common_args(parser: argparse.ArgumentParser) -> None:
    # dry-run 和 ingest 都需要这些 ingestion 参数。
    # 抽成 helper 可以避免两个子命令重复声明同一组参数。
    parser.add_argument("--knowledge-base-dir", default=None)
    parser.add_argument("--source-name", default=None)
    parser.add_argument("--elasticsearch-index-name", default=None)
    parser.add_argument("--milvus-collection-name", default=None)
    parser.add_argument(
        "--write-mode",
        choices=["recreate", "upsert", "replace_docs"],
        default=None,
    )
    parser.add_argument("--max-chars", type=int, default=None)
    parser.add_argument("--overlap-chars", type=int, default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--min-chars", type=int, default=None)
    parser.add_argument("--parent-target-tokens", type=int, default=None)
    parser.add_argument("--parent-max-tokens", type=int, default=None)
    parser.add_argument("--parent-max-chars", type=int, default=None)
    parser.add_argument("--child-target-tokens", type=int, default=None)
    parser.add_argument("--child-max-tokens", type=int, default=None)
    parser.add_argument("--child-min-tokens", type=int, default=None)
    parser.add_argument("--child-overlap-tokens", type=int, default=None)


def parse_args() -> argparse.Namespace:
    # ArgumentParser 是整个 CLI 的顶层解析器。
    # 它负责把命令行文本解析成 args 对象。
    parser = argparse.ArgumentParser(
        description="Milvus + ElasticSearch knowledge base ingestion CLI.",
    )
    # add_subparsers 用来创建子命令。
    # dest="command" 表示子命令名字会保存到 args.command。
    # required=True 表示必须传 dry-run / ingest / reset-stores 之一。
    subparsers = parser.add_subparsers(dest="command", required=True)

    # dry-run 子命令：只读取和切分，不写入外部存储。
    dry_run_parser = subparsers.add_parser("dry-run")
    add_ingestion_common_args(dry_run_parser)
    dry_run_parser.add_argument("--sample-size", type=int, default=3)

    # validate 子命令：只做结构化回归检查，不写入外部存储。
    validate_parser = subparsers.add_parser("validate")
    add_ingestion_common_args(validate_parser)

    # ingest 子命令：执行真实写入，所以有 --yes 和 --mock-embeddings。
    ingest_parser = subparsers.add_parser("ingest")
    add_ingestion_common_args(ingest_parser)
    ingest_parser.add_argument("--yes", action="store_true")
    ingest_parser.add_argument("--mock-embeddings", action="store_true")
    ingest_parser.add_argument("--no-es-auth", action="store_true")

    # reset-stores 子命令：只管理 ES / Milvus 结构，不读取文档。
    reset_parser = subparsers.add_parser("reset-stores")
    reset_parser.add_argument(
        "--target",
        choices=["elasticsearch", "milvus", "both"],
        default="both",
    )
    reset_parser.add_argument("--drop-only", action="store_true")
    reset_parser.add_argument("--elasticsearch-index-name", default=None)
    reset_parser.add_argument("--milvus-collection-name", default=None)
    reset_parser.add_argument("--yes", action="store_true")
    reset_parser.add_argument("--no-es-auth", action="store_true")

    return parser.parse_args()


async def main_async() -> int:
    # 入口流程：
    # 1. 解析命令行参数
    # 2. 把参数覆盖到 os.environ
    # 3. 重新读取 Settings
    # 4. 根据子命令分发到具体处理函数
    args = parse_args()
    apply_arg_overrides(args)
    settings = get_settings()

    try:
        if args.command == "dry-run":
            return await run_dry_run(args, settings)

        if args.command == "validate":
            return await run_validate(args, settings)

        if args.command == "ingest":
            return await run_ingest(args, settings)

        if args.command == "reset-stores":
            return await run_reset_stores(args, settings)

        raise RuntimeError(f"不支持的 CLI 命令: {args.command}")

    except Exception as exc:
        print(f"ingestion CLI 执行失败: {exc}", file=sys.stderr)
        return 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
