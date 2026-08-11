"""盘点当前 Milvus 中全部当前有效的 markdown_child 记录。

输出 .tmp/knowledge_inventory.json：
- 每条 child 的 logical_record_id/doc_id/title/source_path/chunk_index/
  logical_parent_id/source_revision/visibility/allowed_departments/content
- 按文档分组摘要（含 ACL 可见性）
"""

from __future__ import annotations

import json
from pathlib import Path

from pymilvus import MilvusClient

MILVUS_HOST = "127.0.0.1"
MILVUS_PORT = 19530
COLLECTION = "python_agent_demo_chunks"
OUTPUT_PATH = Path(__file__).parent / "knowledge_inventory.json"

OUTPUT_FIELDS = [
    "logical_record_id",
    "doc_id",
    "title",
    "source_path",
    "chunk_index",
    "logical_parent_id",
    "source_revision",
    "valid_from_version",
    "valid_to_version",
    "metadata",
    "content",
]


def main() -> None:
    client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    rows = client.query(
        collection_name=COLLECTION,
        filter='record_type == "markdown_child" and valid_to_version == 0',
        output_fields=OUTPUT_FIELDS,
        limit=1000,
    )

    inventory = []
    for row in rows:
        metadata = row.get("metadata") or {}
        inventory.append(
            {
                "logical_record_id": row["logical_record_id"],
                "doc_id": row["doc_id"],
                "title": row.get("title"),
                "source_path": row.get("source_path"),
                "chunk_index": row.get("chunk_index"),
                "logical_parent_id": row.get("logical_parent_id"),
                "source_revision": row.get("source_revision"),
                "valid_from_version": row.get("valid_from_version"),
                "visibility": metadata.get("visibility"),
                "allowed_departments": metadata.get("allowed_departments") or [],
                "content": row.get("content") or "",
            }
        )

    inventory.sort(key=lambda item: (item["source_path"] or "", item["chunk_index"] or 0))

    OUTPUT_PATH.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 按文档分组摘要
    by_doc: dict[str, dict] = {}
    for item in inventory:
        doc = by_doc.setdefault(
            item["doc_id"],
            {
                "title": item["title"],
                "source_path": item["source_path"],
                "visibility": item["visibility"],
                "allowed_departments": item["allowed_departments"],
                "child_count": 0,
                "source_revision": item["source_revision"],
            },
        )
        doc["child_count"] += 1

    print(f"当前有效 markdown_child 总数: {len(inventory)}")
    print(f"文档数: {len(by_doc)}\n")
    print(f"{'doc_id':<28} {'child':>5} {'visibility':<12} {'departments':<20} source_path")
    for doc_id, doc in sorted(by_doc.items(), key=lambda kv: kv[1]["source_path"] or ""):
        print(
            f"{doc_id:<28} {doc['child_count']:>5} "
            f"{str(doc['visibility']):<12} {','.join(doc['allowed_departments']) or '-':<20} "
            f"{doc['source_path']}"
        )
        print(f"    title: {doc['title']}  revision: {doc['source_revision']}")

    print(f"\n完整盘点已写入 {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
