from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.services.agent_tasks.agent_task_router import AgentTaskRouter


@dataclass(frozen=True)
class RouteCase:
    query: str
    expected: frozenset[str]


CASES = [
    RouteCase("FastAPI 是什么？", frozenset({"simple_rag"})),
    RouteCase("PostgreSQL 在后端系统中承担什么作用？", frozenset({"simple_rag"})),
    RouteCase("RAG 中 rerank 的主要作用是什么？", frozenset({"simple_rag"})),
    RouteCase("请对比混合检索与 rerank 的差异和协作关系。", frozenset({"question_decomposition"})),
    RouteCase("分析权限过滤、Prompt Guard 和检索质量之间的关系。", frozenset({"question_decomposition"})),
    RouteCase("比较 Milvus 与 Elasticsearch 在混合检索中的职责。", frozenset({"question_decomposition"})),
    RouteCase("请创建知识库文档 docs/development/router-create.md。", frozenset({"knowledge_document_management"})),
    RouteCase("请修改 development/rag-backend-deployment.md 文档中的健康检查。", frozenset({"knowledge_document_management"})),
    RouteCase("请删除知识库中的旧部署文档。", frozenset({"knowledge_document_management"})),
    RouteCase("生成部署报告并保存为知识库文档 deployment-report.md。", frozenset({"knowledge_document_management"})),
    RouteCase(
        "删除刚才找到的知识库旧部署文档",
        frozenset({"knowledge_document_management", "clarification_required"}),
    ),
    RouteCase(
        "修改刚才找到的权限设计文档内容",
        frozenset({"knowledge_document_management", "clarification_required"}),
    ),
    RouteCase("请联网搜索 FastAPI 最新部署建议。", frozenset({"web_research"})),
    RouteCase("使用 web_search 查询 PostgreSQL 版本发布信息。", frozenset({"web_research"})),
    RouteCase("读取 https://fastapi.tiangolo.com/deployment/ 并总结。", frozenset({"web_research"})),
    RouteCase("请网络搜索 Milvus 官方健康检查说明。", frozenset({"web_research"})),
    RouteCase("删除 Redis 测试缓存。", frozenset({"simple_rag", "clarification_required"})),
    RouteCase("移除本地 Docker 的临时容器。", frozenset({"simple_rag", "clarification_required"})),
    RouteCase("帮我处理一下。", frozenset({"clarification_required"})),
    RouteCase("继续。", frozenset({"clarification_required"})),
]


async def main() -> None:
    settings = Settings()
    settings.validate_agent_router_config()
    router = AgentTaskRouter(settings)
    results = []
    # 小批并发降低验收耗时，同时避免给 Router provider 造成突发压力。
    for start in range(0, len(CASES), 4):
        batch = CASES[start : start + 4]
        routed = await asyncio.gather(
            *(
                router.route(query=case.query)
                for case in batch
            )
        )
        for case, result in zip(batch, routed, strict=True):
            actual = result.decision.intent
            results.append(
                {
                    "query": case.query,
                    "expected": sorted(case.expected),
                    "actual": actual,
                    "confidence": result.decision.confidence,
                    "source": result.source,
                    "passed": actual in case.expected,
                }
            )

    passed = sum(1 for item in results if item["passed"])
    accuracy = passed / len(results)
    print(json.dumps({"accuracy": accuracy, "results": results}, ensure_ascii=False, indent=2))
    assert accuracy >= 0.9
    assert all(
        item["actual"] != "simple_rag"
        for item in results[6:16]
    ), "文档操作或明确 Web Search 不得路由为 simple_rag"


if __name__ == "__main__":
    asyncio.run(main())
