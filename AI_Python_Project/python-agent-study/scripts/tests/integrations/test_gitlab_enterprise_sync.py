from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import io
import os
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx

from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    build_es_filters,
)
from fast_app.components.retrievers.milvus_vector_retriever import (
    build_milvus_filter_expr,
)
from fast_app.core.config import get_secret_env_value, get_settings
from fast_app.db.session import create_database_engine, create_session_factory
from fast_app.domain.rag_models import RetrievalFilters, RetrievedDoc
from fast_app.domain.knowledge_document_actions import (
    KnowledgeDocumentActionPreview,
    KnowledgeDocumentActionRequest,
    KnowledgeDocumentOperation,
    KnowledgeDocumentRiskLevel,
)
from fast_app.domain.user_context import CurrentUserContext
from fast_app.db.gitlab_tables import GitLabSourceTable
from fast_app.ingestion.processing.markdown_hierarchy import (
    MarkdownHierarchyBuilder,
    MarkdownHierarchyOptions,
)
from fast_app.ingestion.stores.rag_store_writer import (
    build_es_bulk_actions,
    build_milvus_rows,
)
from fast_app.ingestion.cli import build_milvus_client
from fast_app.integrations.gitlab.client import GitLabClient
from fast_app.integrations.gitlab.agent_change_service import (
    GitLabAgentChangeService,
)
from fast_app.integrations.gitlab.models import (
    GitLabCommitResult,
    GitLabMergeRequestResult,
)
from fast_app.integrations.gitlab.project_source import GitLabProjectSource
from fast_app.integrations.gitlab.repository import GitLabRepository
from fast_app.integrations.gitlab.sync_service import (
    safe_extract_archive,
    version_artifacts,
)
from fast_app.integrations.gitlab.worker import (
    GitLabSyncWorker,
    _is_retryable_sync_error,
)
from fast_app.services.rag.rag_pipeline_service import docs_to_sources


