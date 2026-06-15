import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from typing import Any

import httpx
from elasticsearch import AsyncElasticsearch
from pymilvus import MilvusClient

from fast_app.components.embeddings.base import BaseEmbeddingClient
from fast_app.components.embeddings.mock_embedding_client import MockEmbeddingClient
from fast_app.components.embeddings.qwen_embedding_client import QwenEmbeddingClient
from fast_app.components.llms.base import BaseLLMClient
from fast_app.components.llms.mock_llm_client import MockLLMClient
from fast_app.components.llms.qwen_langchain_llm_client import QwenLangChainLLMClient
from fast_app.components.rerankers.base import BaseReranker
from fast_app.components.rerankers.dashscope_reranker import DashScopeReranker
from fast_app.components.rerankers.mock_reranker import MockReranker
from fast_app.components.retrievers.elasticsearch_keyword_retriever import (
    ElasticsearchKeywordRetriever,
)
from fast_app.components.retrievers.milvus_vector_retriever import (
    MilvusVectorRetriever,
    build_milvus_uri,
)
from fast_app.core.config import Settings, get_settings
from fast_app.evaluation.cases.loader import load_eval_dataset
from fast_app.evaluation.thresholds.models import (
    EvalThresholdResult,
    EvalThresholds,
    check_offline_eval_thresholds,
)
from fast_app.evaluation.pipeline.runner import run_offline_rag_eval
from fast_app.evaluation.reports.serialization import to_jsonable
from fast_app.evaluation.reports.writer import write_offline_eval_report
from fast_app.services.langgraph_rag_pipeline_service import LangGraphRagPipeline
from fast_app.services.rag_pipeline_service import RagPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real offline RAG evaluation against local Milvus / ElasticSearch.",
    )
    parser.add_argument(
        "--dataset",
        default="src/fast_app/evaluation/datasets/stage11_rag_eval_cases.json",
        help="评测集 JSON 路径。",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/evaluation",
        help="评测报告输出目录。",
    )
    parser.add_argument(
        "--pipeline-provider",
        choices=["classic", "langgraph"],
        default="classic",
        help="选择 Classic Pipeline 或 LangGraph Pipeline。",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["qwen", "mock"],
        default="qwen",
        help="生成回答使用的 LLM。真实测试使用 qwen。",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=["mock", "qwen"],
        default="mock",
        help=(
            "查询 Milvus 使用的 embedding。必须和写入 Milvus 时一致；"
            "如果 ingestion 使用过 --mock-embeddings，这里保持 mock。"
        ),
    )
    parser.add_argument(
        "--reranker-provider",
        choices=["mock", "dashscope"],
        default="mock",
        help="rerank 提供者。默认 mock，避免评测时额外调用 rerank 服务。",
    )
    parser.add_argument(
        "--use-es-auth",
        action="store_true",
        help="默认不使用 ES basic_auth；只有本地 ES 开启认证时才需要传入。",
    )
    parser.add_argument(
        "--print-json-summary",
        action="store_true",
        help="额外在终端打印一份 JSON 摘要。",
    )
    parser.add_argument(
        "--min-retrieval-recall",
        type=float,
        default=0.0,
        help="最低 retrieval mean_recall_at_k，通过阈值检查使用。",
    )
    parser.add_argument(
        "--min-retrieval-mrr",
        type=float,
        default=0.0,
        help="最低 retrieval mean_mrr，通过阈值检查使用。",
    )
    parser.add_argument(
        "--min-generation-pass-rate",
        type=float,
        default=0.0,
        help="最低 generation pass_rate，通过阈值检查使用。",
    )
    parser.add_argument(
        "--fail-on-threshold",
        action="store_true",
        help="如果任一阈值检查失败，脚本返回退出码 1。",
    )

    return parser.parse_args()


def load_settings() -> Settings:
    # 某些 .env 中 DEBUG 可能不是 Pydantic bool 能解析的值。
    # 评测脚本不依赖 debug 语义，统一覆盖成 true。
    os.environ["DEBUG"] = "true"
    get_settings.cache_clear()
    return get_settings()


def build_embedding_client(
    settings: Settings,
    provider: str,
) -> BaseEmbeddingClient:
    if provider == "mock":
        return MockEmbeddingClient(dim=settings.embedding_dim)

    if provider == "qwen":
        return QwenEmbeddingClient(settings=settings)

    raise RuntimeError(f"不支持的 embedding provider: {provider}")


def build_llm_client(
    settings: Settings,
    provider: str,
) -> BaseLLMClient:
    if provider == "mock":
        return MockLLMClient()

    if provider == "qwen":
        return QwenLangChainLLMClient(settings=settings)

    raise RuntimeError(f"不支持的 LLM provider: {provider}")


def build_reranker(
    settings: Settings,
    provider: str,
    http_client: httpx.AsyncClient,
) -> BaseReranker:
    if provider == "mock":
        return MockReranker()

    if provider == "dashscope":
        return DashScopeReranker(
            settings=settings,
            http_client=http_client,
        )

    raise RuntimeError(f"不支持的 reranker provider: {provider}")


def validate_ascii_basic_auth(username: str, password: str) -> None:
    try:
        f"{username}:{password}".encode("ascii")
    except UnicodeEncodeError as exc:
        raise RuntimeError(
            "Elasticsearch basic_auth 只能使用 ASCII 字符。"
            "如果本地 ES 没有开启认证，请不要传 --use-es-auth；"
            "如果开启了认证，请把 .env 中的 ES 用户名和密码改成实际 ASCII 凭据。"
        ) from exc


