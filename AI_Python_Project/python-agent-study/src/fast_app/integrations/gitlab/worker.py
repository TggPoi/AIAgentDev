from __future__ import annotations

import argparse
import asyncio
import os
import socket
from contextlib import suppress

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fast_app.core.config import Settings, get_secret_env_value, get_settings
from fast_app.core.logging import format_log_fields, get_logger, setup_logging
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.ingestion.stores.store_mutation_lock import StoreMutationLock
from fast_app.ingestion.cli import (
    apply_arg_overrides,
    build_elasticsearch_client,
    build_embedding_client,
    build_milvus_client,
)
from fast_app.integrations.gitlab.client import GitLabClient
from fast_app.integrations.gitlab.repository import GitLabRepository
from fast_app.integrations.gitlab.sync_service import GitDocumentSyncService


logger = get_logger(__name__)


class GitLabSyncWorker:
    """在 FastAPI 进程之外领取并执行 GitLab 文档同步任务。"""

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        service: GitDocumentSyncService,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.service = service
        self.worker_id = worker_id

    async def run_once(self) -> bool:
        # 领取任务使用短事务并立即释放连接；耗时的下载和 Embedding 不占着领取锁。
        async with self.session_factory() as session:
            job = await GitLabRepository(session).claim_next(
                worker_id=self.worker_id,
                lease_seconds=self.settings.gitlab_worker_lease_seconds,
            )
        if job is None:
            return False

        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        try:
            async with self.session_factory() as session:
                repository = GitLabRepository(session)
                source = await repository.get_source(job.source_id)
                if source is None or source.status != "active":
                    raise RuntimeError("GitLab Source 不存在或已停用")
                if job.mode == "bootstrap":
                    sources = [
                        item
                        for item in await repository.list_sources()
                        if item.status == "active"
                    ]
                    clients = {
                        item.id: self._client(item)
                        for item in sources
                    }
                    try:
                        target_shas = {
                            item.id: await clients[item.id].get_branch_head(
                                item.project_id,
                                item.target_branch,
                            )
                            for item in sources
                        }
                        version = await self.service.bootstrap_all(
                            job=job,
                            sources=sources,
                            clients=clients,
                            target_shas=target_shas,
                            repository=repository,
                            worker_id=self.worker_id,
                        )
                    finally:
                        await asyncio.gather(
                            *(client.close() for client in clients.values())
                        )
                else:
                    client = self._client(source)
                    try:
                        # 同步 main 前顺便把本地 opened MR 状态与 GitLab 对齐。
                        await self._reconcile_change_requests(
                            repository=repository,
                            source=source,
                            client=client,
                        )
                        version = await self.service.run(
                            job=job,
                            source=source,
                            repository=repository,
                            client=client,
                            worker_id=self.worker_id,
                        )
                    finally:
                        await client.close()

                for item in await repository.list_sources():
                    await session.refresh(item)
                    if (
                        item.desired_sha
                        and item.last_synced_sha
                        and item.desired_sha != item.last_synced_sha
                    ):
                        # 当前任务处理的是领取时冻结的 target_sha。运行期间若又有提交，
                        # desired_sha 会更靠前，这里立即补一个追赶任务而不漏掉新版本。
                        await repository.enqueue(
                            source_id=item.id,
                            mode="incremental",
                            base_sha=item.last_synced_sha,
                            target_sha=item.desired_sha,
                        )
                logger.info(
                    "GitLab 同步任务发布完成%s",
                    format_log_fields(job_id=job.id, version=version),
                )
        except Exception as exc:
            logger.exception(
                "GitLab 同步任务失败%s",
                format_log_fields(job_id=job.id, error=str(exc)),
            )
            async with self.session_factory() as session:
                await GitLabRepository(session).mark_job_failed(
                    job_id=job.id,
                    worker_id=self.worker_id,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    retryable=_is_retryable_sync_error(exc),
                )
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
        return True

    async def enqueue_reconcile_jobs(self) -> None:
        async with self.session_factory() as session:
            sources = [
                source
                for source in await GitLabRepository(session).list_sources()
                if source.status == "active"
            ]
        for source in sources:
            client = self._client(source)
            try:
                target_sha = await client.get_branch_head(
                    source.project_id,
                    source.target_branch,
                )
                async with self.session_factory() as session:
                    await GitLabRepository(session).enqueue(
                        source_id=source.id,
                        mode="reconcile",
                        base_sha=source.last_synced_sha,
                        target_sha=target_sha,
                    )
            except Exception:
                logger.exception(
                    "GitLab 周期性对账任务创建失败%s",
                    format_log_fields(source_id=source.id),
                )
            finally:
                await client.close()

    def _client(self, source) -> GitLabClient:
        # Worker 只使用 rag-sync 的只读 Token，不具备创建分支或提交文件的权限。
        return GitLabClient(
            base_url=source.base_url,
            token=get_secret_env_value(source.sync_token_env),
            timeout_seconds=self.settings.gitlab_request_timeout_seconds,
            max_retries=self.settings.gitlab_max_retries,
        )

    @staticmethod
    async def _reconcile_change_requests(
        *,
        repository: GitLabRepository,
        source,
        client: GitLabClient,
    ) -> None:
        for row in await repository.list_change_requests(
            source_id=source.id,
            status="opened",
        ):
            merge_request = await client.find_merge_request(
                source.project_id,
                source_branch=row.branch_name,
            )
            if merge_request is not None and merge_request.state != row.status:
                row.status = merge_request.state
                await repository.save_change_request(row)

    async def _heartbeat(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(self.settings.gitlab_worker_heartbeat_seconds)
            async with self.session_factory() as session:
                owned = await GitLabRepository(session).heartbeat(
                    job_id=job_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.settings.gitlab_worker_lease_seconds,
                )
            if not owned:
                return


def _is_retryable_sync_error(exc: Exception) -> bool:
    """确定性内容、路径和 ACL 校验错误不应自动重放。"""

    return not isinstance(exc, ValueError)


async def run_worker(*, once: bool, use_mock_embeddings: bool) -> int:
    settings = get_settings()
    setup_logging(settings)
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    elasticsearch_client = build_elasticsearch_client(settings)
    milvus_client = build_milvus_client(settings)
    worker = GitLabSyncWorker(
        settings=settings,
        session_factory=session_factory,
        service=GitDocumentSyncService(
            settings=settings,
            embedding_client=build_embedding_client(settings, use_mock_embeddings),
            elasticsearch_client=elasticsearch_client,
            milvus_client=milvus_client,
            store_mutation_lock=StoreMutationLock(engine),
        ),
        worker_id=f"{socket.gethostname()}:{os.getpid()}",
    )
    try:
        if once:
            await worker.run_once()
            return 0
        loop = asyncio.get_running_loop()
        next_reconcile = (
            loop.time() + settings.gitlab_reconcile_interval_seconds
        )
        while True:
            worked = await worker.run_once()
            if loop.time() >= next_reconcile:
                await worker.enqueue_reconcile_jobs()
                next_reconcile = (
                    loop.time() + settings.gitlab_reconcile_interval_seconds
                )
            if not worked:
                # 队列为空时才休眠；Worker 是独立常驻进程，不由 FastAPI 请求临时启动。
                await asyncio.sleep(settings.gitlab_worker_poll_seconds)
    finally:
        await elasticsearch_client.close()
        await milvus_client.close()
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="处理 GitLab 企业文档同步任务")
    parser.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    parser.add_argument(
        "--mock-embeddings",
        action="store_true",
        help="本地集成测试使用固定维度 Mock Embedding",
    )
    parser.add_argument(
        "--no-es-auth",
        action="store_true",
        help="本地 Elasticsearch 未启用认证时忽略认证配置",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    apply_arg_overrides(args)
    return asyncio.run(
        run_worker(once=args.once, use_mock_embeddings=args.mock_embeddings)
    )


if __name__ == "__main__":
    raise SystemExit(main())
