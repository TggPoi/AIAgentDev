# 统一增强 Web 检索服务改造方案（v2 修订版）

> v2 修订记录：合入评审意见错误 1-4、瑕疵 5-6 及 fallback 契约缺口修复。与 v1 的差异在各节中以【v2 修订】标注。

## 一、总体设计与关键决策

**核心思路**：新建共享服务模块 `src/fast_app/services/rag/enhanced_web_search.py`（文件已创建并经核对），把 `rag_agent_nodes.py` L84-187 的全部确定性增强逻辑迁移进去，暴露唯一执行入口 `execute_enhanced_web_search()`。四条链路全部调用它：

| 链路 | 接入方式 | question 来源 | 失败策略 |
|---|---|---|---|
| RAG 主链路 `call_direct_web` | 委托调用（保持现有 LangSmith 子 run 配置透传） | `state["query"]` | **不降级**，异常外抛由现有 `classify_agent_error` 分类（与现状一致） |
| Research Worker | 替换 `_run_web_search_for_sub_question` 执行体 | 已隐私清洗的 `safe_web_query`（L306-313 已替换进 tool_input，服务不感知） | 增强链路抛异常时记告警日志并**回退裸 bocha 调用** |
| DeepAgent Researcher | 替换 web_search 闭包内的 bocha 调用 | 服务端拼接的 `public_query`（信任边界不变） | 同上回退裸 bocha |
| direct 文档工具循环 | 替换 web_search 闭包内的 bocha 调用 | 模型传入的 query（该链路本就无隐私重写） | 同上回退裸 bocha |

**关键决策**：
1. `forced_site` 语义：调用方显式传入 site 而 Planner 未规划出 site 时补入；Planner 已规划出 site 时不覆盖。
2. 【v2 修订】**Planner 实例为无状态轻量对象，四条链路各自持有独立实例**：RAG 主链路沿用 `create_call_direct_web_node` 内部自建（`rag_agent_builder.py` L97 不传 `search_planner`）；Research 链路在 `rag_dependencies.py` 新建并注入；`DeepDocumentAgent` 与 `DocumentTaskExecutor` 各自 `__init__` 自建。**不做跨链路实例共享**，避免改动 `build_rag_agent_graph` 签名。
3. 【v2 修订】DeepAgent 与 direct 链路的返回契约**双路径统一**：增强路径与 fallback 路径都经共享构造器输出，key 集合恒为 `{title, url, site_name, content}`，`content` 截断上限 8000 字符（常量定义在各自文件）。Research 链路内部使用 `RetrievedDoc`，无对外契约变化。
4. 【v2 修订】`rag_agent_nodes.py` 删除 6 个 helper 和 1 个常量；6 个 helper 经 import re-export 保持既有测试导入兼容，`_CONTENT_TERM_RELAX_MAX` 仅迁移、无测试引用、不 re-export。
5. `test_agent_task_router.py` 的 fake bocha patch 目标从 `nodes_module.search_web_with_bocha` 改为 `enhanced_module.search_web_with_bocha`；httpx patch 保留原处（见 8.1）。

---

## 二、`src/fast_app/services/rag/enhanced_web_search.py`

主体文件已创建（313 行，经评审逐字核对与现状一致），包含：6 个迁移 helper、`_CONTENT_TERM_RELAX_MAX`、`execute_enhanced_web_search()`。**还需追加两个载荷构造器**【v2 修订：瑕疵 6 + fallback 缺口】：

```python
def build_web_search_payload(
    docs: list[RetrievedDoc], *, content_limit: int
) -> list[dict[str, str]]:
    """构造给模型消费的 Web 搜索结果 JSON 载荷。

    返回 key 集合固定为 {title, url, site_name, content}，是 DeepAgent
    Researcher 与 direct 文档工具循环的对外契约；content 为增强链路产出
    的页面全文或摘要拼接，并按 content_limit 确定性截断。
    """

    return [
        {
            "title": doc.title,
            "url": str((doc.metadata or {}).get("url") or doc.title),
            "site_name": str((doc.metadata or {}).get("site_name") or ""),
            "content": doc.content[:content_limit],
        }
        for doc in docs
    ]


def build_payload_from_web_search_results(
    results, *, content_limit: int
) -> list[dict[str, str]]:
    """fallback 路径的载荷构造器：先把 WebSearchResult 转成 RetrievedDoc，
    再经 build_web_search_payload 输出，保证与增强路径 key 集合一致。

    content 用 title/snippet/summary/url 拼接，与增强链路摘要回退的
    内容来源保持一致。
    """

    fallback_docs = [
        RetrievedDoc(
            id=f"web:{index}",
            content="\n".join(
                part
                for part in (item.title, item.snippet, item.summary, item.url)
                if part
            ),
            score=1.0,
            source="web_search",
            title=item.title,
            metadata={"url": item.url, "site_name": item.site_name},
        )
        for index, item in enumerate(results, start=1)
    ]
    return build_web_search_payload(fallback_docs, content_limit=content_limit)
```

