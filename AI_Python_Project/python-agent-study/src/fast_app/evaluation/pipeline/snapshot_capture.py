import base64
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from fast_app.core.config import Settings
from fast_app.core.request_context import get_request_id, get_trace_id
from fast_app.domain.rag_models import RagContext, RetrievedDoc, ScoreBreakdown
from fast_app.evaluation.contracts import get_metric_versions
from fast_app.evaluation.pipeline.models import (
    EvaluationError,
    EvaluationSnapshot,
    EvaluationSnapshotPayload,
    EvaluationSnapshotSecurityMode,
    SnapshotContext,
    SnapshotDocument,
    SnapshotMapping,
    SnapshotPrincipal,
    SnapshotRequest,
    SnapshotRetrievalStage,
    SnapshotScoreBreakdown,
    SnapshotTargetIdentity,
    SnapshotValue,
)
from fast_app.evaluation.retrieval.models import RetrievalStage
from fast_app.schemas.rag_chat_schema import RagChatRequest, RagChatResponse


EVALUATION_SNAPSHOT_VERSION = "evaluation_snapshot.v1"
_SNAPSHOT_ASSOCIATED_DATA = EVALUATION_SNAPSHOT_VERSION.encode("utf-8")


class SnapshotContentUnavailableError(ValueError):
    """请求读取 redacted 快照中未保存的敏感内容。"""


