import argparse
import asyncio
import inspect
import os
import sys
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from fast_app.core.config import get_settings
from fast_app.dependencies.rag_dependencies import (
    get_keyword_retriever,
    get_llm_client,
    get_rag_pipeline,
    get_vector_retriever,
)
from fast_app.schemas.rag_chat_schema import RagChatRequest


# 这个脚本用“进程内直接构建依赖”的方式测试 RAG provider 组合。
#
# 它不启动 FastAPI，也不发送 HTTP 请求。每个测试用例会临时把 provider 名称
# 写入 os.environ，清掉已缓存的 Settings 对象，然后直接调用应用里的依赖工厂函数，
# 构建 RAG pipeline，再执行 pipeline.run，并可选执行 pipeline.stream。
# 这样就能在同一个 Python 进程里连续验证多组 provider 配置。
PROVIDER_MATRIX = {
    "LLM_PROVIDER": ("mock", "qwen"),
    "EMBEDDING_PROVIDER": ("qwen",),
    "VECTOR_RETRIEVER_PROVIDER": ("mock", "milvus"),
    "KEYWORD_RETRIEVER_PROVIDER": ("mock", "elasticsearch"),
    "RAG_PIPELINE_PROVIDER": ("classic", "langgraph"),
}

BASE_TEST_ENV = {
    # Keep provider matrix tests focused on provider combinations even when the
    # parent shell has a non-boolean DEBUG value such as "release".
    "DEBUG": "true",
}

REQUEST_MODES = ("vector", "keyword", "hybrid")


# 一个 ProviderScenario 表示从 PROVIDER_MATRIX 生成出来的一组具体配置，
# 例如 mock LLM + mock vector retriever + langgraph pipeline。
@dataclass(frozen=True)
class ProviderScenario:
    llm_provider: str
    embedding_provider: str
    vector_retriever_provider: str
    keyword_retriever_provider: str
    rag_pipeline_provider: str

    @property
    def env(self) -> dict[str, str]:
        return {
            "LLM_PROVIDER": self.llm_provider,
            "EMBEDDING_PROVIDER": self.embedding_provider,
            "VECTOR_RETRIEVER_PROVIDER": self.vector_retriever_provider,
            "KEYWORD_RETRIEVER_PROVIDER": self.keyword_retriever_provider,
            "RAG_PIPELINE_PROVIDER": self.rag_pipeline_provider,
        }

    @property
    def label(self) -> str:
        return (
            f"llm={self.llm_provider}, "
            f"embedding={self.embedding_provider}, "
            f"vector={self.vector_retriever_provider}, "
            f"keyword={self.keyword_retriever_provider}, "
            f"pipeline={self.rag_pipeline_provider}"
        )

    @property
    def uses_external_service(self) -> bool:
        return (
            self.llm_provider == "qwen"
            or self.vector_retriever_provider == "milvus"
            or self.keyword_retriever_provider == "elasticsearch"
        )


@dataclass
class CaseResult:
    scenario: ProviderScenario
    mode: str
    operation: str
    ok: bool
    detail: str


def build_provider_scenarios() -> list[ProviderScenario]:
    scenarios: list[ProviderScenario] = []

    # product(...) 会对所有 provider 候选值做笛卡尔积。
    # 当前矩阵会生成 2 * 1 * 2 * 2 * 2 = 16 个测试场景。
    for (
        llm_provider,
        embedding_provider,
        vector_retriever_provider,
        keyword_retriever_provider,
        rag_pipeline_provider,
    ) in product(
        PROVIDER_MATRIX["LLM_PROVIDER"],
        PROVIDER_MATRIX["EMBEDDING_PROVIDER"],
        PROVIDER_MATRIX["VECTOR_RETRIEVER_PROVIDER"],
        PROVIDER_MATRIX["KEYWORD_RETRIEVER_PROVIDER"],
        PROVIDER_MATRIX["RAG_PIPELINE_PROVIDER"],
    ):
        scenarios.append(
            ProviderScenario(
                llm_provider=llm_provider,
                embedding_provider=embedding_provider,
                vector_retriever_provider=vector_retriever_provider,
                keyword_retriever_provider=keyword_retriever_provider,
                rag_pipeline_provider=rag_pipeline_provider,
            )
        )

    return scenarios


def apply_provider_env(scenario: ProviderScenario) -> dict[str, str | None]:
    # 应用通过 Settings 读取 provider 配置，而 Settings 又来自环境变量。
    # 所以每个用例先临时覆盖当前进程的环境变量，让后面的依赖工厂函数
    # 按照当前 scenario 创建对应的组件。
    env_overrides = {
        **BASE_TEST_ENV,
        **scenario.env,
    }

    previous_values = {
        key: os.environ.get(key)
        for key in env_overrides
    }

    for key, value in env_overrides.items():
        os.environ[key] = value

    # get_settings() 带缓存；清缓存后，下一次读取配置时才会看到刚覆盖的环境变量。
    get_settings.cache_clear()
    return previous_values