`__all__` 更新为：

```python
__all__ = [
    "build_payload_from_web_search_results",
    "build_web_search_payload",
    "execute_enhanced_web_search",
]
```

Research 链路的 fallback 保持第四节原有的 RetrievedDoc 构造（sha 前缀 id 进入 evidence，不改 id 方案），不走这两个构造器。

---

## 三、修改 `src/fast_app/graph/rag_agent/rag_agent_nodes.py`

### 3.1 删除 L84-187 的 6 个 helper 和 1 个常量【v2 修订：文字与列表对齐】

6 个 helper 在原位置删除，经下方 import re-export 保持测试兼容；`_CONTENT_TERM_RELAX_MAX` 仅迁移不 re-export。原位置替换为：

```python
from fast_app.services.rag.enhanced_web_search import (
    _build_direct_web_doc,          # noqa: F401 re-export，保持既有测试导入兼容
    _content_term_hit_count,        # noqa: F401
    _hard_match_direct_web_plan,    # noqa: F401
    _matches_direct_web_plan,       # noqa: F401
    _needs_sitemap_rescue,          # noqa: F401
    _relax_content_term_results,    # noqa: F401
    execute_enhanced_web_search,
)
```

### 3.2 `_execute_direct_web_search`（L264-443）整体替换为委托实现

```python
async def _execute_direct_web_search(
    *,
    state: RagAgentState,
    planner: DirectWebSearchPlanner,
    settings: Settings,
) -> dict[str, object]:
    """Direct Web 检索执行体；异常由节点包裹层统一分类。

    增强策略已收敛到共享服务 execute_enhanced_web_search，本节点只
    负责把 RagAgentState 与 LangSmith 子 run 配置透传给服务层。
    """

    operation = get_rag_agent_operation(state)
    docs = await execute_enhanced_web_search(
        settings=settings,
        planner=planner,
        question=state["query"],
        top_k=state["top_k"],
        plan_langchain_config=build_rag_langchain_child_config(
            settings=settings,
            state=state,
            pipeline_provider="rag_agent",
            operation=operation,
            step_name="call_direct_web",
            step_index=get_rag_agent_step_index(operation, "call_direct_web"),
            child_name="search_plan",
            run_name=f"rag_agent_pipeline.{operation}.call_direct_web.search_plan",
        ),
        select_langchain_config=build_rag_langchain_child_config(
            settings=settings,
            state=state,
            pipeline_provider="rag_agent",
            operation=operation,
            step_name="call_direct_web",
            step_index=get_rag_agent_step_index(operation, "call_direct_web"),
            child_name="candidate_selection",
            run_name=(
                f"rag_agent_pipeline.{operation}."
                "call_direct_web.candidate_selection"
            ),
        ),
    )
    return {
        "docs": docs,
        "tool_name": "web_search",
        "tool_error": None,
        "error_decision": None,
        "tool_call_count": state["tool_call_count"] + 1,
    }
```

### 3.3 import 清理【v2 修订：全部删除，已 grep 验证无其他使用点】

删除以下 import：
- `from fast_app.agents.tools.web_search_tools import search_web_with_bocha`（L22，唯一使用点在被替换的执行体内）
- `from urllib.parse import urlparse`（L3，唯一使用点在被迁移 helper 的 L91）
- `import httpx`（L5，唯一使用点在被迁移执行体的 L289/L399）
- `direct_web_search_planner` 导入收缩为 `from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner`（`DirectWebSearchPlan` 仅用于被迁移 helper 注解）
- `direct_web_page_fetch`（L68-72）/ `direct_web_page_text`（L73）/ `direct_web_sitemap`（L74）三个 import 块整体删除