async def test_client() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        page = request.url.params.get("page")
        return httpx.Response(
            200,
            headers={"X-Next-Page": "2" if page == "1" else ""},
            json={
                "commit": {"id": "b" * 40},
                "diffs": [
                    {
                        "old_path": f"docs/{page}.md",
                        "new_path": f"docs/{page}.md",
                    }
                ],
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = GitLabClient(
        base_url="http://gitlab.local/",
        token="test-token",
        max_retries=2,
        http_client=http_client,
    )
    try:
        result = await client.compare(12, "a" * 40, "b" * 40)
    finally:
        await http_client.aclose()
    assert [diff.new_path for diff in result.diffs] == [
        "docs/1.md",
        "docs/2.md",
    ]
    assert requests[-1].headers["PRIVATE-TOKEN"] == "test-token"
    assert requests[-1].url.params["straight"] == "true"
    assert requests[-1].url.params["per_page"] == "100"


def test_identity_version_and_filters() -> None:
    source = GitLabProjectSource(
        host_id="gitlab.local",
        project_id=12,
        source_id="art",
        department_code="art",
        default_visibility="department",
    )
    assert source.document_type("docs/manual.docx") == "word"
    assert source.document_type("docs/manual.pdf") == "pdf"
    assert source.doc_id("docs/a.md") == source.doc_id("docs/a.md")
    assert source.doc_id("docs/a.md") != source.doc_id("docs/b.md")
    document = source.build_text_document(
        repository_path="docs/a.md",
        content="# 标题\n\n" + ("正文内容。" * 100),
        source_revision="a" * 40,
    )
    hierarchy = MarkdownHierarchyBuilder().build(
        [document],
        MarkdownHierarchyOptions(
            source="gitlab",
            parent_target_tokens=100,
            parent_max_tokens=180,
            parent_max_chars=2000,
            child_target_tokens=30,
            child_max_tokens=60,
            child_min_tokens=5,
            child_overlap_tokens=5,
        ),
    )
    parents, children = version_artifacts(
        hierarchy.parents,
        hierarchy.children,
        3,
    )
    parent_ids = {parent.id for parent in parents}
    assert parent_ids
    assert all(len(parent.id) == 64 for parent in parents)
    assert all(len(child.id) == 64 for child in children)
    assert parents[0].id == hashlib.sha256(
        f"{parents[0].metadata['logical_record_id']}3".encode("utf-8")
    ).hexdigest()
    assert all(child.metadata["physical_parent_id"] in parent_ids for child in children)
    assert all(child.metadata["valid_from_version"] == 3 for child in children)
    child = children[0]
    es_source = build_es_bulk_actions("knowledge", [child])[0]["_source"]
    assert es_source["physical_record_id"] == child.id
    assert es_source["doc_id"] == child.metadata["doc_id"]
    assert es_source["record_type"] == "markdown_child"
    assert es_source["physical_parent_id"] == child.metadata["physical_parent_id"]
    milvus_row = build_milvus_rows(
        SimpleNamespace(
            milvus_id_field="id",
            milvus_vector_field="embedding",
            milvus_content_field="content",
        ),
        [child],
        [[0.1]],
    )[0]
    assert milvus_row["physical_record_id"] == child.id
    assert milvus_row["doc_id"] == child.metadata["doc_id"]
    assert milvus_row["record_type"] == "markdown_child"
    assert milvus_row["physical_parent_id"] == child.metadata["physical_parent_id"]

    filters = RetrievalFilters(
        can_read_all=True,
        knowledge_version=3,
    )
    assert {"range": {"valid_from_version": {"lte": 3}}} in build_es_filters(
        filters
    )
    milvus_filter = build_milvus_filter_expr(filters) or ""
    assert "valid_from_version <= 3" in milvus_filter
    assert "valid_to_version > 3" in milvus_filter

    source_item = docs_to_sources(
        [
            RetrievedDoc(
                id=child.id,
                content=child.content,
                score=1.0,
                source=child.source,
                title=child.title,
                metadata=child.metadata,
            )
        ]
    )[0]
    assert source_item.id == child.metadata["logical_record_id"]
    assert source_item.parent_id == child.metadata["logical_parent_id"]
    assert "physical_record_id" not in source_item.metadata
    assert "physical_parent_id" not in source_item.metadata


def test_archive_traversal() -> None:
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        content = b"blocked"
        member = tarfile.TarInfo("../outside.md")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            safe_extract_archive(
                payload.getvalue(),
                Path(temp_dir),
                max_files=10,
                max_bytes=1024,
                max_file_bytes=1024,
            )
        except ValueError as exc:
            assert "路径穿越" in str(exc)
        else:
            raise AssertionError("路径穿越 Archive 未被拒绝")


def test_secret_env_fallback() -> None:
    name = "GITLAB_TEST_SECRET"
    previous = os.environ.pop(name, None)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(f"{name}=from-dotenv\n", encoding="utf-8")
            assert get_secret_env_value(name, str(env_file)) == "from-dotenv"
            os.environ[name] = "from-process"
            assert get_secret_env_value(name, str(env_file)) == "from-process"
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


async def test_live_store_contract() -> None:
    settings = get_settings()
    required = {
        "physical_record_id",
        "logical_record_id",
        "doc_id",
        "record_type",
        "source_id",
        "source_revision",
        "valid_from_version",
        "valid_to_version",
    }
    response = httpx.post(
        (
            f"{settings.elasticsearch_url.rstrip('/')}/"
            f"{settings.elasticsearch_index_name}/_search"
        ),
        json={
            "size": 1,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"valid_from_version": {"lte": 1}}},
                        {
                            "bool": {
                                "should": [
                                    {"term": {"valid_to_version": 0}},
                                    {"range": {"valid_to_version": {"gt": 1}}},
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    ]
                }
            },
            "aggs": {"types": {"terms": {"field": "record_type", "size": 10}}},
        },
        timeout=30,
    )
    response.raise_for_status()
    es_result = response.json()
    es_source = es_result["hits"]["hits"][0]["_source"]
    assert required <= es_source.keys()
    assert es_source["physical_record_id"] == hashlib.sha256(
        (
            f"{es_source['logical_record_id']}"
            f"{es_source['valid_from_version']}"
        ).encode("utf-8")
    ).hexdigest()

    client = build_milvus_client(settings)
    try:
        description = await client.describe_collection(
            settings.milvus_collection_name
        )
        fields = {
            item["name"]
            for item in description["fields"]
        }
        required_milvus = required | {
            "logical_parent_id",
            "physical_parent_id",
        }
        assert required_milvus <= fields
        rows = await client.query(
            collection_name=settings.milvus_collection_name,
            filter=(
                "valid_from_version <= 1 and "
                "(valid_to_version == 0 or valid_to_version > 1)"
            ),
            output_fields=list(required_milvus),
            limit=1000,
        )
    finally:
        await client.close()

    counts = Counter(row["record_type"] for row in rows)
    assert len(rows) == 260
    assert "markdown_parent" not in counts
    assert all(
        row["physical_record_id"]
        and row["logical_record_id"]
        and row["doc_id"]
        for row in rows
    )
    assert all(
        row["physical_record_id"]
        == hashlib.sha256(
            f"{row['logical_record_id']}{row['valid_from_version']}".encode(
                "utf-8"
            )
        ).hexdigest()
        for row in rows
    )
    assert all(
        row["logical_parent_id"] and row["physical_parent_id"]
        for row in rows
        if row["record_type"] == "markdown_child"
    )
    print(
        {
            "es_total": es_result["hits"]["total"]["value"],
            "es_types": {
                bucket["key"]: bucket["doc_count"]
                for bucket in es_result["aggregations"]["types"]["buckets"]
            },
            "milvus_total": len(rows),
            "milvus_types": dict(counts),
            "top_level_fields": "passed",
        }
    )


