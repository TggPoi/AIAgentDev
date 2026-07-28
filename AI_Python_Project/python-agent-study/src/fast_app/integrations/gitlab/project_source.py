from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from fast_app.domain.knowledge_models import LoadedDocument
from fast_app.ingestion.processing.markdown_hierarchy import (
    MARKDOWN_CHUNK_STRATEGY_VERSION,
)


PARSER_VERSION = "gitlab_source_v1"
SUPPORTED_DOCUMENT_TYPES = {
    ".md": "markdown",
    ".txt": "text",
    ".pptx": "powerpoint",
    ".xlsx": "spreadsheet",
}


class GitLabProjectSource:
    def __init__(
        self,
        *,
        host_id: str,
        project_id: int,
        source_id: str,
        department_code: str,
        default_visibility: str,
    ) -> None:
        self.host_id = host_id.strip().lower()
        self.project_id = project_id
        self.source_id = source_id
        self.department_code = department_code
        self.default_visibility = default_visibility

    def normalize_path(self, repository_path: str) -> str:
        value = repository_path.replace("\\", "/").strip("/")
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("GitLab repository_path 非法")
        return path.as_posix()

    def source_uri(self, repository_path: str) -> str:
        path = self.normalize_path(repository_path)
        return f"gitlab://{self.host_id}/{self.project_id}/{path}"

    def doc_id(self, repository_path: str) -> str:
        path = self.normalize_path(repository_path)
        raw = f"gitlab:{self.host_id}:{self.project_id}:{path}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def document_type(self, repository_path: str) -> str | None:
        suffix = PurePosixPath(repository_path).suffix.lower()
        return SUPPORTED_DOCUMENT_TYPES.get(suffix)

    def default_acl(self) -> dict[str, Any]:
        if self.default_visibility == "public":
            return {
                "visibility": "public",
                "allowed_departments": [],
                "allowed_users": [],
                "permission_source": "gitlab_source",
            }
        return {
            "visibility": "department",
            "allowed_departments": [self.department_code],
            "allowed_users": [],
            "permission_source": "gitlab_source",
        }

    def build_text_document(
        self,
        *,
        repository_path: str,
        content: str,
        source_revision: str,
        acl: dict[str, Any] | None = None,
    ) -> LoadedDocument:
        path = self.normalize_path(repository_path)
        document_type = self.document_type(path)
        if document_type not in {"markdown", "text"}:
            raise ValueError("build_text_document 只接收 Markdown/TXT")
        metadata = {
            "doc_id": self.doc_id(path),
            "source_path": path,
            "source_uri": self.source_uri(path),
            "source_id": self.source_id,
            "source_revision": source_revision,
            "document_type": document_type,
            "file_name": PurePosixPath(path).name,
            "file_extension": PurePosixPath(path).suffix,
            **(acl or self.default_acl()),
        }
        return LoadedDocument(
            source_path=path,
            content=content,
            document_type=document_type,
            metadata=metadata,
        )

    def chunk_config_fingerprint(self, values: dict[str, Any]) -> str:
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def parser_version(self) -> str:
        return PARSER_VERSION

    @property
    def chunk_strategy_version(self) -> str:
        return MARKDOWN_CHUNK_STRATEGY_VERSION


__all__ = [
    "GitLabProjectSource",
    "PARSER_VERSION",
    "SUPPORTED_DOCUMENT_TYPES",
]