---

## 四、修改 `src/fast_app/services/research/research_tool_loop.py`

### 4.1 新增 import 与模块级 logger（该文件目前无 logger）

```python
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner
from fast_app.services.rag.enhanced_web_search import execute_enhanced_web_search
```

import 区之后：

```python
logger = get_logger(__name__)
```

### 4.2 `ResearchToolLoop.__init__`（L138-156）：新增 `web_planner` 参数并保存

```python
    def __init__(
        self,
        settings: Settings,
        vector_retriever: BaseRetriever,
        keyword_retriever: BaseRetriever,
        llm_client: BaseLLMClient,
        reranker: BaseReranker | None = None,
        prompt_guard: PromptGuardService | None = None,
        parent_expander: MarkdownParentContextExpander | None = None,
        nl2sql_service: Nl2SqlService | None = None,
        web_planner: DirectWebSearchPlanner | None = None,
    ) -> None:
        self._settings = settings
        self._vector_retriever = vector_retriever
        self._keyword_retriever = keyword_retriever
        self._llm_client = llm_client
        self._reranker = reranker
        self._prompt_guard = prompt_guard
        self._parent_expander = parent_expander
        self._nl2sql_service = nl2sql_service
        self._web_planner = web_planner
```

### 4.3 分发点（L820-824）透传 config factory

```python
        if selected_tool == WEB_SEARCH_TOOL_NAME:
            return await self._run_web_search_for_sub_question(
                sub_question=sub_question,
                tool_input=tool_input,
                langchain_config_factory=langchain_config_factory,
            )
```

### 4.4 `_run_web_search_for_sub_question`（L955-1001）整体替换

```python
    async def _run_web_search_for_sub_question(
        self,
        sub_question: AgentTaskSubQuestion,
        tool_input: dict[str, Any],
        langchain_config_factory: LangChainConfigFactory | None = None,
    ) -> ToolExecutionResult:
        """执行网页搜索：优先增强链路，不可用时回退裸 Bocha 调用。

        tool_input 中的 query 已由执行分支替换为隐私清洗后的公开查询，
        增强服务不感知私有内容；site 通过 forced_site 传给 Planner 兜底。
        """

        query = str(tool_input.get("query") or sub_question.question).strip()
        count = coerce_int(tool_input.get("count"), default=5, minimum=1, maximum=10)
        site = str(tool_input.get("site") or "").strip() or None
        docs: list[RetrievedDoc] | None = None
        if self._web_planner is not None:
            try:
                docs = await execute_enhanced_web_search(
                    settings=self._settings,
                    planner=self._web_planner,
                    question=query,
                    top_k=count,
                    forced_site=site,
                    plan_langchain_config=(
                        langchain_config_factory(
                            f"sub_question.{sub_question.sub_question_id}.web_search.plan"
                        )
                        if langchain_config_factory is not None
                        else None
                    ),
                    select_langchain_config=(
                        langchain_config_factory(
                            f"sub_question.{sub_question.sub_question_id}.web_search.candidate_selection"
                        )
                        if langchain_config_factory is not None
                        else None
                    ),
                )
            except Exception as exc:
                # 增强链路是增强不是硬依赖：规划、sitemap 或抓取失败时
                # 回退直接搜索引擎调用，保证 Worker 工具循环可用性。
                logger.warning(
                    "research_web_search_enhanced_fallback %s",
                    format_log_fields(
                        event="research.web_search.enhanced_fallback",
                        sub_question_id=sub_question.sub_question_id,
                        error_type=type(exc).__name__,
                    ),
                )
                docs = None
        if docs is None:
            async with httpx.AsyncClient() as http_client:
                results = await search_web_with_bocha(
                    settings=self._settings,
                    http_client=http_client,
                    query=query,
                    count=count,
                    site=site,
                )
            # WebSearch 返回的数据模型与本地检索不同；转成 RetrievedDoc 后可以复用同一 RAG 上下文构造器。
            docs = [
                RetrievedDoc(
                    id=(
                        "web_"
                        + hashlib.sha256(
                            (item.url or f"{item.title}:{index}").encode("utf-8")
                        ).hexdigest()[:16]
                    ),
                    content=" ".join(
                        part
                        for part in [item.title, item.snippet, item.summary, item.url]
                        if part
                    ),
                    score=1.0,
                    source=WEB_SEARCH_TOOL_NAME,
                    title=item.title,
                    metadata={"url": item.url, "site_name": item.site_name},
                )
                for index, item in enumerate(results, start=1)
            ]
        return ToolExecutionResult(
            tool_output={
                "result_count": len(docs),
                "top_urls": [
                    str((doc.metadata or {}).get("url") or doc.title)
                    for doc in docs[:5]
                ],
            },
            evidence=[doc_to_evidence(doc) for doc in docs],
            context_docs=docs,
        )
```

