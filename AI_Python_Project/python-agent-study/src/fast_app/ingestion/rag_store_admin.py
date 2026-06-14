from dataclasses import dataclass, field
from typing import Any, Literal

from elasticsearch import AsyncElasticsearch
from pymilvus import MilvusClient

from fast_app.core.config import Settings
from fast_app.ingestion.rag_store_schema import (
    ES_IK_INDEX_ANALYZER,
    ES_IK_SEARCH_ANALYZER,
    build_es_mapping,
    build_milvus_index_params,
    build_milvus_schema,
)


StoreName = Literal["elasticsearch", "milvus"]
StoreResetTarget = Literal["elasticsearch", "milvus", "both"]


@dataclass(frozen=True)
class StoreResetOptions:
    target: StoreResetTarget = "both" # 选择要重置milvus还是es，both 两个一起重构
    recreate_schema: bool = True # 删除后是否立刻创建空结构
    confirm: bool = False # 确认是否要重置

# 单个 store 的重建结果
@dataclass(frozen=True)
class SingleStoreResetResult:
    store_name: StoreName
    name: str
    existed_before: bool #操作前是否存在
    dropped: bool #是否真的删除了
    created: bool #是否重新创建了
    detail: dict[str, Any] = field(default_factory=dict) #还有哪些附加信息

# 双 store 的重建结果
@dataclass(frozen=True)
class RagStoresResetResult:
    target: StoreResetTarget
    es: SingleStoreResetResult | None = None #ES重构结果
    milvus: SingleStoreResetResult | None = None #milvus重构结果


def validate_reset_options(options: StoreResetOptions) -> None:
    if options.target not in {"elasticsearch", "milvus", "both"}:
        raise RuntimeError(f"不支持的 store reset 目标: {options.target}")

    if not options.confirm:
        raise RuntimeError("重建 ES / Milvus 存储需要显式 confirm=True")


async def verify_es_ik_analyzers(client: AsyncElasticsearch) -> None:
    sample_text = "混合检索结合向量召回和关键词召回"

    for analyzer in [ES_IK_INDEX_ANALYZER, ES_IK_SEARCH_ANALYZER]:
        await client.indices.analyze(
            analyzer=analyzer,
            text=sample_text,
        )


async def reset_es_index(
    client: AsyncElasticsearch,
    settings: Settings,
    options: StoreResetOptions,
) -> SingleStoreResetResult:
    validate_reset_options(options)
    if options.target not in {"elasticsearch", "both"}:
        raise RuntimeError(f"ES reset 不支持目标: {options.target}")

    index_name = settings.elasticsearch_index_name
    await verify_es_ik_analyzers(client)

    existed_before = bool(await client.indices.exists(index=index_name))
    dropped = False
    created = False

    if existed_before:
        await client.indices.delete(index=index_name)
        dropped = True

    if options.recreate_schema:
        await client.indices.create(index=index_name, **build_es_mapping())
        created = True

    return SingleStoreResetResult(
        store_name="elasticsearch",
        name=index_name,
        existed_before=existed_before,
        dropped=dropped,
        created=created,
    )


def reset_milvus_collection(
    client: MilvusClient,
    settings: Settings,
    options: StoreResetOptions,
) -> SingleStoreResetResult:
    validate_reset_options(options)
    if options.target not in {"milvus", "both"}:
        raise RuntimeError(f"Milvus reset 不支持目标: {options.target}")

    collection_name = settings.milvus_collection_name
    existed_before = client.has_collection(collection_name)
    dropped = False
    created = False

    if existed_before:
        client.drop_collection(collection_name)
        dropped = True

    if options.recreate_schema:
        client.create_collection(
            collection_name=collection_name,
            schema=build_milvus_schema(settings),
            index_params=build_milvus_index_params(settings),
        )
        client.load_collection(collection_name=collection_name)
        created = True

    return SingleStoreResetResult(
        store_name="milvus",
        name=collection_name,
        existed_before=existed_before,
        dropped=dropped,
        created=created,
    )


async def reset_rag_stores(
    elasticsearch_client: AsyncElasticsearch,
    milvus_client: MilvusClient,
    settings: Settings,
    options: StoreResetOptions,
) -> RagStoresResetResult:
    validate_reset_options(options)

    es_result: SingleStoreResetResult | None = None
    milvus_result: SingleStoreResetResult | None = None

    if options.target in {"elasticsearch", "both"}:
        es_result = await reset_es_index(
            client=elasticsearch_client,
            settings=settings,
            options=options,
        )

    if options.target in {"milvus", "both"}:
        milvus_result = reset_milvus_collection(
            client=milvus_client,
            settings=settings,
            options=options,
        )

    return RagStoresResetResult(
        target=options.target,
        es=es_result,
        milvus=milvus_result,
    )
