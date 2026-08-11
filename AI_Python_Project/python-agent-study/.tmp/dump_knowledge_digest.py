"""生成知识库摘要文件，供人工/模型出题使用。

每个 markdown_child 一行：序号、logical_record_id、parent 短 ID、
visibility/部门、内容预览（首行标题 + 前 160 字符）。
"""

from __future__ import annotations

import json
from pathlib import Path

INVENTORY = Path(__file__).parent / "knowledge_inventory.json"
OUTPUT = Path(__file__).parent / "knowledge_digest.txt"


def main() -> None:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    lines: list[str] = []
    current_doc = None
    for index, item in enumerate(inventory):
        if item["source_path"] != current_doc:
            current_doc = item["source_path"]
            lines.append("")
            lines.append(f"===== {current_doc} | doc_id={item['doc_id']} "
                         f"| {item['visibility']}/{','.join(item['allowed_departments']) or '-'} "
                         f"| revision={item['source_revision']} =====")
        content = item["content"].strip().replace("\n", " ⏎ ")
        parent_short = (item["logical_parent_id"] or "")[-12:]
        lines.append(
            f"[{index:03d}] {item['logical_record_id']} (parent=...{parent_short}) "
            f"chunk#{item['chunk_index']} :: {content[:200]}"
        )
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"摘要已写入 {OUTPUT}，共 {len(inventory)} 条 chunk")


if __name__ == "__main__":
    main()