---

## 五、修改 `src/fast_app/dependencies/rag_dependencies.py`

在 `research_tool_loop = ResearchToolLoop(...)`（L397）之前新增【v2 修订：注释明确为 Research 专用独立实例】：

```python
    # Research 链路专用增强 Web 检索 Planner（无状态，与 RAG 主链路各自持有独立实例）。
    direct_web_planner = DirectWebSearchPlanner(settings)
    research_tool_loop = ResearchToolLoop(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        llm_client=llm_client,
        reranker=reranker,
        prompt_guard=prompt_guard,
        parent_expander=parent_expander,
        nl2sql_service=nl2sql_service,
        web_planner=direct_web_planner,
    )
```

import 区新增：

```python
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner
```

---

## 六、修改 `src/fast_app/services/agent_tasks/deep_document_agent.py`

### 6.1 import 区（L56 之后）新增

```python
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner
from fast_app.services.rag.enhanced_web_search import (
    build_payload_from_web_search_results,
    build_web_search_payload,
    execute_enhanced_web_search,
)
```

### 6.2 模块级常量新增

```python
# 返回给 Researcher 的单页正文截断上限：增强链路会抓取真实全文，
# 过长的正文会挤占 SubAgent 上下文，这里做确定性截断。
_DEEP_WEB_SEARCH_CONTENT_LIMIT = 8000
```

### 6.3 `DeepDocumentAgent.__init__`（L931-938 赋值段末尾）新增一行

```python
        self._nl2sql_service = nl2sql_service
        self._web_planner = DirectWebSearchPlanner(settings)
```

### 6.4 web_search 闭包中 `public_query` 拼接之后到 `return` 整体替换【v2 修订：fallback 也走共享构造器，双路径 key 集合一致】

```python
                public_query = " ".join(
                    [plan.original_query[:200], deliverable.title, *topics]
                )
                try:
                    docs = await execute_enhanced_web_search(
                        settings=self._settings,
                        planner=self._web_planner,
                        question=public_query,
                        top_k=5,
                        forced_site=site,
                    )
                    payload = build_web_search_payload(
                        docs, content_limit=_DEEP_WEB_SEARCH_CONTENT_LIMIT
                    )
                except Exception:
                    # 增强链路不可用时回退直接搜索引擎调用；fallback 经
                    # 共享构造器输出，与增强路径保持同一 key 集合契约。
                    async with httpx.AsyncClient() as client:
                        results = await search_web_with_bocha(
                            settings=self._settings,
                            http_client=client,
                            query=public_query,
                            count=5,
                            site=site,
                        )
                    payload = build_payload_from_web_search_results(
                        results, content_limit=_DEEP_WEB_SEARCH_CONTENT_LIMIT
                    )
                used_tools.add("web_search")
                await persist_runtime_facts()
                return json.dumps(payload, ensure_ascii=False)
```

说明：闭包内不传 trace 配置（无当前图 RunnableConfig 作用域），Planner LLM 调用由 SDK 级 tracing 覆盖。`DocumentWebResearchInput` Schema、deliverable 校验、`_validate_public_topic` 不变。

---

## 七、修改 `src/fast_app/services/agent_tasks/document_task_executor.py`

### 7.1 import 区新增与模块级定义（该文件目前无 logger）

```python
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlanner
from fast_app.services.rag.enhanced_web_search import (
    build_payload_from_web_search_results,
    build_web_search_payload,
    execute_enhanced_web_search,
)
```

```python
logger = get_logger(__name__)

# direct 文档工具循环返回给模型的单页正文截断上限。
_DIRECT_WEB_SEARCH_CONTENT_LIMIT = 8000
```

### 7.2 `DocumentTaskExecutor.__init__`（L109 之后）新增一行

```python
        self._settings = settings
        self._web_planner = DirectWebSearchPlanner(settings)
```