def restore_provider_env(previous_values: dict[str, str | None]) -> None:
    # 每个用例结束后恢复原始环境变量，避免上一组 provider 配置污染下一组测试。
    for key, value in previous_values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    get_settings.cache_clear()


async def close_if_needed(*objects: object) -> None:
    for obj in objects:
        close = getattr(obj, "close", None)

        if close is None:
            continue

        result = close()

        if inspect.isawaitable(result):
            await result


def build_pipeline_from_current_env() -> tuple[Any, list[object]]:
    # 这是测试的核心：直接调用 FastAPI 依赖层里同一批工厂函数，
    # 构建 vector retriever、keyword retriever、LLM client 和 RAG pipeline。
    # 因为这里直接构建对象，所以切换 provider 组合时不需要重启 Web 服务。
    settings = get_settings()

    vector_retriever = get_vector_retriever(settings=settings)
    keyword_retriever = get_keyword_retriever(settings=settings)
    llm_client = get_llm_client(settings=settings)

    pipeline = get_rag_pipeline(
        settings=settings,
        vector_retriever=vector_retriever,
        keyword_retriever=keyword_retriever,
        llm_client=llm_client,
    )

    return pipeline, [vector_retriever, keyword_retriever, llm_client]


async def consume_stream(
    pipeline: Any,
    req: RagChatRequest,
    stream_char_limit: int,
) -> int:
    char_count = 0
    agen = pipeline.stream(req)

    try:
        async for token in agen:
            char_count += len(str(token))

            if stream_char_limit > 0 and char_count >= stream_char_limit:
                break

    finally:
        await agen.aclose()

    return char_count


async def run_one_case(
    scenario: ProviderScenario,
    mode: str,
    args: argparse.Namespace,
) -> list[CaseResult]:
    # 一个 case = 一组 provider scenario + 一种请求 mode。
    # 流程是：覆盖环境变量 -> 构建 pipeline -> 执行请求 -> 记录 PASS/FAIL
    # -> 在 finally 里恢复环境变量。
    previous_values = apply_provider_env(scenario)
    managed_objects: list[object] = []
    results: list[CaseResult] = []

    req = RagChatRequest(
        query=args.query,
        mode=mode,
        top_k=args.top_k,
        min_score=args.min_score,
    )

    try:
        pipeline, managed_objects = build_pipeline_from_current_env()

        # pipeline.run 用来验证当前 provider 组合下的普通非流式 RAG 路径。
        response = await asyncio.wait_for(
            pipeline.run(req),
            timeout=args.timeout,
        )

        results.append(
            CaseResult(
                scenario=scenario,
                mode=mode,
                operation="run",
                ok=True,
                detail=(
                    f"answer_length={len(response.answer)}, "
                    f"sources={response.sources}"
                ),
            )
        )

        if args.include_stream:
            # stream 测试是可选的；它通常更慢，而且真实 provider 场景下
            # 对 Qwen、Milvus、Elasticsearch 等外部服务准备程度要求更高。
            stream_chars = await asyncio.wait_for(
                consume_stream(
                    pipeline=pipeline,
                    req=req,
                    stream_char_limit=args.stream_char_limit,
                ),
                timeout=args.timeout,
            )

            results.append(
                CaseResult(
                    scenario=scenario,
                    mode=mode,
                    operation="stream",
                    ok=True,
                    detail=f"stream_chars={stream_chars}",
                )
            )

    except Exception as exc:
        operation = "run"
        if args.include_stream and results and results[-1].operation == "run":
            operation = "stream"

        results.append(
            CaseResult(
                scenario=scenario,
                mode=mode,
                operation=operation,
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
            )
        )

    finally:
        # 即使构建或执行失败，也要关闭带 close() 的对象，并恢复环境变量。
        await close_if_needed(*managed_objects)
        restore_provider_env(previous_values)

    return results


def filter_scenarios(
    scenarios: list[ProviderScenario],
    args: argparse.Namespace,
) -> list[ProviderScenario]:
    # 命令行参数先决定要跑哪些 provider 场景。
    # --mock-only 只保留纯 mock 场景，适合本地快速验证脚本和依赖装配逻辑。
    if args.mock_only:
        return [
            scenario
            for scenario in scenarios
            if scenario.llm_provider == "mock"
            and scenario.vector_retriever_provider == "mock"
            and scenario.keyword_retriever_provider == "mock"
        ]

    # --real-only 只保留会触碰外部服务的场景，例如 qwen、milvus、
    # elasticsearch。运行这些场景前需要准备好密钥、服务连接和测试数据。
    if args.real_only:
        return [
            scenario
            for scenario in scenarios
            if scenario.uses_external_service
        ]

    return scenarios


def print_scenarios(scenarios: list[ProviderScenario]) -> None:
    # 打印当前即将测试的场景清单。mock-safe 表示不需要真实外部服务，
    # external 表示至少会依赖一个真实 provider。
    for index, scenario in enumerate(scenarios, start=1):
        external = "external" if scenario.uses_external_service else "mock-safe"
        print(f"{index:02d}. [{external}] {scenario.label}")


