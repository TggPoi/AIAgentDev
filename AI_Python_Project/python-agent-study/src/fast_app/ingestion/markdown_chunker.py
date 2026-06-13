import hashlib
from pathlib import Path

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
    documents: list[LoadedDocument],
    source: str,
    max_chars: int,
) -> list[KnowledgeChunk]:
    # 最终结果列表。所有文档切出来的 chunk 都会 append 到这里
    chunks: list[KnowledgeChunk] = []

    for document in documents:
        # 保存当前标题路径 # RAG 基础教程--## 混合检索--### RRF->融合["RAG 基础教程", "混合检索", "RRF 融合"]
        heading_stack: list[str] = []
        # 当前章节里的正文行
        section_lines: list[str] = []
        # 记录当前是第几个 section 每遇到一个标题 section_index += 1
        section_index = 0
        # 记录当前文档里已经生成了第几个 chunk
        chunk_index = 0
        # docs/rag_intro.md -> rag_intro 用于没有标题时的默认标题；stem 去除文件后缀
        current_title = Path(document.source_path).stem
        current_heading_level = 0

        # 把当前已经收集的 section_lines 保存成 chunk。
        def flush_section() -> None:
            nonlocal chunk_index

            content = "\n".join(section_lines).strip()
            
            # 正文为空，就不生成 chunk
            if not content:
                return

            # 按最大字符数切分
            for part in split_text(content, max_chars):
                chunk_index += 1
                # :符号在这里的作用是 浅拷贝heading_stack 避免后续修改 `heading_stack` 影响已经保存的 metadata
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
                        #获取最后一元素作为当前chunk的标题  section_path = ["RAG 基础教程", "混合检索", "RRF 融合"]
                        title=section_path[-1],
                        metadata={
                            **document.metadata,
                            "section_path": section_path,
                            "heading_level": current_heading_level,
                            "section_index": section_index,
                            "chunk_index": chunk_index,
                            "source_path": document.source_path,
                            "document_type": document.document_type,
                        },
                    )
                )

        # 实际扫描markdown的逻辑
        for line in document.content.splitlines():
            heading = parse_heading(line)

            if heading is not None:
                # 如果是标题 先保存上一个 section
                flush_section()
                
                # 清空正文缓存 后面的正文应该属于新 section
                section_lines = []
                section_index += 1

                # 取出标题层级和标题文字
                level, title = heading
                current_heading_level = level
                current_title = title

                # doc 9-10 原heading_stack = ["RAG 基础教程", "混合检索", "RRF 融合"]
                # 现在遇到一个新的二级标题 ## 向量检索---level = 2 通过下面的处理保存新的标题层级
                heading_stack = heading_stack[: level - 1]
                # 处理后，新的二级标题进入正确的索引位置 ["RAG 基础教程", "向量检索"]
                heading_stack.append(title)

                continue
            
            # 普通正文，收集起来，等遇到下一个标题或文件结束时再切 chunk
            section_lines.append(line)

        # 最后一个 section 手动触发保存
        flush_section()

    return chunks