### 7.3 direct 模式 web_search 闭包（L1193-1209）整体替换【v2 修订：fallback 同契约】

```python
            async def web_search(
                query: str,
                count: int = 5,
                site: str | None = None,
            ) -> str:
                try:
                    docs = await execute_enhanced_web_search(
                        settings=self._settings,
                        planner=self._web_planner,
                        question=query,
                        top_k=count,
                        forced_site=site,
                    )
                    return json.dumps(
                        build_web_search_payload(
                            docs, content_limit=_DIRECT_WEB_SEARCH_CONTENT_LIMIT
                        ),
                        ensure_ascii=False,
                    )
                except Exception as exc:
                    # 增强链路失败时回退裸 Bocha 调用，保持工具可用；
                    # fallback 经共享构造器输出，与增强路径同一 key 集合。
                    logger.warning(
                        "document_web_search_enhanced_fallback %s",
                        format_log_fields(
                            event="document.web_search.enhanced_fallback",
                            error_type=type(exc).__name__,
                        ),
                    )
                async with httpx.AsyncClient() as http_client:
                    results = await search_web_with_bocha(
                        settings=self._settings,
                        http_client=http_client,
                        query=query,
                        count=count,
                        site=site,
                    )
                return json.dumps(
                    build_payload_from_web_search_results(
                        results, content_limit=_DIRECT_WEB_SEARCH_CONTENT_LIMIT
                    ),
                    ensure_ascii=False,
                )
```

权限检查（`bocha_api_key` + `AGENT_TOOL_WEB_SEARCH`）位置不变。

---

## 八、测试修改

### 8.1 修改 `scripts/phase_15/test_agent_task_router.py` 的 patch 目标

- import 区新增：`import fast_app.services.rag.enhanced_web_search as enhanced_module`
- L291：`original_web_search = nodes_module.search_web_with_bocha` → `original_web_search = enhanced_module.search_web_with_bocha`
- L389：`nodes_module.search_web_with_bocha = fake_web_search` → `enhanced_module.search_web_with_bocha = fake_web_search`
- L478：`nodes_module.search_web_with_bocha = original_web_search` → `enhanced_module.search_web_with_bocha = original_web_search`

【v2 修订】**`nodes_module.httpx.AsyncClient` 的 patch（L292/L390/L479）保留原处不动**：Python 模块对象单例，`nodes_module.httpx is enhanced_module.httpx`，属性替换对 `enhanced_web_search` 同样生效。在 patch 处补一行注释固化该隐性依赖：

```python
    # httpx 是模块单例：nodes_module.httpx 与 enhanced_web_search.httpx 是同一对象，
    # 对 AsyncClient 的属性替换对共享服务模块同样生效；不要把该 patch 改坏或移除。
```

### 8.2 新增 `scripts/phase_15/test_enhanced_web_search.py`【v2 修订：修复 forced_site 矛盾 + 补 fallback 契约用例】

