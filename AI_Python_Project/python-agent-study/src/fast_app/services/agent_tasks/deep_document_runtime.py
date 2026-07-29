"""Deep Document Agent 的 PostgreSQL checkpoint、运行事实和生命周期。

这个模块同时管理两类数据，阅读时不要将它们混在一起：

1. ``PostgresSaver`` 保存 LangGraph 的执行现场，例如节点进度、消息、Todo 和
   StateBackend 中的虚拟文件。这部分由 LangGraph 自动读写，并使用 AES 加密。
2. ``PostgresStore`` 保存业务层的恢复登记表，例如 ACL 指纹、源文件 SHA、
   ``record_version`` 和过期时间。Store 中不保存完整文档正文。

``DeepDocumentRuntime`` 将两者组合为同一个 TaskPlan 的可恢复运行环境：
业务层先根据 Store 判断“是否允许恢复”，再由 Saver 告诉 LangGraph
“从哪个执行状态继续”。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.postgres import PostgresStore
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from fast_app.core.config import Settings
from fast_app.domain.rag_models import RetrievalFilters
from fast_app.domain.user_context import CurrentUserContext
from fast_app.services.exceptions import (
    DocumentAgentCheckpointConflictError,
    DocumentAgentCheckpointUnavailableError,
)


# LangGraph Store 通过 ``namespace + key`` 定位数据。这里固定 namespace，
# 再以 task_plan_id 作为 key，避免与其他 Store 业务数据冲突。
_RUNTIME_NAMESPACE = ("deep_document_runtime",)
# Store 数据结构的版本，与每次更新递增的 record_version 含义不同。
_RUNTIME_SCHEMA_VERSION = 1


class _AsyncPostgresSaverAdapter(BaseCheckpointSaver):
    """在 Windows Proactor loop 中异步调用官方同步 PostgresSaver。

    psycopg 的异步连接不支持 Windows 默认 ProactorEventLoop，而全局改用
    SelectorEventLoop 又会影响工程中需要子进程的 MCP stdio。因此这里保留
    LangGraph 需要的异步 Saver 接口，只把阻塞的 PostgreSQL 操作交给
    ``asyncio.to_thread()`` 执行。

    这层在 Linux 上也能正常运行；只有将开发和部署统一迁移到 Linux
    原生异步 PostgreSQL 时，才需要整体替换为 AsyncPostgresSaver/Store。
    """

    def __init__(self, saver: PostgresSaver) -> None:
        """保留官方 Saver 的序列化器，并将真实数据库操作委托给它。"""

        # BaseCheckpointSaver 会通过 serde 序列化 Graph State。必须沿用已经
        # 配置 AES 的 saver.serde，否则适配器可能绕过 checkpoint 加密。
        super().__init__(serde=saver.serde)
        self._saver = saver

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """按 thread_id/checkpoint_id 异步读取一个完整 checkpoint 记录。"""

        return await asyncio.to_thread(self._saver.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """异步列出 checkpoint，并在后台线程内完成同步迭代。"""

        # PostgresSaver.list() 返回的是惰性同步迭代器，真正的 SQL 读取
        # 可能发生在迭代期间。因此要在 to_thread() 内转成 list，不能只把
        # 迭代器创建放到线程中，然后回到事件循环里执行阻塞迭代。
        items = await asyncio.to_thread(
            lambda: list(
                self._saver.list(
                    config,
                    filter=filter,
                    before=before,
                    limit=limit,
                )
            )
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """持久化节点完成后的 checkpoint，并返回新的 checkpoint 配置。"""

        # durability="sync" 时，LangGraph 会 await 此方法。to_thread 只是
        # 改变阻塞函数的执行线程，不会提前返回，因此写库完成前
        # LangGraph 仍不会进入下一个节点。
        return await asyncio.to_thread(
            self._saver.put,
            config,
            checkpoint,
            metadata,
            new_versions,
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """保存当前 LangGraph task 在 checkpoint 之间产生的中间写入。"""

        await asyncio.to_thread(
            self._saver.put_writes,
            config,
            writes,
            task_id,
            task_path,
        )

    async def adelete_thread(self, thread_id: str) -> None:
        """删除一个 LangGraph thread 的 checkpoint 和中间写入。"""

        await asyncio.to_thread(self._saver.delete_thread, thread_id)

    def get_next_version(self, current: Any, channel: Any) -> Any:
        """复用官方 Saver 的 channel version 计算规则。"""

        # 这是纯内存计算，不访问 PostgreSQL，所以不需要 to_thread()。
        return self._saver.get_next_version(current, channel)


class DocumentRuntimeReadSnapshot(BaseModel):
    """Store 中保存的文档读取证明；完整正文只进入加密 checkpoint。

    恢复时会重新读取 ``source_path`` 并比较 ``sha256``。如果文档在任务中断
    期间被修改，旧 checkpoint 中的推理就不再可信，必须废弃旧现场重新执行。
    """

    doc_id: str = Field(description="被 Deep Agent 授权读取的稳定文档 ID。")
    source_path: str = Field(description="读取时由服务端确认的知识库源路径。")
    sha256: str = Field(description="读取时完整文档正文的 SHA-256。")


class DeepDocumentRuntimeRecord(BaseModel):
    """Deep Agent 可恢复运行事实的版本化记录。

    这不是 LangGraph State 的副本，而是业务层在恢复前用来做安全判断的
    最小事实集。``record_version`` 保护的是这条 Store 记录，不是 LangGraph
    内部的 checkpoint version。
    """

    schema_version: int = Field(
        default=_RUNTIME_SCHEMA_VERSION,
        description="运行记录 JSON 结构版本。",
    )
    record_version: int = Field(
        default=1,
        ge=1,
        description="每次 Store 更新递增的乐观锁版本。",
    )
    task_plan_id: str = Field(description="关联的 Agent TaskPlan ID。")
    thread_id: str = Field(description="LangGraph checkpoint 使用的稳定 thread_id。")
    acl_fingerprint: str = Field(description="创建或恢复时当前用户 ACL 的规范化指纹。")
    candidates: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="由受控检索登记的文档候选事实摘要。",
    )
    read_snapshots: dict[str, DocumentRuntimeReadSnapshot] = Field(
        default_factory=dict,
        description="已读取文档的路径与正文哈希，不包含完整正文。",
    )
    used_tools: list[str] = Field(
        default_factory=list,
        description="服务端确认已成功完成的只读工具名称。",
    )
    resume_count: int = Field(default=0, ge=0, description="从 checkpoint 恢复的累计次数。")
    status: Literal["running", "failed", "cleanup_pending"] = Field(
        description="当前可恢复运行记录或待清理状态。"
    )
    expires_at: datetime = Field(description="失败或运行记录的最晚保留时间。")
    updated_at: datetime = Field(description="运行记录最近一次成功写入时间。")


def decode_langgraph_aes_key(value: str) -> bytes:
    """严格解码配置中的 Base64，并要求 AES-256 所需的 32 字节。

    Base64 只是密钥的配置编码，不是加密。先解码再检查字节数，可避免
    将“32 个 UTF-8 字符”误当成“32 字节 AES 密钥”。
    """

    try:
        raw_key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("LANGGRAPH_AES_KEY_BASE64 不是合法 Base64") from exc
    if len(raw_key) != 32:
        raise ValueError("LANGGRAPH_AES_KEY_BASE64 解码后必须恰好为 32 字节")
    return raw_key


def build_document_acl_fingerprint(
    user: CurrentUserContext,
    filters: RetrievalFilters,
) -> str:
    """把当前可信身份和检索边界规范化，供恢复前比较权限是否变化。

    返回值只用于精确判断“权限边界是否变化”，不代替恢复请求的实时鉴权。
    权限撤销后即使指纹数据仍存在，业务层也必须使用当前用户重新鉴权。
    """

    payload = {
        "user_id": user.user_id,
        "global_role_codes": sorted(set(user.global_role_codes)),
        "global_permission_codes": sorted(set(user.global_permission_codes)),
        "department_codes": sorted(set(user.department_codes)),
        "is_authenticated": user.is_authenticated,
        "can_read_all": filters.can_read_all,
        "filter_user_id": filters.user_id,
        "filter_departments": sorted(set(filters.department_codes)),
        "allow_public": filters.allow_public,
        "source_path": filters.source_path,
        "section_path": list(filters.section_path),
    }
    # 列表排序、JSON key 排序和固定分隔符共同保证：同一组权限即使
    # 原始集合顺序不同，也会产生相同指纹。
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(normalized.encode("utf-8")).hexdigest()


def _psycopg_connection_string(database_url: str) -> str:
    """把 SQLAlchemy 驱动 URL 转成 psycopg 可识别的 PostgreSQL URL。

    工程主数据库可使用 ``postgresql+asyncpg://``，但 psycopg ConnectionPool
    不识别 SQLAlchemy 的 ``+driver`` 部分，因此这里只替换 scheme，不改动
    用户名、密码、主机、端口和数据库名。
    """

    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix) :]
    if database_url.startswith(("postgresql://", "postgres://")):
        return database_url
    raise ValueError("LangGraph PostgreSQL 持久化要求 DATABASE_URL 使用 PostgreSQL")


class DeepDocumentRuntime:
    """复用一个连接池，为 Deep Agent 提供加密 Saver 和事实 Store。

    该对象在 FastAPI lifespan 启动时创建一次，通过 ``app.state`` 注入所有
    文档 Agent 请求，并在应用关闭时统一释放连接池。它不是每个请求
    都重新创建的临时对象。
    """

    def __init__(
        self,
        *,
        settings: Settings,
        pool: ConnectionPool,
        checkpointer: _AsyncPostgresSaverAdapter,
        store: PostgresStore,
    ) -> None:
        """保存 lifespan 已经创建好的连接池、Saver 和 Store。"""

        self.settings = settings
        self.pool = pool
        self.checkpointer = checkpointer
        self.store = store

    @classmethod
    async def start(cls, settings: Settings) -> "DeepDocumentRuntime":
        """创建共享连接池、初始化官方表结构并清理过期运行记录。

        该方法作为应用启动的失败边界：密钥无效、PostgreSQL 不可用或官方
        表结构初始化失败时，应用不应带着一个“无法恢复”的 Deep Agent 继续启动。
        """

        # JsonPlusSerializer 负责将 LangGraph State 转成字节，EncryptedSerializer
        # 在这些字节写入 PostgreSQL 前使用 AES-256 加密。禁用 pickle
        # fallback 避免从 checkpoint 恢复任意 pickle 对象。
        raw_key = decode_langgraph_aes_key(settings.langgraph_aes_key_base64)
        serializer = EncryptedSerializer.from_pycryptodome_aes(
            serde=JsonPlusSerializer(
                pickle_fallback=False,
                allowed_msgpack_modules=None,
            ),
            key=raw_key,
        )
        # Saver 和 Store 共享一个线程安全的官方连接池。open=False
        # 使连接动作保持在下方可统一清理的 try/except 边界内。
        pool = ConnectionPool(
            _psycopg_connection_string(settings.database_url),
            min_size=1,
            max_size=max(
                1,
                settings.database_pool_size + settings.database_max_overflow,
            ),
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=False,
        )
        try:
            # pool.open(wait=True) 会阻塞到最小连接就绪，因此也放到
            # 线程池；启动成功后才会向 FastAPI 暴露 runtime。
            await asyncio.to_thread(pool.open, wait=True)
            # Saver 保存加密的 Graph State；Store 保存不含完整正文的
            # DeepDocumentRuntimeRecord。两者虽共用 PostgreSQL，职责和表结构不同。
            saver = PostgresSaver(pool, serde=serializer)
            store = PostgresStore(pool)
            runtime = cls(
                settings=settings,
                pool=pool,
                checkpointer=_AsyncPostgresSaverAdapter(saver),
                store=store,
            )
            # setup() 执行 LangGraph 官方表结构迁移。两个 setup 都是同步
            # 数据库操作，所以不在事件循环线程里直接运行。
            await asyncio.to_thread(saver.setup)
            await asyncio.to_thread(store.setup)
            # 先清理上次进程遗留的过期数据，再开始接收新请求。
            await runtime.cleanup_expired()
            return runtime
        except BaseException:
            # BaseException 包含启动期 CancelledError。即使应用启动被取消，
            # 已打开的连接池也必须关闭，然后保留原始异常向上传播。
            await asyncio.to_thread(pool.close)
            raise

    async def close(self) -> None:
        """关闭 FastAPI lifespan 共享的 psycopg 连接池。"""

        # close() 可能等待已借出的连接归还，因此不直接阻塞事件循环。
        await asyncio.to_thread(self.pool.close)

    @staticmethod
    def thread_id(task_plan_id: str) -> str:
        """同一 TaskPlan 的所有恢复请求始终使用同一个 LangGraph thread。

        这个值必须由服务端稳定生成，不能信任请求传入的 thread_id；否则用户
        可能读取或覆盖其他任务的 checkpoint。
        """

        return f"document:{task_plan_id}"

    def retention_deadline(self) -> datetime:
        """计算失败或运行 checkpoint 的保留截止时间。"""

        return datetime.now(UTC) + timedelta(
            days=self.settings.agent_document_checkpoint_retention_days
        )

    async def create_record(
        self,
        *,
        task_plan_id: str,
        acl_fingerprint: str,
    ) -> DeepDocumentRuntimeRecord:
        """建立新运行记录；调用方必须先决定是否应释放旧 thread。

        这里不会隐式删除旧 checkpoint。旧 ACL 或源文件变化时是否重启任务，
        必须由拥有当前安全上下文的 DeepDocumentAgent 先做决策。
        """

        now = datetime.now(UTC)
        record = DeepDocumentRuntimeRecord(
            task_plan_id=task_plan_id,
            thread_id=self.thread_id(task_plan_id),
            acl_fingerprint=acl_fingerprint,
            status="running",
            expires_at=self.retention_deadline(),
            updated_at=now,
        )
        # Store 使用 namespace + task_plan_id 定位记录。index=False 表示这是
        # 精确 key 查询的运行事实，不需要语义向量索引。
        await asyncio.to_thread(
            self.store.put,
            _RUNTIME_NAMESPACE,
            task_plan_id,
            record.model_dump(mode="json"),
            False,
        )
        return record

    async def load_record(self, task_plan_id: str) -> DeepDocumentRuntimeRecord | None:
        """读取并验证运行记录；结构损坏统一转换为稳定业务错误。

        ``None`` 只表示 Store 中没有该任务。如果数据存在但无法验证，不能把它
        伪装成“没有记录”后静默重跑，因为这可能导致重复模型调用或越过原权限边界。
        """

        item = await asyncio.to_thread(
            self.store.get,
            _RUNTIME_NAMESPACE,
            task_plan_id,
        )
        if item is None:
            return None
        # model_validate 同时恢复 datetime 等强类型，并防止后续代码直接信任
        # Store 中可能损坏或来自旧版本的原始 JSON。
        try:
            record = DeepDocumentRuntimeRecord.model_validate(item.value)
        except Exception as exc:
            raise DocumentAgentCheckpointUnavailableError(
                "Deep Agent 运行记录损坏或版本不兼容"
            ) from exc
        if record.schema_version != _RUNTIME_SCHEMA_VERSION:
            raise DocumentAgentCheckpointUnavailableError(
                "Deep Agent 运行记录版本不受支持"
            )
        return record

    async def update_record(
        self,
        task_plan_id: str,
        *,
        expected_version: int,
        updates: dict[str, Any],
    ) -> DeepDocumentRuntimeRecord:
        """在单进程锁内执行读版本、更新和递增，为多 Worker CAS 预留契约。

        ``expected_version`` 是调用方上次读到的版本。如果当前 Store 版本已变，
        说明另一条执行路径已更新任务，本次不应覆盖它。

        注意：当前的“读取 + 比较 + put”不是 PostgreSQL 原子 CAS，安全性依赖
        AgentTaskExecutor 的单进程 task_plan_id 锁。未来多 Worker 部署时需改成
        数据库条件更新或租约。
        """

        current = await self.load_record(task_plan_id)
        if current is None:
            raise DocumentAgentCheckpointUnavailableError("Deep Agent 运行记录不存在")
        if current.record_version != expected_version:
            raise DocumentAgentCheckpointConflictError(
                "Deep Agent 运行记录已被其他恢复请求更新"
            )
        # 用完整模型重新验证合并结果，使 updates 也不能绕过字段类型、
        # status Literal 和 record_version 下限等契约。
        record = DeepDocumentRuntimeRecord.model_validate(
            {
                **current.model_dump(mode="python"),
                **updates,
                "record_version": current.record_version + 1,
                "updated_at": datetime.now(UTC),
                "expires_at": self.retention_deadline(),
            }
        )
        await asyncio.to_thread(
            self.store.put,
            _RUNTIME_NAMESPACE,
            task_plan_id,
            record.model_dump(mode="json"),
            False,
        )
        return record

    async def has_checkpoint(self, task_plan_id: str) -> bool:
        """检查稳定 thread 是否至少存在一个可恢复 checkpoint。

        Store 记录存在不代表 checkpoint 一定存在，因为进程可能在创建记录后、
        首个 checkpoint 落库前崩溃。恢复决策因此必须同时检查 Store 和 Saver。
        """

        config = {"configurable": {"thread_id": self.thread_id(task_plan_id)}}
        return await self.checkpointer.aget(config) is not None

    async def release(self, task_plan_id: str) -> None:
        """删除同一 TaskPlan 的 LangGraph thread 和可信运行事实。

        先删 Saver，再删 Store。如果 checkpoint 删除失败，Store 记录仍保留，
        上层可将它标记为 ``cleanup_pending`` 供下次启动重试；反过来先删
        Store 会产生无人管理的加密虚拟工作区。
        """

        await self.checkpointer.adelete_thread(self.thread_id(task_plan_id))
        await asyncio.to_thread(
            self.store.delete,
            _RUNTIME_NAMESPACE,
            task_plan_id,
        )

    async def cleanup_expired(self) -> int:
        """启动时释放超过保留期的运行记录和对应 checkpoint。

        返回实际选中并调用 ``release()`` 的任务数。清理放在 FastAPI 启动
        阶段，让上一次进程遗留的失败任务不会永久占用 PostgreSQL。
        """

        # Store.search() 默认只返回有限条目。先分页收集完整快照，
        # 再删除，可避免“边分页边删除”导致 offset 移动而跳过记录。
        items = []
        offset = 0
        while True:
            batch = await asyncio.to_thread(
                self.store.search,
                _RUNTIME_NAMESPACE,
                limit=100,
                offset=offset,
            )
            items.extend(batch)
            if len(batch) < 100:
                break
            offset += len(batch)
        now = datetime.now(UTC)
        expired_ids: list[str] = []
        for item in items:
            try:
                record = DeepDocumentRuntimeRecord.model_validate(item.value)
            except Exception:
                # 启动清理不猜测损坏数据属于哪个 thread，避免误删。
                # load_record() 在真正恢复该任务时会返回稳定的数据损坏错误。
                continue
            # cleanup_pending 表示之前的终态清理失败，无需等到 expires_at；
            # 其他 running/failed 记录只在保留期结束后删除，为 /retry 留出时间。
            if record.status == "cleanup_pending" or record.expires_at <= now:
                expired_ids.append(record.task_plan_id)
        for task_plan_id in expired_ids:
            await self.release(task_plan_id)
        return len(expired_ids)


__all__ = [
    "DeepDocumentRuntime",
    "DeepDocumentRuntimeRecord",
    "DocumentRuntimeReadSnapshot",
    "build_document_acl_fingerprint",
    "decode_langgraph_aes_key",
]
