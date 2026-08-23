from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from fast_app.domain.agent_task_plan import AgentTaskPlanStatus
from fast_app.domain.user_context import CurrentUserContext
from fast_app.schemas.agent_task_plan_schema import (
    AgentTaskPlanListItem,
    AgentTaskPlanListResponse,
)
from fast_app.services.agent_tasks.agent_task_plan_store import AgentTaskPlanStore
from fast_app.services.exceptions import (
    AgentTaskPlanCursorInvalidError,
    AuthenticationError,
)


class AgentTaskPlanCatalogService:
    """提供当前用户 TaskPlan 目录，不暴露内部 snapshot、租约或 checkpoint。"""

    def __init__(self, store: AgentTaskPlanStore) -> None:
        self._store = store

    async def list_plans(
        self,
        user: CurrentUserContext,
        *,
        cursor: str | None,
        limit: int,
        status: AgentTaskPlanStatus | None,
        session_id: str | None,
    ) -> AgentTaskPlanListResponse:
        if not user.is_authenticated:
            raise AuthenticationError("TaskPlan 列表只允许已认证用户")
        cursor_updated_at, cursor_task_plan_id = _decode_cursor(cursor)
        records, has_more = await self._store.list_owned(
            owner_user_id=user.user_id,
            limit=limit,
            status=status.value if status is not None else None,
            session_id=session_id,
            cursor_updated_at=cursor_updated_at,
            cursor_task_plan_id=cursor_task_plan_id,
        )
        items = [
            AgentTaskPlanListItem(
                task_plan_id=record.task_plan_id,
                task_kind=record.task_kind,
                status=record.status,
                session_id=record.session_id,
                summary=" ".join(record.summary.split())[:200],
                requires_confirmation=(
                    record.status == AgentTaskPlanStatus.WAITING_CONFIRMATION.value
                ),
                error_code=record.error_code,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ]
        return AgentTaskPlanListResponse(
            items=items,
            next_cursor=(
                _encode_cursor(records[-1].updated_at, records[-1].task_plan_id)
                if has_more and records
                else None
            ),
        )


def _encode_cursor(updated_at: datetime, task_plan_id: str) -> str:
    payload = json.dumps(
        {"updated_at": updated_at.isoformat(), "task_plan_id": task_plan_id},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError
        updated_at = datetime.fromisoformat(payload["updated_at"])
        task_plan_id = payload["task_plan_id"]
        if (
            updated_at.tzinfo is None
            or not isinstance(task_plan_id, str)
            or not task_plan_id
        ):
            raise ValueError
        return updated_at, task_plan_id
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise AgentTaskPlanCursorInvalidError("TaskPlan 列表 cursor 无效") from exc


__all__ = ["AgentTaskPlanCatalogService"]