```python
"""增强 Web 检索共享服务的离线回归测试。

覆盖 execute_enhanced_web_search 主流程，以及增强/fallback 双路径
共用的载荷构造器契约。
"""

from __future__ import annotations

import asyncio

import fast_app.services.rag.enhanced_web_search as enhanced_module
from fast_app.agents.tools.web_search_tools import WebSearchResult
from fast_app.core.config import Settings
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.exceptions import NoSearchResultError
from fast_app.services.rag.direct_web_search_planner import DirectWebSearchPlan


class FakeEnhancedPlanner:
    """记录入参并按固定策略返回规划与选择的测试替身。"""

    def __init__(self, plan: DirectWebSearchPlan, selected_url: str | None = None):
        self._plan = plan
        self._selected_url = selected_url
        self.plan_questions: list[str] = []
        self.last_candidates: list[dict[str, str]] = []

    async def plan(self, *, question, count, langchain_config=None):
        self.plan_questions.append(question)
        return self._plan.model_copy(update={"count": count})

    async def select_candidate_url(
        self, *, question, plan, candidates, langchain_config=None
    ):
        self.last_candidates = candidates
        return self._selected_url


def _result(url: str, title: str = "", snippet: str = "", summary: str = "") -> WebSearchResult:
    return WebSearchResult(
        title=title or url, url=url, snippet=snippet, summary=summary
    )


async def _run_with_fakes(planner, raw_results, *, fetch_texts=None, forced_site=None):
    """patch bocha 与全文抓取后执行服务入口。"""

    original_bocha = enhanced_module.search_web_with_bocha
    original_fetch = enhanced_module.fetch_direct_web_page_texts
    calls: dict[str, object] = {}

    async def fake_bocha(**kwargs):
        calls.update(kwargs)
        return raw_results

    async def fake_fetch(http_client, page_urls, *, site):
        return list(fetch_texts or [])

    enhanced_module.search_web_with_bocha = fake_bocha
    enhanced_module.fetch_direct_web_page_texts = fake_fetch
    try:
        docs = await enhanced_module.execute_enhanced_web_search(
            settings=Settings(),
            planner=planner,
            question="测试问题",
            top_k=3,
            forced_site=forced_site,
        )
    finally:
        enhanced_module.search_web_with_bocha = original_bocha
        enhanced_module.fetch_direct_web_page_texts = original_fetch
    return docs, calls


async def step_multiple_sources_snippet_fallback() -> None:
    """multiple_sources 且正文抓取为空时，文档回退为摘要拼接。"""

    plan = DirectWebSearchPlan(
        query="postgresql row security", count=3, result_strategy="multiple_sources"
    )
    raw = [
        _result("https://example.com/a", snippet="snippet a"),
        _result("https://example.com/b", snippet="snippet b"),
    ]
    docs, _ = await _run_with_fakes(FakeEnhancedPlanner(plan), raw)
    assert len(docs) == 2
    assert "snippet a" in docs[0].content
    assert docs[0].metadata["url"] == "https://example.com/a"
    print("step_multiple_sources_snippet_fallback OK")


async def step_multiple_sources_fulltext() -> None:
    """multiple_sources 正文抓取成功时，文档内容为 URL 加全文。"""

    plan = DirectWebSearchPlan(
        query="postgresql row security", count=3, result_strategy="multiple_sources"
    )
    raw = [_result("https://example.com/a", snippet="snippet a")]
    docs, _ = await _run_with_fakes(
        FakeEnhancedPlanner(plan),
        raw,
        fetch_texts=[("https://example.com/a", "完整正文")],
    )
    assert docs[0].content == "https://example.com/a\n完整正文"
    print("step_multiple_sources_fulltext OK")


async def step_forced_site_and_hard_filter() -> None:
    """forced_site 补入空 site 计划，且域名硬约束过滤离站候选。"""

    plan = DirectWebSearchPlan(
        query="row security",
        count=3,
        result_strategy="multiple_sources",
        required_url_fragments=["16"],
    )
    raw = [
        _result("https://postgresql.org/docs/16/x.html", snippet="row security"),
        _result("https://other.com/docs/16/y.html", snippet="row security"),
    ]
    planner = FakeEnhancedPlanner(plan)
    docs, calls = await _run_with_fakes(planner, raw, forced_site="postgresql.org")
    assert calls["site"] == "postgresql.org"
    assert len(docs) == 1
    assert docs[0].metadata["url"] == "https://postgresql.org/docs/16/x.html"
    print("step_forced_site_and_hard_filter OK")


async def step_off_topic_raises() -> None:
    """general 模式无 site 且主题词全不命中时抛 NoSearchResultError。"""

    plan = DirectWebSearchPlan(
        query="row security",
        count=3,
        result_strategy="multiple_sources",
        required_content_terms=["row security"],
    )
    raw = [_result("https://example.com/unrelated", snippet="无关内容")]
    try:
        await _run_with_fakes(FakeEnhancedPlanner(plan), raw)
    except NoSearchResultError:
        print("step_off_topic_raises OK")
        return
    raise AssertionError("离题候选应触发 NoSearchResultError")


async def step_single_best_page_candidate_pool() -> None:
    """盲区 A：single_best_page 候选池保留 URL 片段硬约束。"""

    plan = DirectWebSearchPlan(
        query="row security",
        count=3,
        result_strategy="single_best_page",
        site="example.org",
        required_url_fragments=["16"],
    )
    raw = [
        _result("https://example.org/docs/16/a.html", snippet="row security"),
        _result("https://example.org/docs/15/b.html", snippet="row security"),
    ]
    planner = FakeEnhancedPlanner(plan, selected_url=None)
    docs, _ = await _run_with_fakes(planner, raw)
    assert all("16" in item["url"] for item in planner.last_candidates)
    assert len(docs) == 1
    assert docs[0].metadata["url"] == "https://example.org/docs/16/a.html"
    print("step_single_best_page_candidate_pool OK")


_PAYLOAD_KEYS = {"title", "url", "site_name", "content"}


async def step_payload_contract() -> None:
    """增强路径载荷构造器：key 集合与 content 截断是固化契约。"""

    doc = RetrievedDoc(
        id="web:1",
        content="x" * 20,
        score=1.0,
        source="web_search",
        title="标题",
        metadata={"url": "https://postgresql.org/a", "site_name": "postgresql.org"},
    )
    payload = enhanced_module.build_web_search_payload([doc], content_limit=10)
    assert payload[0].keys() == _PAYLOAD_KEYS
    assert payload[0]["url"] == "https://postgresql.org/a"
    assert payload[0]["content"] == "x" * 10
    print("step_payload_contract OK")


async def step_fallback_payload_contract() -> None:
    """fallback 路径载荷构造器：与增强路径 key 集合完全一致，content 拼接自摘要字段。"""

    results = [
        _result(
            "https://postgresql.org/docs/16/x.html",
            title="Row Security",
            snippet="snippet text",
            summary="summary text",
        )
    ]
    payload = enhanced_module.build_payload_from_web_search_results(
        results, content_limit=8000
    )
    assert payload[0].keys() == _PAYLOAD_KEYS
    assert payload[0]["url"] == "https://postgresql.org/docs/16/x.html"
    assert payload[0]["site_name"] == ""
    assert "snippet text" in payload[0]["content"]
    assert "summary text" in payload[0]["content"]
    print("step_fallback_payload_contract OK")


async def main() -> None:
    await step_multiple_sources_snippet_fallback()
    await step_multiple_sources_fulltext()
    await step_forced_site_and_hard_filter()
    await step_off_topic_raises()
    await step_single_best_page_candidate_pool()
    await step_payload_contract()
    await step_fallback_payload_contract()
    print("test_enhanced_web_search ALL OK")


if __name__ == "__main__":
    asyncio.run(main())
```