def print_result(result: CaseResult) -> None:
    # 每个 CaseResult 对应一次具体操作的结果：run 或 stream。
    # 同一个 provider scenario + mode 在开启 --include-stream 时会产生两条结果。
    status = "PASS" if result.ok else "FAIL"
    print(
        f"[{status}] mode={result.mode}, operation={result.operation}, "
        f"{result.scenario.label}"
    )
    print(f"       {result.detail}")


def parse_args() -> argparse.Namespace:
    # 这些参数控制测试范围和测试强度：
    # - provider 范围：全部、mock-only、real-only
    # - 请求 mode：默认 hybrid，或通过 --all-modes 跑三种 mode
    # - 操作类型：默认只跑 run，或通过 --include-stream 额外跑 stream
    # - 失败策略：是否遇到第一个失败就停止
    parser = argparse.ArgumentParser(
        description=(
            "Run RAG provider matrix tests by overriding environment variables "
            "and invoking the pipeline directly."
        ),
    )
    parser.add_argument(
        "--query",
        default="什么是混合检索？",
        help="测试问题",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=REQUEST_MODES,
        default=["hybrid"],
        help="要测试的请求 mode，默认只测试 hybrid",
    )
    parser.add_argument(
        "--all-modes",
        action="store_true",
        help="测试 vector、keyword、hybrid 三种请求 mode",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
        help="RAG 请求 top_k",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="RAG 请求 min_score",
    )
    parser.add_argument(
        "--include-stream",
        action="store_true",
        help="同时测试 pipeline.stream；默认只测试 pipeline.run",
    )
    parser.add_argument(
        "--stream-char-limit",
        type=int,
        default=200,
        help="流式测试最多消费多少字符；0 表示消费完整流",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="单个 run 或 stream 操作超时时间，单位秒",
    )
    parser.add_argument(
        "--mock-only",
        action="store_true",
        help="只运行不依赖真实 LLM、Milvus、Elasticsearch 的 mock 组合",
    )
    parser.add_argument(
        "--real-only",
        action="store_true",
        help="只运行至少包含 qwen、milvus、elasticsearch 之一的组合",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="只打印 provider 组合，不执行测试",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="遇到第一个失败用例后停止",
    )

    args = parser.parse_args()

    # mock-only 和 real-only 是互斥的筛选条件，同时开启会让测试范围没有清晰语义。
    if args.mock_only and args.real_only:
        parser.error("--mock-only 和 --real-only 不能同时使用")

    return args


async def async_main() -> int:
    args = parse_args()
    # 先生成完整 provider 笛卡尔积，再按命令行参数筛选要执行的场景。
    scenarios = filter_scenarios(build_provider_scenarios(), args)

    # 默认只测 hybrid；--all-modes 会把 vector、keyword、hybrid 都纳入测试。
    modes = list(REQUEST_MODES) if args.all_modes else args.modes

    print("Provider scenarios:")
    print_scenarios(scenarios)

    # --list-scenarios 是 dry-run：只查看会有哪些组合，不真正构建 pipeline。
    if args.list_scenarios:
        return 0

    # 一个 case 是 scenario 和 mode 的组合；如果 include_stream 打开，
    # 每个 case 会执行 run 和 stream 两个 operation。
    total_cases = len(scenarios) * len(modes)
    total_operations = total_cases * (2 if args.include_stream else 1)
    print(
        "\nStart matrix test: "
        f"scenarios={len(scenarios)}, modes={modes}, "
        f"operations={total_operations}"
    )

    all_results: list[CaseResult] = []

    # 主测试循环：逐个 provider scenario、逐个 request mode 执行。
    # 真正的构建、运行、清理都在 run_one_case() 内完成。
    for scenario in scenarios:
        for mode in modes:
            print("\n" + "=" * 100)
            print(f"Scenario: {scenario.label}")
            print(f"Mode: {mode}")

            case_results = await run_one_case(
                scenario=scenario,
                mode=mode,
                args=args,
            )

            for result in case_results:
                print_result(result)
                all_results.append(result)

                # 适合调试时使用：第一个失败出现后马上返回非 0 退出码。
                if args.stop_on_failure and not result.ok:
                    print("\nStopped on first failure.")
                    return 1

    # 所有 operation 执行完后统一汇总。脚本退出码也由是否存在失败决定，
    # 方便在 CI 或本地批处理里判断测试是否通过。
    passed = sum(1 for result in all_results if result.ok)
    failed = len(all_results) - passed

    print("\n" + "=" * 100)
    print(f"Matrix summary: passed={passed}, failed={failed}, total={len(all_results)}")

    # 失败用例集中打印一次，避免用户需要在很长的矩阵输出里手动查找 FAIL。
    if failed:
        print("\nFailed cases:")
        for result in all_results:
            if not result.ok:
                print_result(result)

    return 0 if failed == 0 else 1


def main() -> int:
    # 脚本主体是 async 的，因为 pipeline.run / pipeline.stream 都是异步接口。
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