class SnapshotIntegrityError(ValueError):
    """快照哈希或 AES-GCM 认证校验失败。"""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_text(value: str | None) -> str:
    serialized = "null" if value is None else value
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _sha256_mapping(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decode_key(encoded_key: str) -> bytes:
    return base64.b64decode(encoded_key, altchars=b"-_", validate=True)


class _SnapshotProtector:
    """把明文值按一个配置模式转换为可校验的安全快照值。"""

    def __init__(self, settings: Settings):
        self.mode: EvaluationSnapshotSecurityMode = (
            settings.eval_snapshot_security_mode
        )
        self.active_key_id = settings.eval_snapshot_encryption_active_key_id.strip()
        raw_key_ring = (
            json.loads(settings.eval_snapshot_encryption_keys_json)
            if self.mode == "encrypted"
            else {}
        )
        self.key_ring = {
            str(key_id): _decode_key(str(encoded_key))
            for key_id, encoded_key in raw_key_ring.items()
        }

    def protect_text(self, value: str | None) -> SnapshotValue:
        value_hash = _sha256_text(value)
        if self.mode == "plain":
            return SnapshotValue(
                storage="plain",
                sha256=value_hash,
                is_null=value is None,
                plaintext=value,
            )
        if self.mode == "redacted":
            return SnapshotValue(
                storage="redacted",
                sha256=value_hash,
                is_null=value is None,
            )
        if value is None:
            return SnapshotValue(
                storage="encrypted",
                sha256=value_hash,
                is_null=True,
            )

        nonce = os.urandom(12)
        ciphertext = AESGCM(self.key_ring[self.active_key_id]).encrypt(
            nonce,
            value.encode("utf-8"),
            _SNAPSHOT_ASSOCIATED_DATA,
        )
        return SnapshotValue(
            storage="encrypted",
            sha256=value_hash,
            ciphertext=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
            key_id=self.active_key_id,
        )

    def protect_mapping(self, value: Mapping[str, object]) -> SnapshotMapping:
        normalized = json.loads(_canonical_json(value))
        value_hash = _sha256_mapping(normalized)
        if self.mode == "plain":
            return SnapshotMapping(
                storage="plain",
                sha256=value_hash,
                plaintext=normalized,
            )
        if self.mode == "redacted":
            return SnapshotMapping(
                storage="redacted",
                sha256=value_hash,
            )

        nonce = os.urandom(12)
        plaintext = _canonical_json(normalized).encode("utf-8")
        ciphertext = AESGCM(self.key_ring[self.active_key_id]).encrypt(
            nonce,
            plaintext,
            _SNAPSHOT_ASSOCIATED_DATA,
        )
        return SnapshotMapping(
            storage="encrypted",
            sha256=value_hash,
            ciphertext=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
            key_id=self.active_key_id,
        )


def _build_key_ring(settings: Settings) -> dict[str, bytes]:
    raw_key_ring = json.loads(settings.eval_snapshot_encryption_keys_json)
    return {
        str(key_id): _decode_key(str(encoded_key))
        for key_id, encoded_key in raw_key_ring.items()
    }


def read_snapshot_value(
    value: SnapshotValue,
    settings: Settings | None = None,
) -> str | None:
    """读取明文或解密值，并在返回前验证内容哈希。"""

    if value.is_null:
        plaintext = None
    elif value.storage == "plain":
        plaintext = value.plaintext
    elif value.storage == "redacted":
        raise SnapshotContentUnavailableError("redacted snapshot 不保存敏感文本")
    else:
        if settings is None:
            raise SnapshotContentUnavailableError("读取 encrypted snapshot 需要 key ring")
        key_ring = _build_key_ring(settings)
        if value.key_id not in key_ring:
            raise SnapshotContentUnavailableError(
                f"snapshot key_id={value.key_id!r} 不在当前 key ring"
            )
        try:
            plaintext = AESGCM(key_ring[value.key_id]).decrypt(
                base64.urlsafe_b64decode(value.nonce or ""),
                base64.urlsafe_b64decode(value.ciphertext or ""),
                _SNAPSHOT_ASSOCIATED_DATA,
            ).decode("utf-8")
        except (InvalidTag, ValueError) as exc:
            raise SnapshotIntegrityError("snapshot encrypted value 认证失败") from exc

    if _sha256_text(plaintext) != value.sha256:
        raise SnapshotIntegrityError("snapshot value 内容哈希不匹配")
    return plaintext


def read_snapshot_mapping(
    value: SnapshotMapping,
    settings: Settings | None = None,
) -> dict[str, object]:
    """读取明文或解密映射，并在返回前验证规范化 JSON 哈希。"""

    if value.storage == "plain":
        plaintext = value.plaintext or {}
    elif value.storage == "redacted":
        raise SnapshotContentUnavailableError("redacted snapshot 不保存敏感映射")
    else:
        if settings is None:
            raise SnapshotContentUnavailableError("读取 encrypted snapshot 需要 key ring")
        key_ring = _build_key_ring(settings)
        if value.key_id not in key_ring:
            raise SnapshotContentUnavailableError(
                f"snapshot key_id={value.key_id!r} 不在当前 key ring"
            )
        try:
            decoded = AESGCM(key_ring[value.key_id]).decrypt(
                base64.urlsafe_b64decode(value.nonce or ""),
                base64.urlsafe_b64decode(value.ciphertext or ""),
                _SNAPSHOT_ASSOCIATED_DATA,
            )
            plaintext = json.loads(decoded.decode("utf-8"))
        except (InvalidTag, ValueError, json.JSONDecodeError) as exc:
            raise SnapshotIntegrityError("snapshot encrypted mapping 认证失败") from exc

    if not isinstance(plaintext, dict):
        raise SnapshotIntegrityError("snapshot mapping 解码后不是 JSON object")
    if _sha256_mapping(plaintext) != value.sha256:
        raise SnapshotIntegrityError("snapshot mapping 内容哈希不匹配")
    return plaintext


def _optional_metadata_text(metadata: Mapping[str, Any], name: str) -> str | None:
    value = metadata.get(name)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


class EvaluationSnapshotCollector:
    """一次 Eval 调用的内部采集器；调用方只需记录阶段并最终 finalize。"""

    def __init__(
        self,
        *,
        req: RagChatRequest,
        settings: Settings,
        pipeline_provider: str,
        eval_principal_id: str | None,
    ) -> None:
        self.req = req
        self.settings = settings
        self.pipeline_provider = pipeline_provider
        self.protector = _SnapshotProtector(settings)
        self.eval_principal_id = eval_principal_id or req._current_user_id
        self.effective_query = req.query
        self.stages = {
            stage: SnapshotRetrievalStage(
                name=stage,
                status="not_executed",
            )
            for stage in ("vector", "keyword", "rrf", "rerank")
        }
        self.final_context: SnapshotContext | None = None

    def _snapshot_document(self, doc: RetrievedDoc, rank: int) -> SnapshotDocument:
        metadata = dict(doc.metadata)
        return SnapshotDocument(
            rank=rank,
            id=doc.id,
            source=doc.source,
            content=self.protector.protect_text(doc.content),
            metadata=self.protector.protect_mapping(metadata),
            scores=SnapshotScoreBreakdown(
                score=doc.score,
                vector_score=doc.scores.vector_score,
                keyword_score=doc.scores.keyword_score,
                rrf_score=doc.scores.rrf_score,
                rerank_score=doc.scores.rerank_score,
            ),
            title=(
                self.protector.protect_text(doc.title)
                if doc.title is not None
                else None
            ),
            doc_id=_optional_metadata_text(metadata, "doc_id"),
            logical_chunk_id=_optional_metadata_text(metadata, "logical_chunk_id"),
            logical_parent_id=_optional_metadata_text(metadata, "logical_parent_id"),
            parent_id=_optional_metadata_text(metadata, "parent_id"),
            source_revision=_optional_metadata_text(metadata, "source_revision"),
            retrieval_sources=list(doc.retrieval_sources),
        )

    def record_retrieval_stage(
        self,
        stage: RetrievalStage,
        docs: list[RetrievedDoc],
        *,
        query: str | None = None,
    ) -> None:
        if query is not None:
            self.effective_query = query
        self.stages[stage] = SnapshotRetrievalStage(
            name=stage,
            status="captured",
            documents=[
                self._snapshot_document(doc, rank)
                for rank, doc in enumerate(docs, start=1)
            ],
        )

    def record_retrieval_error(
        self,
        stage: RetrievalStage,
        error_code: str,
        *,
        query: str | None = None,
    ) -> None:
        if query is not None:
            self.effective_query = query
        self.stages[stage] = SnapshotRetrievalStage(
            name=stage,
            status="error",
            error_code=error_code,
        )

    def record_final_context(self, context: RagContext) -> None:
        self.effective_query = context.query
        self.final_context = SnapshotContext(
            query=self.protector.protect_text(context.query),
            context_text=self.protector.protect_text(context.context_text),
            documents=[
                self._snapshot_document(doc, rank)
                for rank, doc in enumerate(context.docs, start=1)
            ],
        )

    def finalize(
        self,
        *,
        response: RagChatResponse | None,
        latency_ms: float,
        error: EvaluationError | None = None,
    ) -> EvaluationSnapshot:
        effective_query = response.query if response is not None else self.effective_query
        source_ids = [source.id for source in response.sources] if response else []
        source_revisions = sorted(
            {
                revision
                for stage in self.stages.values()
                for document in stage.documents
                if (revision := document.source_revision) is not None
            }
            | {
                revision
                for document in (
                    self.final_context.documents if self.final_context is not None else []
                )
                if (revision := document.source_revision) is not None
            }
        )
        permission_scope = (
            self.req._retrieval_permission_scope.model_dump()
            if self.req._retrieval_permission_scope is not None
            else {}
        )
        payload = EvaluationSnapshotPayload(
            raw_query=self.protector.protect_text(self.req.query),
            effective_query=self.protector.protect_text(effective_query),
            request=SnapshotRequest(
                mode=self.req.mode,
                top_k=self.req.top_k,
                candidate_k=max(self.req.candidate_k or self.req.top_k, self.req.top_k),
                min_score=self.req.min_score,
                filters=self.protector.protect_mapping(self.req.filters.model_dump()),
            ),
            principal=SnapshotPrincipal(
                eval_principal_id=self.protector.protect_text(
                    self.eval_principal_id
                ),
                permission_scope=self.protector.protect_mapping(permission_scope),
            ),
            knowledge_version=(
                self.req._knowledge_version
                if self.req._knowledge_version is not None
                else response.knowledge_version if response is not None else None
            ),
            source_revisions=source_revisions,
            target=SnapshotTargetIdentity(
                pipeline_provider=self.pipeline_provider,
                vector_retriever=(
                    f"{self.settings.vector_retriever_provider}:"
                    f"{self.settings.embedding_model_name}"
                ),
                keyword_retriever=(
                    f"{self.settings.keyword_retriever_provider}:"
                    f"{self.settings.elasticsearch_index_name}"
                ),
                reranker=(
                    f"{self.settings.reranker_provider}:"
                    f"{self.settings.rerank_model_name}"
                ),
                generator=(
                    f"{self.settings.llm_provider}:{self.settings.llm_model_name}"
                ),
            ),
            retrieval_stages=dict(self.stages),
            final_context=self.final_context,
            answer=self.protector.protect_text(
                response.answer if response is not None else None
            ),
            source_ids=source_ids,
            prompt_version=self.settings.rag_prompt_version,
            metric_versions=get_metric_versions(),
            request_id=(
                response.request_id if response and response.request_id else get_request_id()
            ),
            trace_id=(
                response.trace_id if response and response.trace_id else get_trace_id()
            ),
            latency_ms=latency_ms,
            error=error,
        )
        payload_hash = _sha256_mapping(asdict(payload))
        return EvaluationSnapshot(
            snapshot_id=uuid4().hex,
            snapshot_version=EVALUATION_SNAPSHOT_VERSION,
            captured_at=datetime.now(timezone.utc).isoformat(),
            security_mode=self.settings.eval_snapshot_security_mode,
            content_replayable=(
                self.settings.eval_snapshot_security_mode != "redacted"
            ),
            payload_hash=payload_hash,
            payload=payload,
        )


_snapshot_collector_var: ContextVar[EvaluationSnapshotCollector | None] = ContextVar(
    "evaluation_snapshot_collector",
    default=None,
)


@contextmanager
def capture_evaluation_snapshot(
    *,
    req: RagChatRequest,
    settings: Settings,
    pipeline_provider: str,
    eval_principal_id: str | None = None,
) -> Iterator[EvaluationSnapshotCollector]:
    """在当前异步上下文内开启一次隔离的 Eval snapshot 旁路采集。"""

    collector = EvaluationSnapshotCollector(
        req=req,
        settings=settings,
        pipeline_provider=pipeline_provider,
        eval_principal_id=eval_principal_id,
    )
    token = _snapshot_collector_var.set(collector)
    try:
        yield collector
    finally:
        _snapshot_collector_var.reset(token)


def record_snapshot_retrieval_stage(
    stage: RetrievalStage,
    docs: list[RetrievedDoc],
    *,
    query: str | None = None,
) -> None:
    """当前未开启 Eval capture 时立即返回。"""

    collector = _snapshot_collector_var.get()
    if collector is not None:
        collector.record_retrieval_stage(stage, docs, query=query)


def record_snapshot_retrieval_error(
    stage: RetrievalStage,
    error_code: str,
    *,
    query: str | None = None,
) -> None:
    """记录一个检索阶段失败；普通请求不产生任何副作用。"""

    collector = _snapshot_collector_var.get()
    if collector is not None:
        collector.record_retrieval_error(stage, error_code, query=query)


def record_snapshot_final_context(context: RagContext) -> None:
    """冻结模型实际收到的最终上下文；普通请求不产生任何副作用。"""

    collector = _snapshot_collector_var.get()
    if collector is not None:
        collector.record_final_context(context)


def verify_snapshot_integrity(
    snapshot: EvaluationSnapshot,
    settings: Settings | None = None,
) -> None:
    """校验整体 payload 及其中所有可读取敏感值的哈希与认证标签。"""

    if _sha256_mapping(asdict(snapshot.payload)) != snapshot.payload_hash:
        raise SnapshotIntegrityError("evaluation snapshot payload_hash 不匹配")

    values = [
        snapshot.payload.raw_query,
        snapshot.payload.effective_query,
        snapshot.payload.answer,
        snapshot.payload.principal.eval_principal_id,
    ]
    mappings = [
        snapshot.payload.request.filters,
        snapshot.payload.principal.permission_scope,
    ]
    for stage in snapshot.payload.retrieval_stages.values():
        for document in stage.documents:
            values.append(document.content)
            if document.title is not None:
                values.append(document.title)
            mappings.append(document.metadata)
    if snapshot.payload.final_context is not None:
        values.extend(
            [
                snapshot.payload.final_context.query,
                snapshot.payload.final_context.context_text,
            ]
        )
        for document in snapshot.payload.final_context.documents:
            values.append(document.content)
            if document.title is not None:
                values.append(document.title)
            mappings.append(document.metadata)

    for value in values:
        if value.storage != "redacted":
            read_snapshot_value(value, settings)
    for mapping in mappings:
        if mapping.storage != "redacted":
            read_snapshot_mapping(mapping, settings)


def build_retrieved_docs_from_snapshot(
    snapshot: EvaluationSnapshot,
    settings: Settings | None = None,
) -> list[RetrievedDoc]:
    """仅从冻结最终上下文重建检索评测输入，不再次调用被测 Pipeline。"""

    context = snapshot.payload.final_context
    if context is None:
        return []

    docs: list[RetrievedDoc] = []
    for document in context.documents:
        try:
            content = read_snapshot_value(document.content, settings) or ""
        except SnapshotContentUnavailableError:
            content = ""
        try:
            metadata = read_snapshot_mapping(document.metadata, settings)
        except SnapshotContentUnavailableError:
            metadata = {}
        if document.logical_chunk_id is not None:
            metadata.setdefault("logical_chunk_id", document.logical_chunk_id)
        if document.doc_id is not None:
            metadata.setdefault("doc_id", document.doc_id)
        if document.source_revision is not None:
            metadata.setdefault("source_revision", document.source_revision)
        title = None
        if document.title is not None:
            try:
                title = read_snapshot_value(document.title, settings)
            except SnapshotContentUnavailableError:
                title = None
        docs.append(
            RetrievedDoc(
                id=document.id,
                content=content,
                score=document.scores.score,
                source=document.source,
                title=title,
                metadata=metadata,
                retrieval_sources=list(document.retrieval_sources),
                scores=ScoreBreakdown(
                    vector_score=document.scores.vector_score,
                    keyword_score=document.scores.keyword_score,
                    rrf_score=document.scores.rrf_score,
                    rerank_score=document.scores.rerank_score,
                ),
            )
        )
    return docs