async def test_live_worker_claims() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            sources = [
                source
                for source in await GitLabRepository(session).list_sources()
                if source.status == "active" and source.last_synced_sha
            ][:2]
        assert len(sources) == 2
        for source in sources:
            async with session_factory() as session:
                await GitLabRepository(session).enqueue(
                    source_id=source.id,
                    mode="incremental",
                    base_sha=source.last_synced_sha,
                    target_sha=source.last_synced_sha,
                )

        async def claim(worker_id: str):
            async with session_factory() as session:
                return await GitLabRepository(session).claim_next(
                    worker_id=worker_id,
                    lease_seconds=60,
                )

        claimed = await asyncio.gather(claim("live-worker-1"), claim("live-worker-2"))
        assert all(claimed)
        assert len({job.id for job in claimed if job is not None}) == 2
        for job in claimed:
            assert job is not None
            async with session_factory() as session:
                await GitLabRepository(session).complete_noop(
                    job_id=job.id,
                    source_id=job.source_id,
                    worker_id=str(job.worker_id),
                    target_sha=job.target_sha,
                )
    finally:
        await engine.dispose()


async def test_agent_uses_branch_and_idempotent_mr() -> None:
    source = GitLabSourceTable(
        id="art",
        base_url="http://gitlab.local",
        host_id="gitlab.local",
        project_id=12,
        project_path="company/art",
        target_branch="main",
        department_code="art",
        default_visibility="department",
        sync_token_env="SYNC",
        agent_token_env="AGENT",
        webhook_secret_env="WEBHOOK",
        status="active",
    )

    class Repository:
        change_request = None

        async def get_change_request(self, task_plan_id, source_id):
            return self.change_request

        async def save_change_request(self, row):
            self.change_request = row
            return row

        async def get_document(self, doc_id):
            return None

        async def find_document_by_path(self, repository_path):
            return None

        async def find_source_by_department(self, department_code):
            return source

    class Client:
        branch_creations = 0
        commits = 0
        merge_requests = 0
        branch_head = None

        async def get_branch_head(self, project_id, branch):
            assert branch == "main"
            return "a" * 40

        async def get_branch_head_optional(self, project_id, branch):
            assert branch.startswith("agent/")
            return self.branch_head

        async def create_branch(self, project_id, *, branch, ref):
            assert branch.startswith("agent/") and branch != "main"
            self.branch_creations += 1
            self.branch_head = ref
            return {}

        async def get_file_optional(self, project_id, path, ref):
            return None

        async def create_commit(self, project_id, *, branch, commit_message, actions):
            assert (
                branch.startswith("agent/")
                and actions[0]["action"] == "create"
                and actions[0]["file_path"] == "art/new.md"
            )
            self.commits += 1
            self.branch_head = "b" * 40
            return GitLabCommitResult(id=self.branch_head)

        async def find_merge_request(self, project_id, *, source_branch):
            return None

        async def create_merge_request(
            self,
            project_id,
            *,
            source_branch,
            target_branch,
            title,
            description,
        ):
            assert source_branch.startswith("agent/") and target_branch == "main"
            self.merge_requests += 1
            return GitLabMergeRequestResult(
                iid=7,
                web_url="http://gitlab.local/company/art/-/merge_requests/7",
                state="opened",
            )

        async def close(self):
            return None

    repository = Repository()
    client = Client()
    service = GitLabAgentChangeService(
        settings=SimpleNamespace(
            gitlab_request_timeout_seconds=1,
            gitlab_max_retries=0,
        ),
        repository=repository,
    )
    service._client = lambda _: client  # type: ignore[method-assign]
    request = KnowledgeDocumentActionRequest(
        operation=KnowledgeDocumentOperation.CREATE,
        target_path="art/new.md",
        content="# New",
        reason="test",
        expected_department_codes=["art"],
    )
    preview = KnowledgeDocumentActionPreview(
        operation=request.operation,
        target_path=request.target_path,
        normalized_path=request.target_path,
        exists_before=False,
        risk_level=KnowledgeDocumentRiskLevel.HIGH,
        affected_doc_id="d" * 64,
        before_hash=None,
        after_hash="e" * 64,
        permission_metadata={
            "visibility": "department",
            "allowed_departments": ["art"],
            "allowed_users": [],
        },
    )
    user = CurrentUserContext(
        user_id="user-1",
        is_authenticated=True,
        auth_source="jwt",
        primary_department_code="art",
        department_codes=["art"],
    )
    first = await service.submit_changes(
        task_plan_id="plan-1",
        actions=[(request, preview, None)],
        user=user,
    )
    second = await service.submit_changes(
        task_plan_id="plan-1",
        actions=[(request, preview, None)],
        user=user,
    )
    assert first == second
    assert client.branch_creations == client.commits == client.merge_requests == 1