### 8.3 回归验证清单（PowerShell，`.tmp\*.ps1` 模式，设置 `PYTHONPATH=src`）

按顺序执行，全部通过后删除临时脚本：

1. `scripts/phase_15/test_enhanced_web_search.py`（新）
2. `scripts/phase_15/test_agent_task_router.py`（patch 目标已改）
3. `scripts/phase_15/test_direct_web_filter_fetch.py`（验证 re-export 兼容）
4. `scripts/phase_15/test_direct_web_sitemap.py`
5. `scripts/phase_15/test_direct_web_redirect_error.py`、`test_direct_web_page_text.py`
6. `scripts/phase_15/test_schema_field_descriptions.py`、`scripts/test_langsmith_tracing.py`
7. 可选：真实网络端到端（`DirectWebSearchPlanner` + RLS 查询），确认主链路行为未退化。

---

## 九、假设与风险

1. **LLM 调用成本**：Research / DeepAgent / direct 链路每次 web_search 工具调用新增 1 次 Planner 规划调用（single_best_page 时再 +1 次候选选择），使用 `agent_router_*` 轻量模型配置。
2. **DeepAgent 限额不变**：Researcher 的 `tool_run_limits={"web_search": 2}` 保持不变。
3. **隐私边界不变**：三条链路的现有 query 清洗逻辑全部保留在服务调用之前，增强服务只接收公开问题。
4. **回退语义**：三条 tool 链路回退裸 bocha 时记结构化告警日志（DeepAgent 闭包沿用现有裸 `except Exception` 不记日志的写法）；RAG 主链路无回退，保持现有错误分类行为。
5. 【v2 修订】**契约统一**：DeepAgent / direct 链路增强与 fallback 双路径 key 集合恒为 `{title, url, site_name, content}`，由两个共享构造器确定性保证，并有 `step_payload_contract` / `step_fallback_payload_contract` 两个用例覆盖。
6. `web_search_tools.py` 中的 `build_web_search_tool` 工厂函数不动。
7. 已创建文件 `src/fast_app/services/rag/enhanced_web_search.py` 保留，实施时仅追加第二节的两个载荷构造器并更新 `__all__`。