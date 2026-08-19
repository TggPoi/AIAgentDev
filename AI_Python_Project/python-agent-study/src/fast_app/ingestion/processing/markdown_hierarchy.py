from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

from fast_app.core.logging import get_logger
from fast_app.ingestion.processing.token_counters import TiktokenCounter
from fast_app.domain.knowledge_models import KnowledgeChunk, LoadedDocument
from fast_app.ingestion.processing.metadata_models import build_document_metadata


logger = get_logger(__name__)


# v2：空标题章节向后合并 + 父块/子块 content 前置章节面包屑；
# 版本号参与稳定 ID 哈希，升版即全量 ID 换新，旧记录由增量同步版本闸门清理。
MARKDOWN_CHUNK_STRATEGY_VERSION = "markdown_parent_child_v2"
MARKDOWN_CHILD_RECORD_TYPE = "markdown_child"
MARKDOWN_PARENT_RECORD_TYPE = "markdown_parent"


@dataclass(frozen=True)
class MarkdownHierarchyOptions:
    source: str
    parent_target_tokens: int = 900
    parent_max_tokens: int = 1200
    parent_max_chars: int = 6000
    child_target_tokens: int = 260
    child_max_tokens: int = 350
    child_min_tokens: int = 80
    child_overlap_tokens: int = 50

    def validate(self) -> None:
        if min(
            self.parent_target_tokens,
            self.parent_max_tokens,
            self.parent_max_chars,
            self.child_target_tokens,
            self.child_max_tokens,
            self.child_min_tokens,
        ) <= 0:
            raise ValueError("Markdown 父子分块预算必须全部大于 0")
        if not (
            self.child_min_tokens
            <= self.child_target_tokens
            <= self.child_max_tokens
            < self.parent_max_tokens
        ):
            raise ValueError(
                "Markdown token 预算必须满足 "
                "child_min <= child_target <= child_max < parent_max"
            )
        if not 0 <= self.child_overlap_tokens < self.child_target_tokens:
            raise ValueError("Markdown child overlap 必须小于 child target")
        if self.parent_target_tokens > self.parent_max_tokens:
            raise ValueError("Markdown parent target 不能大于 parent max")


@dataclass(frozen=True)
class MarkdownBlock:
    kind: str
    content: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class MarkdownSection:
    section_index: int
    section_path: list[str]
    heading_level: int
    occurrence: int
    blocks: list[MarkdownBlock]


@dataclass(frozen=True)
class MarkdownParentChunk:
    id: str
    content: str
    source: str
    title: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class MarkdownChunkBuildResult:
    parents: list[MarkdownParentChunk] = field(default_factory=list)
    children: list[KnowledgeChunk] = field(default_factory=list)


