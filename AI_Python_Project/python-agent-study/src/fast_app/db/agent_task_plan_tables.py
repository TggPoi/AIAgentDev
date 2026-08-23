"""Agent TaskPlan 多 Worker 一致性的事实表。

四张表共同构成问题十二的数据库一致性层：

- ``agent_task_plans``：TaskPlan 唯一事实快照与执行租约（record_version CAS、
  lease_fence_token、单调状态转换）。
- ``agent_task_plan_runtime_records``：Deep Document RuntimeRecord 恢复登记表，
  独立 record_version CAS，写入时同时校验父 TaskPlan 租约。
- ``agent_task_plan_commands``：confirm/retry/cancel 的幂等命令记录，
  (task_plan_id, operation, idempotency_key) 唯一。
- ``agent_task_capacity_slots``：多实例共享的复杂任务容量槽，槽位自身也有
  租约与 fencing token。

业务并发 SQL 只允许写在 ``fast_app.services.agent_tasks.agent_task_plan_repository``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from fast_app.db.base import Base


TASK_PLAN_STATUSES = (
    "created",
    "preparing_confirmation",
    "waiting_confirmation",
    "executing_confirmed",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
)


class AgentTaskPlanTable(Base):
    __tablename__ = "agent_task_plans"

    task_plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    task_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    record_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_fence_token: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    active_operation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    capacity_workload_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    capacity_slot_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'created','preparing_confirmation','waiting_confirmation',"
            "'executing_confirmed','completed',"
            "'completed_with_warnings','failed','cancelled')",
            name="ck_agent_task_plans_status",
        ),
        CheckConstraint(
            "record_version >= 1", name="ck_agent_task_plans_record_version"
        ),
        CheckConstraint(
            "lease_fence_token >= 0",
            name="ck_agent_task_plans_lease_fence_token",
        ),
        CheckConstraint(
            "(capacity_workload_type IS NULL) = (capacity_slot_no IS NULL)",
            name="ck_agent_task_plans_capacity_pair",
        ),
        Index("idx_agent_task_plans_owner_created", "owner_user_id", "created_at"),
        Index(
            "idx_agent_task_plans_owner_updated_id",
            "owner_user_id",
            updated_at.desc(),
            task_plan_id.desc(),
        ),
        Index(
            "idx_agent_task_plans_owner_session_updated_id",
            "owner_user_id",
            "session_id",
            updated_at.desc(),
            task_plan_id.desc(),
        ),
        Index("idx_agent_task_plans_status_updated", "status", "updated_at"),
        Index("idx_agent_task_plans_lease_until", "lease_until"),
    )


class AgentTaskPlanRuntimeRecordTable(Base):
    __tablename__ = "agent_task_plan_runtime_records"

    task_plan_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("agent_task_plans.task_plan_id", ondelete="CASCADE"),
        primary_key=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    record_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "record_version >= 1",
            name="ck_agent_task_plan_runtime_record_version",
        ),
        Index("idx_agent_task_plan_runtime_expires", "expires_at"),
    )


class AgentTaskPlanCommandTable(Base):
    __tablename__ = "agent_task_plan_commands"

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_plan_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("agent_task_plans.task_plan_id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_fence_token: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "task_plan_id",
            "operation",
            "idempotency_key",
            name="uq_agent_task_plan_command_idempotency",
        ),
        CheckConstraint(
            "status IN ('running','succeeded','failed','rejected','cancelled')",
            name="ck_agent_task_plan_commands_status",
        ),
        Index("idx_agent_task_plan_commands_task_created", "task_plan_id", "created_at"),
    )


class AgentTaskCapacitySlotTable(Base):
    __tablename__ = "agent_task_capacity_slots"

    workload_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    slot_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_fence_token: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    task_plan_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("slot_no >= 1", name="ck_agent_task_capacity_slot_no"),
        CheckConstraint(
            "workload_type IN ('research','document')",
            name="ck_agent_task_capacity_workload_type",
        ),
        CheckConstraint(
            "lease_fence_token >= 0",
            name="ck_agent_task_capacity_fence_token",
        ),
        Index("idx_agent_task_capacity_lease", "workload_type", "lease_until"),
    )


__all__ = [
    "AgentTaskCapacitySlotTable",
    "AgentTaskPlanCommandTable",
    "AgentTaskPlanRuntimeRecordTable",
    "AgentTaskPlanTable",
    "TASK_PLAN_STATUSES",
]
