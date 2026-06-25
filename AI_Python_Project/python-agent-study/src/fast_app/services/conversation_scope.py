import hashlib
import re

from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.rag_chat_schema import RagChatRequest


_SAFE_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def build_scoped_conversation_id(user_id: str, session_id: str) -> str:
    """把 user_id + session_id 映射成后端内部 conversation_id。

    session_id 只在某个用户命名空间内有意义。这里通过稳定 hash 防止不同用户
    使用同名 session_id 时写入同一个 Redis key 或 PostgreSQL conversation。
    """

    normalized_user_id = user_id.strip()
    normalized_session_id = session_id.strip()
    digest = hashlib.sha256(
        f"{normalized_user_id}\0{normalized_session_id}".encode("utf-8")
    ).hexdigest()[:16]

    user_part = _safe_id_component(normalized_user_id, max_length=24)
    session_part = _safe_id_component(normalized_session_id, max_length=48)

    return f"user:{user_part}:session:{session_part}:{digest}"


def scope_rag_chat_request(
    req: RagChatRequest,
    user: CurrentUserContext,
) -> RagChatRequest:
    """生成带用户隔离会话 ID 的内部请求对象。

    对外请求体仍然只有 session_id；如果 session_id 为空，本次请求保持单轮语义。
    如果 session_id 存在，下游 memory / summary / persistence 都使用 scoped id。
    """

    scoped_req = req.model_copy()
    scoped_req._current_user_id = user.user_id
    scoped_req._external_session_id = req.session_id

    if req.session_id is not None:
        scoped_req.session_id = build_scoped_conversation_id(
            user_id=user.user_id,
            session_id=req.session_id,
        )

    return scoped_req


def get_request_user_id(req: RagChatRequest) -> str | None:
    """读取服务端内部绑定的 user_id；不会从请求体读取用户身份。"""

    return req._current_user_id


def get_request_external_session_id(req: RagChatRequest) -> str | None:
    """读取客户端原始 session_id，用于日志和持久化 metadata 追溯。"""

    return req._external_session_id or req.session_id


def _safe_id_component(value: str, max_length: int) -> str:
    normalized = _SAFE_COMPONENT_PATTERN.sub("_", value).strip("_")
    if not normalized:
        normalized = "blank"

    return normalized[:max_length]


__all__ = [
    "build_scoped_conversation_id",
    "get_request_external_session_id",
    "get_request_user_id",
    "scope_rag_chat_request",
]