def build_elasticsearch_client(
    settings: Settings,
    use_auth: bool,
) -> AsyncElasticsearch:
    kwargs: dict[str, Any] = {
        "hosts": [settings.elasticsearch_url],
        "request_timeout": settings.elasticsearch_request_timeout,
    }

    if use_auth:
        username = settings.elasticsearch_username.strip()
        password = settings.elasticsearch_password.strip()

        if not username or not password:
            raise RuntimeError(
                "已传入 --use-es-auth，但 ELASTICSEARCH_USERNAME 或 "
                "ELASTICSEARCH_PASSWORD 为空。"
            )

        validate_ascii_basic_auth(username=username, password=password)
        kwargs["basic_auth"] = (username, password)

    return AsyncElasticsearch(**kwargs)


def build_pipeline(
    settings: Settings,
    provider: str,
    vector_retriever: MilvusVectorRetriever,
    keyword_retriever: ElasticsearchKeywordRetriever,
    llm_client: BaseLLMClient,
    reranker: BaseReranker,
):
    if provider == "classic":
        return RagPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
        )

    if provider == "langgraph":
        return LangGraphRagPipeline(
            settings=settings,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
        )

    raise RuntimeError(f"不支持的 pipeline provider: {provider}")


def print_summary(report_paths, report) -> None:
    print("offline RAG eval finished")
    print(f"dataset: {report.dataset_name}")
    print(f"responses: {report.response_count}/{report.case_count}")
    print(
        "retrieval: "
        f"mean_recall_at_k={report.retrieval_report.mean_recall_at_k:.4f}, "
        f"mean_mrr={report.retrieval_report.mean_mrr:.4f}, "
        f"passed={report.retrieval_report.passed_case_count}/"
        f"{report.retrieval_report.evaluated_case_count}"
    )
    print(
        "generation: "
        f"pass_rate={report.generation_report.pass_rate:.4f}, "
        f"passed={report.generation_report.passed_case_count}/"
        f"{report.generation_report.evaluated_case_count}"
    )
    print(f"json_report: {report_paths.json_path}")
    print(f"markdown_report: {report_paths.markdown_path}")


def print_threshold_result(threshold_result: EvalThresholdResult) -> None:
    print("threshold checks:")
    for check in threshold_result.checks:
        status = "PASS" if check.passed else "FAIL"
        print(
            f"  {check.name}: {status} "
            f"actual={check.actual:.4f}, expected_min={check.expected_min:.4f}"
        )


async def main_async() -> int:
    args = parse_args()
    settings = load_settings()

    dataset = load_eval_dataset(args.dataset)
    milvus_client = MilvusClient(
        uri=build_milvus_uri(
            host=settings.milvus_host,
            port=settings.milvus_port,
        )
    )
    elasticsearch_client = build_elasticsearch_client(
        settings=settings,
        use_auth=args.use_es_auth,
    )
    rerank_http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.rerank_timeout_seconds),
    )

    try:
        embedding_client = build_embedding_client(
            settings=settings,
            provider=args.embedding_provider,
        )
        vector_retriever = MilvusVectorRetriever(
            settings=settings,
            embedding_client=embedding_client,
            client=milvus_client,
        )
        keyword_retriever = ElasticsearchKeywordRetriever(
            settings=settings,
            client=elasticsearch_client,
        )
        llm_client = build_llm_client(
            settings=settings,
            provider=args.llm_provider,
        )
        reranker = build_reranker(
            settings=settings,
            provider=args.reranker_provider,
            http_client=rerank_http_client,
        )
        pipeline = build_pipeline(
            settings=settings,
            provider=args.pipeline_provider,
            vector_retriever=vector_retriever,
            keyword_retriever=keyword_retriever,
            llm_client=llm_client,
            reranker=reranker,
        )

        report = await run_offline_rag_eval(
            dataset=dataset,
            pipeline=pipeline,
        )
        report_paths = write_offline_eval_report(
            report=report,
            output_dir=args.output_dir,
        )

        print_summary(report_paths=report_paths, report=report)

        threshold_result = check_offline_eval_thresholds(
            report=report,
            thresholds=EvalThresholds(
                min_retrieval_recall_at_k=args.min_retrieval_recall,
                min_retrieval_mrr=args.min_retrieval_mrr,
                min_generation_pass_rate=args.min_generation_pass_rate,
            ),
        )
        print_threshold_result(threshold_result)

        if args.print_json_summary:
            summary = {
                "dataset": report.dataset_name,
                "response_count": report.response_count,
                "retrieval": {
                    "mean_recall_at_k": report.retrieval_report.mean_recall_at_k,
                    "mean_mrr": report.retrieval_report.mean_mrr,
                    "passed_case_count": report.retrieval_report.passed_case_count,
                    "evaluated_case_count": report.retrieval_report.evaluated_case_count,
                },
                "generation": {
                    "pass_rate": report.generation_report.pass_rate,
                    "passed_case_count": report.generation_report.passed_case_count,
                    "evaluated_case_count": report.generation_report.evaluated_case_count,
                },
                "paths": asdict(report_paths),
                "thresholds": asdict(threshold_result),
            }
            print(json.dumps(to_jsonable(summary), ensure_ascii=False, indent=2))

        if args.fail_on_threshold and not threshold_result.passed:
            return 1

        return 0

    finally:
        milvus_client.close()
        await elasticsearch_client.close()
        await rerank_http_client.aclose()


def main() -> int:
    try:
        return asyncio.run(main_async())
    except Exception as exc:
        print(f"真实离线 RAG 评测失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

