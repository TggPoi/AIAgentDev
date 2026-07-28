from __future__ import annotations

import argparse
import asyncio
import json
from urllib.parse import urlsplit

from fast_app.core.config import get_secret_env_value, get_settings
from fast_app.db.gitlab_tables import GitLabSourceTable
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.integrations.gitlab.client import GitLabClient
from fast_app.integrations.gitlab.repository import GitLabRepository


async def register_source(args: argparse.Namespace) -> int:
    settings = get_settings()
    token = get_secret_env_value(args.sync_token_env)
    client = GitLabClient(
        base_url=args.base_url,
        token=token,
        timeout_seconds=settings.gitlab_request_timeout_seconds,
        max_retries=settings.gitlab_max_retries,
    )
    try:
        project = await client.get_project(args.project_id)
        await client.get_branch_head(args.project_id, args.target_branch)
    finally:
        await client.close()

    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            repository = GitLabRepository(session)
            source = await repository.get_source(args.source_id)
            values = {
                "base_url": args.base_url.rstrip("/"),
                "host_id": args.host_id or _host_id(args.base_url),
                "project_id": project.id,
                "project_path": project.path_with_namespace,
                "target_branch": args.target_branch,
                "department_code": args.department_code,
                "default_visibility": args.default_visibility,
                "sync_token_env": args.sync_token_env,
                "agent_token_env": args.agent_token_env,
                "webhook_secret_env": args.webhook_secret_env,
                "status": "active",
            }
            if source is None:
                source = GitLabSourceTable(id=args.source_id, **values)
            else:
                for key, value in values.items():
                    setattr(source, key, value)
            await repository.save_source(source)
            print(
                json.dumps(
                    {
                        "source_id": source.id,
                        "project_id": source.project_id,
                        "project_path": source.project_path,
                        "target_branch": source.target_branch,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await engine.dispose()
    return 0


async def enqueue_bootstrap() -> int:
    settings = get_settings()
    engine = create_database_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            repository = GitLabRepository(session)
            if await repository.get_active_version() != 0:
                raise RuntimeError("联合 Bootstrap 只允许在正式知识版本为 0 时执行")
            sources = [
                source
                for source in await repository.list_sources()
                if source.status == "active"
            ]
            if not sources:
                raise RuntimeError("没有已启用的 GitLab Source")
            leader = sources[0]
            client = GitLabClient(
                base_url=leader.base_url,
                token=get_secret_env_value(leader.sync_token_env),
                timeout_seconds=settings.gitlab_request_timeout_seconds,
                max_retries=settings.gitlab_max_retries,
            )
            try:
                target_sha = await client.get_branch_head(
                    leader.project_id,
                    leader.target_branch,
                )
            finally:
                await client.close()
            job = await repository.enqueue(
                source_id=leader.id,
                mode="bootstrap",
                base_sha=None,
                target_sha=target_sha,
            )
            print(
                json.dumps(
                    {
                        "job_id": job.id,
                        "mode": job.mode,
                        "source_count": len(sources),
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        await engine.dispose()
    return 0


def _host_id(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("GitLab base_url 必须是 http/https URL")
    return parsed.netloc.lower().replace(":", "-")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="登记 GitLab Source 或创建联合 Bootstrap")
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register", help="验证并登记一个 GitLab Project")
    register.add_argument("--source-id", required=True)
    register.add_argument("--base-url", required=True)
    register.add_argument("--host-id")
    register.add_argument("--project-id", required=True, type=int)
    register.add_argument("--department-code", required=True)
    register.add_argument(
        "--default-visibility",
        choices=["public", "department"],
        default="department",
    )
    register.add_argument("--target-branch", default="main")
    register.add_argument("--sync-token-env", required=True)
    register.add_argument("--agent-token-env", required=True)
    register.add_argument("--webhook-secret-env", required=True)
    commands.add_parser("bootstrap", help="为全部已启用 Source 创建联合 Bootstrap 任务")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "register":
        return asyncio.run(register_source(args))
    return asyncio.run(enqueue_bootstrap())


if __name__ == "__main__":
    raise SystemExit(main())