async def test_worker_reconciles_merged_change_request() -> None:
    row = SimpleNamespace(branch_name="agent/plan-1", status="opened")

    class Repository:
        saved = 0

        async def list_change_requests(self, *, source_id, status):
            assert source_id == "art" and status == "opened"
            return [row]

        async def save_change_request(self, change_request):
            assert change_request is row
            self.saved += 1
            return change_request

    class Client:
        async def find_merge_request(self, project_id, *, source_branch):
            assert project_id == 12 and source_branch == row.branch_name
            return GitLabMergeRequestResult(
                iid=7,
                web_url="http://gitlab.local/company/art/-/merge_requests/7",
                state="merged",
            )

    repository = Repository()
    await GitLabSyncWorker._reconcile_change_requests(
        repository=repository,
        source=SimpleNamespace(id="art", project_id=12),
        client=Client(),
    )
    assert row.status == "merged" and repository.saved == 1


async def test_non_retryable_sync_failure_is_terminal() -> None:
    job = SimpleNamespace(
        attempt_count=1,
        max_attempts=3,
        status="running",
        phase="claiming",
        error_code=None,
        error_message=None,
        worker_id="worker-1",
        lease_expires_at=object(),
        finished_at=None,
        candidate_version=None,
    )

    class Session:
        committed = False

        async def scalar(self, _stmt):
            return job

        async def rollback(self):
            raise AssertionError("existing job must not roll back")

        async def commit(self):
            self.committed = True

    session = Session()
    await GitLabRepository(session).mark_job_failed(  # type: ignore[arg-type]
        job_id="job-1",
        worker_id="worker-1",
        error_code="ValueError",
        error_message="ACL invalid",
        retryable=False,
    )
    assert job.status == "failed"
    assert job.finished_at is not None
    assert session.committed
    assert not _is_retryable_sync_error(ValueError("ACL invalid"))
    assert _is_retryable_sync_error(RuntimeError("temporary failure"))


async def main() -> None:
    await test_client()
    await test_agent_uses_branch_and_idempotent_mr()
    await test_worker_reconciles_merged_change_request()
    await test_non_retryable_sync_failure_is_terminal()
    test_identity_version_and_filters()
    test_archive_traversal()
    test_secret_env_fallback()
    if os.environ.get("RUN_GITLAB_LIVE_STORE_TEST") == "1":
        await test_live_store_contract()
    if os.environ.get("RUN_GITLAB_LIVE_QUEUE_TEST") == "1":
        await test_live_worker_claims()
    print("gitlab_enterprise_sync=passed")


if __name__ == "__main__":
    asyncio.run(main())
