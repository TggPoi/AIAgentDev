from dataclasses import dataclass
from pathlib import Path
import re

from fast_app.domain.knowledge_models import KnowledgeChunk


DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


@dataclass
class MarkdownSection:
    # 一个 MarkdownSection 表示 Markdown 里的一个标题段落。
    # 例如 "# RAG 基础教程" 到下一个标题之前的正文，会被保存成一个 section。
    title: str
    # 标题层级：# 是 1，## 是 2，### 是 3。
    level: int
    # 从顶层标题到当前标题的完整路径。
    # 例如 ["RAG 基础教程", "混合检索", "RRF 融合"]。
    section_path: list[str]
    # 当前标题下面、下一个标题之前的正文内容。
    content: str


# 匹配 Markdown 标题行：
# - ^ 和 $ 表示整行匹配
# - (#{1,6}) 匹配 1 到 6 个 #，也就是 Markdown 的 1 到 6 级标题
# - \s+ 要求 # 后面至少有一个空格
# - (.+?) 捕获标题文字
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def read_markdown_file(file_path: str | Path) -> str:
    # Path(...) 同时兼容字符串路径和 Path 对象；read_text 直接读取 UTF-8 文本。
    return Path(file_path).read_text(encoding="utf-8")


def split_markdown_into_sections(markdown_text: str) -> list[MarkdownSection]:
    # splitlines() 按行切开文本，并去掉每行末尾的换行符。
    # 后面逐行扫描，遇到标题就开启一个新的 section。
    lines = markdown_text.splitlines()

    sections: list[MarkdownSection] = []
    # heading_stack 维护当前所在的标题路径。
    # 每个元素是 (标题层级, 标题文字)，例如：
    # [(1, "RAG 基础教程"), (2, "混合检索")]
    heading_stack: list[tuple[int, str]] = []

    # current_* 变量保存“正在收集的 section”的状态。
    # 初始 ROOT 用来承接第一个标题出现前的正文；如果没有正文就不会生成 ROOT section。
    current_title = "ROOT"
    current_level = 0
    current_content_lines: list[str] = []
    current_path: list[str] = []

    def flush_current_section() -> None:
        # flush 的意思是“把当前已经收集到的正文保存成一个 MarkdownSection”。
        # 每次遇到新标题前，都要先把上一个标题下的正文保存起来。
        content = "\n".join(current_content_lines).strip()

        # 空 section 不保存。比如标题下面没有正文，或者文件开头没有正文。
        if not content:
            return

        sections.append(
            MarkdownSection(
                title=current_title,
                level=current_level,
                # copy() 很重要：保存当前路径的快照。
                # 如果直接保存 current_path，后续修改路径时可能影响已经保存的 section。
                section_path=current_path.copy(),
                content=content,
            )
        )

    for line in lines:
        match = HEADING_PATTERN.match(line)

        # 不是标题行，就属于当前 section 的正文。
        if not match:
            current_content_lines.append(line)
            continue

        # 走到这里说明遇到了一个新标题。
        # 新标题开始前，先把前一个 section 的正文落盘到 sections 列表里。
        flush_current_section()

        hashes, title = match.groups()
        level = len(hashes)
        title = title.strip()

        # 如果新标题层级小于或等于栈顶层级，说明要回到上级或同级标题。
        # 例如当前路径是 H1 > H2 > H3，遇到新的 H2 时，需要先弹出旧的 H3 和 H2。
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()

        # 把新标题放进路径栈中。
        heading_stack.append((level, title))

        # 更新当前 section 状态；从下一行开始收集这个标题下面的正文。
        current_title = title
        current_level = level
        current_path = [item[1] for item in heading_stack]
        current_content_lines = []

    # 文件扫描结束后，最后一个 section 后面不会再遇到新标题，
    # 所以要手动 flush 一次，把最后一段正文保存下来。
    flush_current_section()

    return sections


def split_text_with_overlap(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    # 这个函数是简易版文本 splitter：
    # 按固定字符数切块，并让相邻块之间保留一段重叠文本。
    # 注意这里按 Python 字符数切，不按 token，也不按语义句子切。
    text = text.strip()

    if not text:
        return []

    # 文本本身不超过 chunk_size 时，不需要切分。
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

        # overlap 的核心在这里：
        # 下一个 chunk 不从 end 开始，而是从 end - chunk_overlap 开始。
        # 例如 chunk_size=300、chunk_overlap=50：
        # 第 1 块取 [0:300]，第 2 块从 250 开始取 [250:550]。
        # 这样可以减少“答案刚好被切在两个 chunk 边界处”导致的上下文丢失。
        start = max(0, end - chunk_overlap)

    return chunks


def build_chunk_id(
    source_stem: str,
    section_index: int,
    chunk_index: int,
) -> str:
    # 为每个 chunk 生成稳定 id。
    # :03d 表示补齐到 3 位数字，例如 1 -> 001。
    # rag_intro_s002_c001 表示 rag_intro 文件的第 2 个 section 的第 1 个 chunk。
    return f"{source_stem}_s{section_index:03d}_c{chunk_index:03d}"


def build_chunks_from_markdown(
    file_path: str | Path,
    source: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[KnowledgeChunk]:
    path = Path(file_path)
    markdown_text = read_markdown_file(path)
    # 第一步：先按 Markdown 标题拆成多个 section。
    sections = split_markdown_into_sections(markdown_text)

    # source 是写入 KnowledgeChunk 的来源字段。
    # 调用方传 source 时用调用方指定的值；不传时默认用文件路径。
    source_name = source or str(path)
    # path.stem 是不带扩展名的文件名，例如 rag_intro.md -> rag_intro。
    # 后面用它生成 chunk id。
    source_stem = path.stem

    chunks: list[KnowledgeChunk] = []

    for section_index, section in enumerate(sections, start=1):
        # 第二步：每个 section 内部再按 chunk_size / chunk_overlap 切成小块。
        # 小 section 通常只生成 1 个 chunk；长 section 会生成多个 chunk。
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

            # 把标题路径拼进 chunk 内容里。
            # 这样后续做 embedding 和检索时，模型不仅能看到正文，也能看到该正文属于哪个章节。
            section_path_text = " / ".join(section.section_path)

            content = (
                f"标题路径：{section_path_text}\n\n"
                f"{chunk_text}"
            )

            # 第三步：把文本块包装成统一的 KnowledgeChunk。
            # content 用于 embedding / 检索；metadata 保存结构化信息，方便调试或后续过滤。
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