class MarkdownHierarchyBuilder:
    """把 Markdown 解析成有界父块和用于召回的结构感知子块。"""

    def __init__(self, token_counter: TiktokenCounter | None = None) -> None:
        self.token_counter = token_counter or TiktokenCounter()
        self.parser = MarkdownIt("commonmark").enable("table")

    def build(
        self,
        documents: list[LoadedDocument],
        options: MarkdownHierarchyOptions,
    ) -> MarkdownChunkBuildResult:
        options.validate()
        parents: list[MarkdownParentChunk] = []
        children: list[KnowledgeChunk] = []
        for document in documents:
            if document.document_type != "markdown":
                raise ValueError("MarkdownHierarchyBuilder 只接受 markdown 文档")
            result = self._build_document(document, options)
            parents.extend(result.parents)
            children.extend(result.children)
        return MarkdownChunkBuildResult(parents=parents, children=children)

    def _build_document(
        self,
        document: LoadedDocument,
        options: MarkdownHierarchyOptions,
    ) -> MarkdownChunkBuildResult:
        metadata = dict(document.metadata)
        if "doc_id" not in metadata:
            metadata.update(
                build_document_metadata(
                    source_path=document.source_path,
                    document_type="markdown",
                )
            )
        doc_id = str(metadata["doc_id"])
        parents: list[MarkdownParentChunk] = []
        children: list[KnowledgeChunk] = []
        for section in self._parse_sections(document):
            section_key = self._stable_id(
                "section",
                doc_id,
                "/".join(section.section_path),
                str(section.occurrence),
            )
            # 章节面包屑前缀（格式与旧 search_text 一致，保证检索匹配文本逐字等价）。
            prefix = self._breadcrumb(section.section_path)
            prefix_tokens = self.token_counter.count(prefix)
            # 装箱前从父块预算中预留前缀开销，拼接后 content 恰好不超原硬上限。
            parent_groups = self._pack_blocks(
                section.blocks,
                target_tokens=max(1, options.parent_target_tokens - prefix_tokens),
                max_tokens=max(1, options.parent_max_tokens - prefix_tokens),
                max_chars=max(1, options.parent_max_chars - len(prefix)),
            )
            for parent_index, parent_blocks in enumerate(parent_groups, start=1):
                parent_content = prefix + self._join_blocks(parent_blocks)
                parent_id = self._stable_id(
                    "parent",
                    section_key,
                    str(parent_index),
                    MARKDOWN_CHUNK_STRATEGY_VERSION,
                )
                parent_metadata = self._metadata(
                    metadata,
                    record_type=MARKDOWN_PARENT_RECORD_TYPE,
                    parent_id=parent_id,
                    section_key=section_key,
                    section=section,
                    parent_index=parent_index,
                    child_index=None,
                    content=parent_content,
                    blocks=parent_blocks,
                )
                parents.append(
                    MarkdownParentChunk(
                        id=parent_id,
                        content=parent_content,
                        source=options.source,
                        title=section.section_path[-1],
                        metadata=parent_metadata,
                    )
                )
                child_groups = self._build_child_groups(parent_blocks, options, prefix)
                for child_index, child_blocks in enumerate(child_groups, start=1):
                    child_content = prefix + self._join_blocks(child_blocks)
                    child_id = self._stable_id(
                        "chunk",
                        parent_id,
                        str(child_index),
                        MARKDOWN_CHUNK_STRATEGY_VERSION,
                    )
                    child_metadata = self._metadata(
                        metadata,
                        record_type=MARKDOWN_CHILD_RECORD_TYPE,
                        parent_id=parent_id,
                        section_key=section_key,
                        section=section,
                        parent_index=parent_index,
                        child_index=child_index,
                        content=child_content,
                        blocks=child_blocks,
                    )
                    child_metadata["chunk_id"] = child_id
                    child_metadata["chunk_index"] = child_index
                    children.append(
                        KnowledgeChunk(
                            id=child_id,
                            content=child_content,
                            # content 已含面包屑前缀，search_text 直接复用，
                            # ES 匹配文本与 embedding 文本保持逐字等价。
                            search_text=child_content,
                            source=options.source,
                            title=section.section_path[-1],
                            metadata=child_metadata,
                        )
                    )
        return MarkdownChunkBuildResult(parents=parents, children=children)

    def _parse_sections(self, document: LoadedDocument) -> list[MarkdownSection]:
        lines = document.content.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        tokens = self.parser.parse("\n".join(lines))
        sections: list[MarkdownSection] = []
        heading_stack: list[tuple[int, str]] = []
        occurrences: dict[tuple[str, ...], int] = {}
        current_path = [self._filename_title(document.source_path)]
        current_level = 0
        current_blocks: list[MarkdownBlock] = []
        # 仅含标题的“空章节”暂存队列：其标题块等待并入下一个有正文的章节，
        # 避免产出只有标题行的空壳父块/子块污染索引。
        pending_heading_blocks: list[MarkdownBlock] = []

        def flush() -> None:
            nonlocal current_blocks, pending_heading_blocks
            if not current_blocks:
                return
            if all(block.kind == "heading" for block in current_blocks):
                # 仅标题无正文：不产出章节，标题块暂存等待并入下一节。
                pending_heading_blocks.extend(current_blocks)
                current_blocks = []
                return
            # 把之前累积的空标题块并入本节头部：空标题语义上是“引子”，
            # 归入它引出的正文章节后，块内容保留完整标题层级且不产生空壳块。
            blocks = [*pending_heading_blocks, *current_blocks]
            pending_heading_blocks = []
            key = tuple(current_path)
            occurrences[key] = occurrences.get(key, 0) + 1
            sections.append(
                MarkdownSection(
                    section_index=len(sections) + 1,
                    section_path=list(current_path),
                    heading_level=current_level,
                    occurrence=occurrences[key],
                    blocks=blocks,
                )
            )
            current_blocks = []

        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.type == "heading_open" and token.level == 0:
                flush()
                level = int(token.tag[1:])
                title = tokens[index + 1].content.strip()
                heading_stack = [item for item in heading_stack if item[0] < level]
                heading_stack.append((level, title))
                current_path = [value for _, value in heading_stack]
                current_level = level
                if token.map:
                    start, end = token.map
                    current_blocks.append(
                        MarkdownBlock(
                            kind="heading",
                            content="\n".join(lines[start:end]).strip(),
                            line_start=start + 1,
                            line_end=end,
                        )
                    )
                index += 3
                continue
            if token.level == 0 and token.map and self._is_top_level_block(token):
                start, end = token.map
                content = "\n".join(lines[start:end]).strip()
                if content:
                    current_blocks.append(
                        MarkdownBlock(
                            kind=token.type,
                            content=content,
                            line_start=start + 1,
                            line_end=end,
                        )
                    )
            index += 1
        flush()
        if pending_heading_blocks:
            if sections:
                # 文末残留的空标题不引出任何内容，丢弃即可；
                # 其标题路径信息已经由 heading_stack 体现在前面章节的 section_path 中。
                logger.warning(
                    "Markdown 文末空标题章节已丢弃 source_path=%s 标题数=%s",
                    document.source_path,
                    len(pending_heading_blocks),
                )
            else:
                # 全文只有空标题：兜底产出，避免整篇文档变成 0 chunk 完全不可检索。
                logger.warning(
                    "Markdown 全文仅含标题，按兜底章节产出 source_path=%s",
                    document.source_path,
                )
                key = tuple(current_path)
                occurrences[key] = occurrences.get(key, 0) + 1
                sections.append(
                    MarkdownSection(
                        section_index=1,
                        section_path=list(current_path),
                        heading_level=current_level,
                        occurrence=occurrences[key],
                        blocks=pending_heading_blocks,
                    )
                )
        return sections

    @staticmethod
    def _is_top_level_block(token: Any) -> bool:
        return token.type in {
            "paragraph_open",
            "blockquote_open",
            "bullet_list_open",
            "ordered_list_open",
            "fence",
            "code_block",
            "html_block",
            "table_open",
            "hr",
        }

    def _pack_blocks(
        self,
        blocks: list[MarkdownBlock],
        *,
        target_tokens: int,
        max_tokens: int,
        max_chars: int,
    ) -> list[list[MarkdownBlock]]:
        expanded = [
            part
            for block in blocks
            for part in self._split_oversized_block(block, max_tokens, max_chars)
        ]
        groups: list[list[MarkdownBlock]] = []
        current: list[MarkdownBlock] = []
        for block in expanded:
            candidate = [*current, block]
            if current and (
                self.token_counter.count(self._join_blocks(candidate)) > max_tokens
                or len(self._join_blocks(candidate)) > max_chars
                or self.token_counter.count(self._join_blocks(current)) >= target_tokens
            ):
                groups.append(current)
                current = []
            current.append(block)
        if current:
            groups.append(current)
        return groups

    def _build_child_groups(
        self,
        blocks: list[MarkdownBlock],
        options: MarkdownHierarchyOptions,
        prefix: str,
    ) -> list[list[MarkdownBlock]]:
        # 面包屑前缀将拼接在每个子块 content 头部，先从子块预算中扣除它的开销，
        # 保证“前缀 + 正文”不超 child_max_tokens；
        # child_min / overlap 衡量的是正文本身，不参与扣减。
        reserved_tokens = self.token_counter.count(prefix)
        effective_target = max(1, options.child_target_tokens - reserved_tokens)
        effective_max = max(1, options.child_max_tokens - reserved_tokens)
        groups = self._pack_blocks(
            blocks,
            target_tokens=effective_target,
            max_tokens=effective_max,
            max_chars=options.parent_max_chars,
        )
        if len(groups) > 1:
            tail = self._join_blocks(groups[-1])
            merged_tail = [*groups[-2], *groups[-1]]
            if (
                self.token_counter.count(tail) < options.child_min_tokens
                and self.token_counter.count(self._join_blocks(merged_tail))
                <= effective_max
            ):
                groups[-2:] = [merged_tail]
        if len(groups) <= 1 or options.child_overlap_tokens == 0:
            return groups
        overlapped: list[list[MarkdownBlock]] = [groups[0]]
        for previous, group in zip(groups, groups[1:]):
            carry: list[MarkdownBlock] = []
            for block in reversed(previous):
                candidate = [block, *carry]
                if (
                    self.token_counter.count(self._join_blocks(candidate))
                    > options.child_overlap_tokens
                ):
                    break
                carry = candidate
            candidate = [*carry, *group]
            if self.token_counter.count(self._join_blocks(candidate)) <= effective_max:
                overlapped.append(candidate)
            else:
                overlapped.append(group)
        return overlapped

    def _split_oversized_block(
        self,
        block: MarkdownBlock,
        max_tokens: int,
        max_chars: int,
    ) -> list[MarkdownBlock]:
        if self._fits(block.content, max_tokens, max_chars):
            return [block]
        if block.kind == "fence":
            return self._split_fence(block, max_tokens, max_chars)
        if block.kind == "table_open":
            return self._split_table(block, max_tokens, max_chars)
        units = (
            [line for line in block.content.splitlines() if line.strip()]
            if block.kind in {"bullet_list_open", "ordered_list_open", "code_block"}
            else [
                part.strip()
                for part in re.split(r"(?<=[。！？.!?；;])\s*", block.content)
                if part.strip()
            ]
        )
        return self._pack_text_units(block, units, max_tokens, max_chars)

    def _split_fence(
        self,
        block: MarkdownBlock,
        max_tokens: int,
        max_chars: int,
    ) -> list[MarkdownBlock]:
        lines = block.content.splitlines()
        if len(lines) < 2:
            return self._token_slices(block, max_tokens, max_chars)
        opening = lines[0]
        marker = opening.lstrip()[:3]
        closing = lines[-1] if lines[-1].lstrip().startswith(marker) else marker
        body = lines[1:-1] if lines[-1] == closing else lines[1:]
        available = max(1, max_tokens - self.token_counter.count(f"{opening}\n{closing}"))
        chunks: list[MarkdownBlock] = []
        current: list[str] = []
        for line in body:
            candidate = "\n".join([opening, *current, line, closing])
            if current and not self._fits(candidate, max_tokens, max_chars):
                chunks.append(self._copy_block(block, "\n".join([opening, *current, closing])))
                current = []
            if self.token_counter.count(line) > available:
                if current:
                    chunks.append(self._copy_block(block, "\n".join([opening, *current, closing])))
                    current = []
                chunks.extend(
                    self._copy_block(block, "\n".join([opening, part, closing]))
                    for part in self.token_counter.split(line, available)
                )
            else:
                current.append(line)
        if current:
            chunks.append(self._copy_block(block, "\n".join([opening, *current, closing])))
        return chunks

    def _split_table(
        self,
        block: MarkdownBlock,
        max_tokens: int,
        max_chars: int,
    ) -> list[MarkdownBlock]:
        lines = block.content.splitlines()
        if len(lines) <= 2:
            return self._token_slices(block, max_tokens, max_chars)
        header = lines[:2]
        header_text = "\n".join(header)
        row_budget = max(1, max_tokens - self.token_counter.count(header_text))
        chunks: list[MarkdownBlock] = []
        current: list[str] = []
        for row in lines[2:]:
            candidate = "\n".join([*header, *current, row])
            if current and not self._fits(candidate, max_tokens, max_chars):
                chunks.append(self._copy_block(block, "\n".join([*header, *current])))
                current = []
            if not self._fits("\n".join([*header, row]), max_tokens, max_chars):
                chunks.extend(
                    self._copy_block(block, "\n".join([*header, part]))
                    for part in self.token_counter.split(row, row_budget)
                )
            else:
                current.append(row)
        if current:
            chunks.append(self._copy_block(block, "\n".join([*header, *current])))
        return chunks

    def _pack_text_units(
        self,
        block: MarkdownBlock,
        units: list[str],
        max_tokens: int,
        max_chars: int,
    ) -> list[MarkdownBlock]:
        chunks: list[MarkdownBlock] = []
        current: list[str] = []
        for unit in units:
            if not self._fits(unit, max_tokens, max_chars):
                if current:
                    chunks.append(self._copy_block(block, "\n".join(current)))
                    current = []
                chunks.extend(
                    self._token_slices(
                        self._copy_block(block, unit),
                        max_tokens,
                        max_chars,
                    )
                )
                continue
            candidate = "\n".join([*current, unit])
            if current and not self._fits(candidate, max_tokens, max_chars):
                chunks.append(self._copy_block(block, "\n".join(current)))
                current = []
            current.append(unit)
        if current:
            chunks.append(self._copy_block(block, "\n".join(current)))
        return chunks

    def _token_slices(
        self,
        block: MarkdownBlock,
        max_tokens: int,
        max_chars: int,
    ) -> list[MarkdownBlock]:
        return [
            self._copy_block(block, char_part)
            for part in self.token_counter.split(block.content, max_tokens)
            for char_part in (
                part[index : index + max_chars]
                for index in range(0, len(part), max_chars)
            )
            if char_part.strip()
        ]

    def _fits(self, text: str, max_tokens: int, max_chars: int) -> bool:
        return len(text) <= max_chars and self.token_counter.count(text) <= max_tokens

    @staticmethod
    def _join_blocks(blocks: list[MarkdownBlock]) -> str:
        return "\n\n".join(block.content for block in blocks if block.content).strip()

    @staticmethod
    def _copy_block(block: MarkdownBlock, content: str) -> MarkdownBlock:
        return MarkdownBlock(
            kind=block.kind,
            content=content.strip(),
            line_start=block.line_start,
            line_end=block.line_end,
        )

    def _metadata(
        self,
        document_metadata: dict[str, Any],
        *,
        record_type: str,
        parent_id: str,
        section_key: str,
        section: MarkdownSection,
        parent_index: int,
        child_index: int | None,
        content: str,
        blocks: list[MarkdownBlock],
    ) -> dict[str, Any]:
        return {
            **document_metadata,
            "record_type": record_type,
            "parent_id": parent_id,
            "section_key": section_key,
            "title": section.section_path[-1],
            "section_path": section.section_path,
            "heading_level": section.heading_level,
            "section_index": section.section_index,
            "parent_index": parent_index,
            "child_index": child_index,
            "token_count": self.token_counter.count(content),
            "char_count": len(content),
            "line_start": min(block.line_start for block in blocks),
            "line_end": max(block.line_end for block in blocks),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "chunk_strategy_version": MARKDOWN_CHUNK_STRATEGY_VERSION,
        }

    @staticmethod
    def _breadcrumb(section_path: list[str]) -> str:
        """章节完整路径面包屑，拼接在父块/子块 content 头部；尾随空行与正文分隔。"""
        return f"{' > '.join(section_path)}\n\n"

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        raw = "|".join(parts)
        return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _filename_title(source_path: str) -> str:
        name = source_path.replace("\\", "/").rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[0] or "document"


__all__ = [
    "MARKDOWN_CHILD_RECORD_TYPE",
    "MARKDOWN_CHUNK_STRATEGY_VERSION",
    "MARKDOWN_PARENT_RECORD_TYPE",
    "MarkdownChunkBuildResult",
    "MarkdownHierarchyBuilder",
    "MarkdownHierarchyOptions",
    "MarkdownParentChunk",
    "TiktokenCounter",
]
