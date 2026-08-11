r"""知识库数据画像：为构建新评测集做准备的只读画像脚本。

运行：
    .\.venv\Scripts\python.exe .tmp\profile_knowledge_data.py
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter

from pymilvus import MilvusClient

MILVUS_COLLECTION = "python_agent_demo_chunks"
ES_INDEX = "python_agent_demo_chunks"
ES_URL = "http://127.0.0.1:9200"


def profile_milvus() -> None:
    client = MilvusClient(uri="http://127.0.0.1:19530")
    client.load_collection(MILVUS_COLLECTION)
    total = client.query(MILVUS_COLLECTION, filter="", output_fields=["count(*)"])[0]["count(*)"]
    rows = client.query(
        MILVUS_COLLECTION,
        filter="",
        output_fields=[
            "doc_id",
            "title",
            "source",
            "source_path",
            "record_type",
            "logical_record_id",
            "valid_from_version",
            "valid_to_version",
        ],
        limit=16384,
    )
    print(f"== Milvus: 共 {total} 条实体，拉取到 {len(rows)} 条 ==")
    print("record_type 分布:", dict(Counter(r.get("record_type") for r in rows)))
    print("source 分布:", dict(Counter(r.get("source") for r in rows)))
    print("valid_to_version 分布(前5):", dict(Counter(r.get("valid_to_version") for r in rows).most_common(5)))
    doc_titles: dict[str, str] = {}
    for r in rows:
        doc_titles.setdefault(str(r.get("doc_id")), str(r.get("title") or ""))
    print(f"distinct doc_id 数: {len(doc_titles)}")
    for doc_id, title in sorted(doc_titles.items(), key=lambda x: x[1])[:40]:
        print(f"  - {title!r}  (doc_id={doc_id[:16]}...)")
    child_rows = [r for r in rows if r.get("record_type") in (None, "child", "chunk")]
    if child_rows:
        print("logical_record_id 样例(前3):", [r.get("logical_record_id") for r in child_rows[:3]])
        print("source_path 样例(前5):", sorted({str(r.get("source_path")) for r in rows})[:5])


def profile_es() -> None:
    from elasticsearch import AsyncElasticsearch

    async def run() -> None:
        async with AsyncElasticsearch(ES_URL, request_timeout=10) as es:
            count = (await es.count(index=ES_INDEX))["count"]
            agg = await es.search(
                index=ES_INDEX,
                size=0,
                body={
                    "aggs": {
                        "by_record_type": {"terms": {"field": "record_type", "missing": "<missing>", "size": 10}},
                        "by_source": {"terms": {"field": "source", "missing": "<missing>", "size": 10}},
                        "by_doc": {"cardinality": {"field": "doc_id", "precision_threshold": 1000}},
                    }
                },
            )
            aggs = agg["aggregations"]
            print(f"== ES: 共 {count} 条文档 ==")
            print(
                "record_type 分布:",
                {b["key"]: b["doc_count"] for b in aggs["by_record_type"]["buckets"]},
            )
            print("source 分布:", {b["key"]: b["doc_count"] for b in aggs["by_source"]["buckets"]})
            print("distinct doc_id 数:", aggs["by_doc"]["value"])
            # 看一条真实文档的字段结构
            sample = await es.search(index=ES_INDEX, size=1, body={"query": {"match_all": {}}})
            hit = sample["hits"]["hits"][0]
            fields = sorted(hit["_source"].keys())
            print("文档字段:", fields)
            content = str(hit["_source"].get("content") or "")
            print("content 片段:", content[:120].replace("\n", " "))

    asyncio.run(run())


def profile_golden_dataset() -> None:
    path = r"src\fast_app\evaluation\datasets\stage11_rag_eval_cases.v2.0.0.json"
    with open(path, encoding="utf-8") as f:
        dataset = json.load(f)
    cases = dataset.get("cases", [])
    print(f"== 旧 Golden V2 数据集: {len(cases)} 条 case ==")
    print("dataset_version:", dataset.get("dataset_version"), "lifecycle:", dataset.get("lifecycle"))
    chunk_ids: set[str] = set()
    for case in cases:
        chunk_ids.update(case.get("relevant_logical_chunk_ids", []))
    print(f"标注引用的 logical_chunk_id 总数: {len(chunk_ids)}")
    print("样例:", sorted(chunk_ids)[:5])
    return chunk_ids


def main() -> None:
    profile_milvus()
    print()
    profile_es()
    print()
    golden_ids = profile_golden_dataset()
    # 对比：旧评测集标注的 logical_chunk_id 是否还存在于 Milvus
    client = MilvusClient(uri="http://127.0.0.1:19530")
    client.load_collection(MILVUS_COLLECTION)
    rows = client.query(
        MILVUS_COLLECTION,
        filter="",
        output_fields=["logical_record_id"],
        limit=16384,
    )
    existing = {str(r.get("logical_record_id")) for r in rows if r.get("logical_record_id")}
    hit = golden_ids & existing
    print()
    print(f"== 旧评测集 vs 当前 Milvus 对比 ==")
    print(f"旧评测集标注 {len(golden_ids)} 个 logical_chunk_id，当前 Milvus 存在 {len(existing)} 个 logical_record_id")
    print(f"交集数量: {len(hit)}  → 交集比例: {(len(hit) / len(golden_ids)) if golden_ids else 0:.1%}")


if __name__ == "__main__":
    main()
