"""图片预算、缓存、并发和 occurrence 映射的统一 Vision 模块。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from fast_app.components.vision.base import (
    BaseVisionClient,
    BeforeExternalCall,
    VisionAnalysisError,
    VisionExternalCallRejected,
)
from fast_app.core.config import Settings
from fast_app.domain.knowledge_models import (
    VisionAnalysisResult,
    VisionImageContent,
    VisionImageOccurrence,
)


@dataclass(frozen=True)
class DocumentProcessingWarning:
    code: str
    source_locator: str
    message: str


@dataclass(frozen=True)
class VisionAnalysisOutcome:
    results: dict[str, VisionAnalysisResult]
    warnings: list[DocumentProcessingWarning]


class DocumentVisionService:
    """以内容为单位分析，以 occurrence 为单位返回结果。"""

    def __init__(
        self,
        *,
        settings: Settings,
        client: BaseVisionClient | None = None,
        client_factory: Callable[[], BaseVisionClient] | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._client_factory = client_factory
        self._semaphore = asyncio.Semaphore(settings.vision_max_concurrency)

    async def analyze_assets(
        self,
        *,
        contents: Mapping[str, VisionImageContent],
        occurrences: list[VisionImageOccurrence],
        mode: str,
        before_external_call: BeforeExternalCall | None = None,
    ) -> dict[str, VisionAnalysisResult]:
        outcome = await self.analyze_assets_with_warnings(
            contents=contents,
            occurrences=occurrences,
            mode=mode,
            before_external_call=before_external_call,
        )
        if outcome.warnings:
            first = outcome.warnings[0]
            raise VisionAnalysisError(first.code, first.message)
        return outcome.results

    async def analyze_assets_with_warnings(
        self,
        *,
        contents: Mapping[str, VisionImageContent],
        occurrences: list[VisionImageOccurrence],
        mode: str,
        before_external_call: BeforeExternalCall | None = None,
    ) -> VisionAnalysisOutcome:
        self._validate_budget(contents, occurrences)
        if not self._settings.vision_enabled:
            return VisionAnalysisOutcome(
                results={},
                warnings=[
                    DocumentProcessingWarning(
                        "VISION_DISABLED", item.source_locator, "图片分析功能已关闭"
                    )
                    for item in occurrences
                ],
            )
        client = self._get_client()
        content_results: dict[str, VisionAnalysisResult] = {}
        warnings: list[DocumentProcessingWarning] = []

        async def guarded_before_external_call() -> None:
            if before_external_call is None:
                return
            try:
                await before_external_call()
            except BaseException as exc:
                raise VisionExternalCallRejected(
                    "外部调用前 ownership/cancellation 校验失败"
                ) from exc

        async def analyze_one(
            content_id: str,
        ) -> tuple[str, VisionAnalysisResult | None, VisionAnalysisError | None]:
            content = contents.get(content_id)
            if content is None:
                return (
                    content_id,
                    None,
                    VisionAnalysisError(
                        "VISION_CONTENT_MISSING", "图片 occurrence 缺少对应内容"
                    ),
                )
            cached = self._read_cache(content, mode)
            if cached is not None:
                return content_id, cached, None
            try:
                async with self._semaphore:
                    result = await client.analyze(
                        content=content,
                        mode=mode,
                        before_provider_call=guarded_before_external_call,
                    )
                self._write_cache(content, mode, result)
                return content_id, result, None
            except VisionAnalysisError as exc:
                return content_id, None, exc
            except VisionExternalCallRejected:
                raise
            except Exception as exc:
                return (
                    content_id,
                    None,
                    VisionAnalysisError("VISION_ANALYSIS_FAILED", "图片分析失败"),
                )

        ordered_content_ids = list(dict.fromkeys(item.content_id for item in occurrences))
        tasks = [
            asyncio.create_task(analyze_one(content_id))
            for content_id in ordered_content_ids
        ]
        try:
            outcomes = await asyncio.gather(*tasks)
        except VisionExternalCallRejected as exc:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            cause = exc.__cause__
            if cause is not None:
                raise cause
            raise
        failures: dict[str, VisionAnalysisError] = {}
        for content_id, result, error in outcomes:
            if result is not None:
                content_results[content_id] = result
            elif error is not None:
                failures[content_id] = error
        for occurrence in occurrences:
            error = failures.get(occurrence.content_id)
            if error is not None:
                warnings.append(
                    DocumentProcessingWarning(
                        error.code, occurrence.source_locator, str(error)
                    )
                )
        results = {
            item.occurrence_id: content_results[item.content_id]
            for item in occurrences
            if item.content_id in content_results
        }
        return VisionAnalysisOutcome(results=results, warnings=warnings)

    def _get_client(self) -> BaseVisionClient:
        if self._client is None:
            if self._client_factory is None:
                from fast_app.components.vision.qwen_vision_client import QwenVisionClient

                self._client = QwenVisionClient(self._settings)
            else:
                self._client = self._client_factory()
        return self._client

    def _validate_budget(
        self,
        contents: Mapping[str, VisionImageContent],
        occurrences: list[VisionImageOccurrence],
    ) -> None:
        # 同一内容可在页眉、模板或多个 block 中重复出现。预算限制真正可能触发
        # Provider 调用的唯一内容数，occurrence 仍全部保留用于位置追溯。
        referenced_content_ids = {item.content_id for item in occurrences}
        if len(referenced_content_ids) > self._settings.vision_max_images_per_document:
            raise VisionAnalysisError(
                "VISION_IMAGE_COUNT_EXCEEDED", "文档唯一图片内容数量超过限制"
            )
        total = 0
        for content in contents.values():
            size = len(content.normalized_bytes)
            if size > self._settings.vision_max_image_bytes:
                raise VisionAnalysisError("VISION_IMAGE_BYTES_EXCEEDED", "单张图片大小超过限制")
            if content.width * content.height > self._settings.vision_max_image_pixels:
                raise VisionAnalysisError("VISION_IMAGE_PIXELS_EXCEEDED", "单张图片像素数超过限制")
            total += size
        if total > self._settings.vision_max_total_normalized_bytes_per_document:
            raise VisionAnalysisError("VISION_DOCUMENT_BYTES_EXCEEDED", "文档图片总大小超过限制")

    def _cache_path(self, content: VisionImageContent, mode: str) -> Path:
        raw = "|".join(
            (
                hashlib.sha256(content.normalized_bytes).hexdigest(),
                self._settings.vision_model_name,
                self._settings.vision_prompt_version,
                self._settings.vision_preprocess_version,
                self._settings.vision_schema_version,
                mode,
            )
        )
        key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return Path(self._settings.vision_cache_dir) / f"{key}.json"

    def _read_cache(self, content: VisionImageContent, mode: str) -> VisionAnalysisResult | None:
        if not self._settings.vision_cache_enabled:
            return None
        path = self._cache_path(content, mode)
        try:
            return VisionAnalysisResult.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def _write_cache(self, content: VisionImageContent, mode: str, result: VisionAnalysisResult) -> None:
        if not self._settings.vision_cache_enabled:
            return
        path = self._cache_path(content, mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(result.model_dump(mode="json"), stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        os.replace(temp, path)
        self._prune_cache(path.parent)

    def _prune_cache(self, root: Path) -> None:
        """按保留期和总字节上限清理不包含原图的敏感结果缓存。"""

        try:
            entries = [item for item in root.glob("*.json") if item.is_file()]
        except OSError:
            return
        cutoff = time.time() - self._settings.vision_cache_retention_days * 86400
        retained: list[tuple[Path, float, int]] = []
        for entry in entries:
            try:
                stat = entry.stat()
                if stat.st_mtime < cutoff:
                    entry.unlink(missing_ok=True)
                else:
                    retained.append((entry, stat.st_mtime, stat.st_size))
            except OSError:
                continue
        total = sum(size for _, _, size in retained)
        for entry, _, size in sorted(retained, key=lambda item: item[1]):
            if total <= self._settings.vision_cache_max_bytes:
                break
            try:
                entry.unlink(missing_ok=True)
                total -= size
            except OSError:
                continue


def render_vision_result(result: VisionAnalysisResult) -> str:
    """把结构化视觉信息渲染为进入 Chunk 的稳定纯文本。"""

    parts = []
    if result.extracted_text.strip():
        parts.append("Image text:\n" + result.extracted_text.strip())
    if result.summary.strip():
        parts.append("Image summary:\n" + result.summary.strip())
    if result.table_markdown:
        parts.append("Image table:\n" + result.table_markdown.strip())
    if result.visual_facts:
        parts.append("Visual facts:\n" + "\n".join(f"- {fact}" for fact in result.visual_facts))
    return "\n\n".join(parts)


__all__ = [
    "BaseVisionClient",
    "BeforeExternalCall",
    "DocumentProcessingWarning",
    "DocumentVisionService",
    "VisionAnalysisError",
    "VisionAnalysisOutcome",
    "render_vision_result",
]
