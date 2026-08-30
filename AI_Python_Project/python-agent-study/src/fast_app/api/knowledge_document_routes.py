from __future__ import annotations

import re
import unicodedata
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Path, Query, Response

from fast_app.dependencies.knowledge_document_dependencies import (
    get_knowledge_document_read_service,
)
from fast_app.dependencies.user_context import get_current_user_context
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.knowledge_document_schema import (
    KnowledgeDocumentContentResponse,
    KnowledgeDocumentDetail,
    KnowledgeDocumentListResponse,
)
from fast_app.schemas.error_schema import RequestValidationErrorResponse
from fast_app.services.knowledge.knowledge_document_read_service import (
    KnowledgeDocumentReadService,
)


router = APIRouter(prefix="/knowledge/documents", tags=["knowledge-documents"])

_KNOWLEDGE_DOCUMENT_VALIDATION_ERROR_RESPONSES = {
    422: {
        "model": RequestValidationErrorResponse,
        "description": "请求字段校验失败；只返回 allowlisted 字段的安全错误投影。",
    }
}


@router.get(
    "",
    response_model=KnowledgeDocumentListResponse,
    responses=_KNOWLEDGE_DOCUMENT_VALIDATION_ERROR_RESPONSES,
)
async def list_knowledge_documents_endpoint(
    cursor: str | None = Query(default=None, description="上一页返回的不透明 keyset cursor。"),
    limit: int = Query(default=20, ge=1, le=100, description="本页最多返回的文档数。"),
    query: str | None = Query(
        default=None,
        max_length=255,
        description="按仓库路径、文件名或精确 doc_id 文本筛选。",
    ),
    department_code: str | None = Query(
        default=None,
        max_length=64,
        description="可选文档所属部门筛选，只会缩小服务端 ACL 结果。",
    ),
    document_type: Literal[
        "markdown",
        "text",
        "pdf",
        "powerpoint",
        "spreadsheet",
        "word",
    ]
    | None = Query(default=None, description="可选文档格式筛选。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: KnowledgeDocumentReadService = Depends(
        get_knowledge_document_read_service
    ),
) -> KnowledgeDocumentListResponse:
    return await service.list_documents(
        user,
        cursor=cursor,
        limit=limit,
        query=query,
        department_code=department_code,
        document_type=document_type,
    )


@router.get(
    "/{doc_id}",
    response_model=KnowledgeDocumentDetail,
    responses=_KNOWLEDGE_DOCUMENT_VALIDATION_ERROR_RESPONSES,
)
async def get_knowledge_document_detail_endpoint(
    doc_id: str = Path(min_length=1, max_length=64, description="稳定 GitLab 文档 ID。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: KnowledgeDocumentReadService = Depends(
        get_knowledge_document_read_service
    ),
) -> KnowledgeDocumentDetail:
    return await service.get_detail(user, doc_id)


@router.get(
    "/{doc_id}/content",
    response_model=KnowledgeDocumentContentResponse,
    responses=_KNOWLEDGE_DOCUMENT_VALIDATION_ERROR_RESPONSES,
)
async def get_knowledge_document_content_endpoint(
    doc_id: str = Path(min_length=1, max_length=64, description="稳定 GitLab 文档 ID。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: KnowledgeDocumentReadService = Depends(
        get_knowledge_document_read_service
    ),
) -> KnowledgeDocumentContentResponse:
    return await service.get_content(user, doc_id)


@router.get(
    "/{doc_id}/download",
    response_class=Response,
    responses={
        200: {
            "description": "下载当前授权可见的文档原始内容。",
            "headers": {
                "Content-Disposition": {
                    "description": "符合 RFC 5987 的附件文件名。",
                    "schema": {"type": "string"},
                },
                "X-Source-Revision": {
                    "description": "下载内容对应的稳定源版本。",
                    "schema": {"type": "string"},
                },
            },
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
        },
        **_KNOWLEDGE_DOCUMENT_VALIDATION_ERROR_RESPONSES,
    },
)
async def download_knowledge_document_endpoint(
    doc_id: str = Path(min_length=1, max_length=64, description="稳定 GitLab 文档 ID。"),
    user: CurrentUserContext = Depends(get_current_user_context),
    service: KnowledgeDocumentReadService = Depends(
        get_knowledge_document_read_service
    ),
) -> Response:
    download = await service.get_download(user, doc_id)
    return Response(
        content=download.content,
        media_type=download.media_type,
        headers={
            "Content-Disposition": _content_disposition(download.file_name),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Source-Revision": download.source_revision,
        },
    )


def _content_disposition(file_name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", file_name).encode(
        "ascii",
        "ignore",
    ).decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip(" ._")
    ascii_name = (ascii_name or "document")[:120]
    encoded_name = quote(file_name, safe="")
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )


__all__ = ["router"]
