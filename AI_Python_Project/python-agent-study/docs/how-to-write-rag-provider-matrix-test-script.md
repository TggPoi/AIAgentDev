# 如何编写 RAG Provider 矩阵测试脚本

这篇文档用 `scripts/tests/rag_memory/test_rag_provider_matrix.py` 作为例子，讲清楚这种测试脚本是怎么写出来的。

你不需要一开始就看懂所有 Python 语法。先记住这个脚本的核心目的：

> 把多组 provider 配置一组一组切换，然后直接构建 RAG pipeline，验证每组配置能不能正常创建和运行。

它不是普通的 HTTP 接口测试。它不启动 FastAPI 服务，也不调用 `/api/...` 接口，而是在同一个 Python 进程里直接调用项目代码。

## 这个脚本在测试什么

项目里的 RAG 功能有多个可切换 provider：

```python
PROVIDER_MATRIX = {
    "LLM_PROVIDER": ("mock", "qwen"),
    "EMBEDDING_PROVIDER": ("qwen",),
    "VECTOR_RETRIEVER_PROVIDER": ("mock", "milvus"),
    "KEYWORD_RETRIEVER_PROVIDER": ("mock", "elasticsearch"),
    "RAG_PIPELINE_PROVIDER": ("classic", "langgraph"),
}
```

这些配置会影响应用创建哪些对象：

- `LLM_PROVIDER` 决定创建 mock LLM 还是 Qwen LLM。
- `VECTOR_RETRIEVER_PROVIDER` 决定创建 mock vector retriever 还是 Milvus retriever。
- `KEYWORD_RETRIEVER_PROVIDER` 决定创建 mock keyword retriever 还是 Elasticsearch retriever。
- `RAG_PIPELINE_PROVIDER` 决定创建 classic pipeline 还是 langgraph pipeline。

这个脚本要验证的是：

1. 每组 provider 配置能不能被 `Settings` 正确读取。
2. 每组配置能不能通过依赖工厂函数创建对象。
3. 创建出来的 pipeline 能不能执行 `pipeline.run(req)`。
4. 如果开启 `--include-stream`，还能不能执行 `pipeline.stream(req)`。

## 整体写法

这种矩阵测试脚本通常分成 8 步：

1. 定义每个配置项有哪些候选值。
2. 用笛卡尔积生成所有组合。
3. 把一组组合包装成一个测试场景对象。
4. 每次测试前临时覆盖环境变量。
5. 清掉配置缓存，让 `get_settings()` 重新读取环境变量。
6. 直接调用依赖工厂函数构建 pipeline。
7. 执行 pipeline，记录通过或失败。
8. 清理资源，恢复环境变量，继续下一组。

换成伪代码就是：

```python
for scenario in 所有_provider组合:
    保存原来的环境变量
    临时设置当前 scenario 的环境变量
    清空 settings 缓存

    try:
        创建 retriever、llm、pipeline
        调用 pipeline.run()
        记录 PASS
    except Exception:
        记录 FAIL
    finally:
        关闭资源
        恢复原来的环境变量
        清空 settings 缓存
```

## 第一步：让脚本能导入 src 里的项目代码

脚本文件在 `scripts/tests/rag_memory` 目录下，项目代码在 `src` 目录下。

所以脚本开头有这段：

```python
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
```

逐句解释：

```python
Path(__file__)
```

表示当前脚本文件自己的路径。

```python
.resolve()
```

把路径转成绝对路径。

```python
.parents[3]
```

取当前文件的上四级目录。当前文件是：

```text
python-agent-study/scripts/tests/rag_memory/test_rag_provider_matrix.py
```

它的：

- `parents[0]` 是 `rag_memory`
- `parents[1]` 是 `tests`
- `parents[2]` 是 `scripts`
- `parents[3]` 是项目根目录 `python-agent-study`

所以：

```python
SRC_DIR = PROJECT_ROOT / "src"
```

得到的是：

```text
python-agent-study/src
```

最后：

```python
sys.path.insert(0, str(SRC_DIR))
```

是把 `src` 加到 Python 模块搜索路径里。这样后面才能写：

```python
from fast_app.core.config import get_settings
```

如果没有这段，直接运行脚本时 Python 可能找不到 `fast_app`。

## 第二步：定义 provider 矩阵

```python
PROVIDER_MATRIX = {
    "LLM_PROVIDER": ("mock", "qwen"),
    "EMBEDDING_PROVIDER": ("qwen",),
    "VECTOR_RETRIEVER_PROVIDER": ("mock", "milvus"),
    "KEYWORD_RETRIEVER_PROVIDER": ("mock", "elasticsearch"),
    "RAG_PIPELINE_PROVIDER": ("classic", "langgraph"),
}
```

这里用到两个基础数据类型。

外层是字典 `dict`：

```python
{
    key: value,
    key: value,
}
```

这个脚本里，key 是环境变量名，例如：

```python
"LLM_PROVIDER"
```

value 是元组 `tuple`，表示这个配置项允许测试哪些值，例如：

```python
("mock", "qwen")
```

注意这个：

```python
("qwen",)
```

它是只有一个元素的元组。最后的逗号不能省略。

如果写成：

```python
("qwen")
```

那只是一个字符串，不是元组。

## 第三步：用 dataclass 表示一个测试场景

脚本里有这个类：

```python
@dataclass(frozen=True)
class ProviderScenario:
    llm_provider: str
    embedding_provider: str
    vector_retriever_provider: str
    keyword_retriever_provider: str
    rag_pipeline_provider: str
```

可以把它理解成“测试场景数据包”。

如果不用 `dataclass`，你可能要手写很多初始化代码。用了 `@dataclass` 后，Python 会自动帮你生成类似这样的构造函数：

```python
def __init__(
    self,
    llm_provider,
    embedding_provider,
    vector_retriever_provider,
    keyword_retriever_provider,
    rag_pipeline_provider,
):
    self.llm_provider = llm_provider
    self.embedding_provider = embedding_provider
    self.vector_retriever_provider = vector_retriever_provider
    self.keyword_retriever_provider = keyword_retriever_provider
    self.rag_pipeline_provider = rag_pipeline_provider
```

所以你可以这样创建对象：

```python
scenario = ProviderScenario(
    llm_provider="mock",
    embedding_provider="qwen",
    vector_retriever_provider="mock",
    keyword_retriever_provider="mock",
    rag_pipeline_provider="classic",
)
```

`frozen=True` 表示创建后不希望再修改它：

```python
scenario.llm_provider = "qwen"
```

这种修改会报错。这样可以避免测试过程中不小心改坏场景对象。

## 第四步：理解类型标注

脚本里有很多类似这样的写法：

```python
def build_provider_scenarios() -> list[ProviderScenario]:
```

意思是：

- 这是一个函数。
- 函数名是 `build_provider_scenarios`。
- 它返回一个列表。
- 列表里的每个元素都是 `ProviderScenario`。

再看这个：

```python
def apply_provider_env(scenario: ProviderScenario) -> dict[str, str | None]:
```

意思是：

- 参数 `scenario` 应该是 `ProviderScenario`。
- 返回值是一个字典。
- 字典 key 是 `str`。
- 字典 value 是 `str` 或 `None`。

为什么 value 可能是 `None`？

因为环境变量原来可能不存在：

```python
old_value = os.environ.get("LLM_PROVIDER")
```

如果原来不存在，`get()` 返回 `None`。

类型标注不会自动改变代码行为。它主要是给读代码的人和类型检查工具看的。

## 第五步：用 product 生成所有组合

脚本里最关键的组合逻辑是：

```python
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
```

`product(...)` 来自：

```python
from itertools import product
```

它的作用是做“笛卡尔积”。

举一个小例子：

```python
from itertools import product

colors = ("red", "blue")
sizes = ("S", "M")

for color, size in product(colors, sizes):
    print(color, size)
```

输出是：

```text
red S
red M
blue S
blue M
```

也就是所有可能组合。

当前脚本里有：

```text
2 个 LLM_PROVIDER
1 个 EMBEDDING_PROVIDER
2 个 VECTOR_RETRIEVER_PROVIDER
2 个 KEYWORD_RETRIEVER_PROVIDER
2 个 RAG_PIPELINE_PROVIDER
```

所以组合数量是：

```text
2 * 1 * 2 * 2 * 2 = 16
```

每次循环会拿到一组具体 provider 值，然后创建一个 `ProviderScenario`：

```python
scenarios.append(
    ProviderScenario(
        llm_provider=llm_provider,
        embedding_provider=embedding_provider,
        vector_retriever_provider=vector_retriever_provider,
        keyword_retriever_provider=keyword_retriever_provider,
        rag_pipeline_provider=rag_pipeline_provider,
    )
)
```

## 第六步：把 scenario 转成环境变量

`ProviderScenario` 里有这个属性：

```python
@property
def env(self) -> dict[str, str]:
    return {
        "LLM_PROVIDER": self.llm_provider,
        "EMBEDDING_PROVIDER": self.embedding_provider,
        "VECTOR_RETRIEVER_PROVIDER": self.vector_retriever_provider,
        "KEYWORD_RETRIEVER_PROVIDER": self.keyword_retriever_provider,
        "RAG_PIPELINE_PROVIDER": self.rag_pipeline_provider,
    }
```

`@property` 的意思是：把一个方法伪装成属性来用。

有了它之后，调用时不用写：

```python
scenario.env()
```

而是写：

```python
scenario.env
```

这个属性会把对象里的字段转成环境变量字典。

例如一个 scenario 是：

```python
ProviderScenario(
    llm_provider="mock",
    embedding_provider="qwen",
    vector_retriever_provider="mock",
    keyword_retriever_provider="mock",
    rag_pipeline_provider="classic",
)
```

那么：

```python
scenario.env
```

结果就是：

```python
{
    "LLM_PROVIDER": "mock",
    "EMBEDDING_PROVIDER": "qwen",
    "VECTOR_RETRIEVER_PROVIDER": "mock",
    "KEYWORD_RETRIEVER_PROVIDER": "mock",
    "RAG_PIPELINE_PROVIDER": "classic",
}
```

## 第七步：临时覆盖环境变量

核心函数是：

```python
def apply_provider_env(scenario: ProviderScenario) -> dict[str, str | None]:
```

它做三件事。

第一，合并基础测试环境和当前 scenario 的环境：

```python
env_overrides = {
    **BASE_TEST_ENV,
    **scenario.env,
}
```

这里的 `**` 是字典展开。

例如：

```python
a = {"DEBUG": "true"}
b = {"LLM_PROVIDER": "mock"}
c = {**a, **b}
```

结果：

```python
{"DEBUG": "true", "LLM_PROVIDER": "mock"}
```

第二，保存原来的环境变量值：

```python
previous_values = {
    key: os.environ.get(key)
    for key in env_overrides
}
```

这是字典推导式。它等价于：

```python
previous_values = {}

for key in env_overrides:
    previous_values[key] = os.environ.get(key)
```

第三，把新的值写入当前进程环境变量：

```python
for key, value in env_overrides.items():
    os.environ[key] = value
```

注意：这只影响当前 Python 进程，不会永久修改你的系统环境变量。

## 第八步：为什么要清 get_settings 缓存

脚本里有：

```python
get_settings.cache_clear()
```

原因是 `get_settings()` 通常会被缓存。

如果不清缓存，流程可能变成这样：

1. 第一个场景设置 `LLM_PROVIDER=mock`。
2. 调用 `get_settings()`，读取到 mock，并缓存起来。
3. 第二个场景设置 `LLM_PROVIDER=qwen`。
4. 再调用 `get_settings()`，但它直接返回旧缓存。
5. 测试以为自己在测 qwen，其实还在用 mock。

所以每次覆盖环境变量后都要清缓存：

```python
get_settings.cache_clear()
```

每次恢复环境变量后也要清缓存：

```python
get_settings.cache_clear()
```

这样下一次读取配置才是准确的。

## 第九步：直接构建 pipeline

这个函数是测试脚本的核心：

```python
def build_pipeline_from_current_env() -> tuple[Any, list[object]]:
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
```

这段代码不是调用 HTTP 接口，而是直接调用依赖工厂函数：

```python
get_vector_retriever(...)
get_keyword_retriever(...)
get_llm_client(...)
get_rag_pipeline(...)
```

这些函数根据 `settings` 创建对应的对象。

也就是说，如果当前环境变量是：

```text
LLM_PROVIDER=mock
VECTOR_RETRIEVER_PROVIDER=mock
KEYWORD_RETRIEVER_PROVIDER=mock
RAG_PIPELINE_PROVIDER=classic
```

那就应该构建出 mock LLM、mock retriever 和 classic pipeline。

如果当前环境变量换成：

```text
LLM_PROVIDER=qwen
VECTOR_RETRIEVER_PROVIDER=milvus
KEYWORD_RETRIEVER_PROVIDER=elasticsearch
RAG_PIPELINE_PROVIDER=langgraph
```

那就应该构建出真实 provider 版本。

这个测试脚本就是通过这种方式验证 provider 配置和依赖构建逻辑是否匹配。

## 第十步：构造请求对象

每个测试 case 会创建一个 `RagChatRequest`：

```python
req = RagChatRequest(
    query=args.query,
    mode=mode,
    top_k=args.top_k,
    min_score=args.min_score,
)
```

它和 HTTP 请求体类似，只不过这里不是从网络请求里解析出来，而是脚本自己创建。

例如命令行默认 query 是：

```python
"什么是混合检索？"
```

默认 mode 是：

```python
"hybrid"
```

那么请求对象就相当于：

```python
RagChatRequest(
    query="什么是混合检索？",
    mode="hybrid",
    top_k=3,
    min_score=0.0,
)
```

## 第十一步：为什么函数前面有 async

脚本里有：

```python
async def run_one_case(...):
```

还有：

```python
response = await asyncio.wait_for(
    pipeline.run(req),
    timeout=args.timeout,
)
```

这是因为 `pipeline.run(req)` 是异步操作。

异步函数不能直接像普通函数那样拿结果：

```python
response = pipeline.run(req)
```

这样拿到的可能只是一个 coroutine 对象，并不是真正执行后的结果。

正确写法是：

```python
response = await pipeline.run(req)
```

脚本外面又包了一层：

```python
asyncio.wait_for(..., timeout=args.timeout)
```

意思是：最多等 `args.timeout` 秒。如果超过时间还没返回，就抛出超时异常，避免测试一直卡住。

## 第十二步：测试 stream

非流式测试是：

```python
pipeline.run(req)
```

流式测试是：

```python
pipeline.stream(req)
```

流式接口不是一次性返回完整答案，而是一段一段地产生 token。

所以脚本里用：

```python
async for token in agen:
    char_count += len(str(token))
```

`async for` 用来遍历异步生成器。

脚本不会无限制消费 stream，而是有一个限制：

```python
if stream_char_limit > 0 and char_count >= stream_char_limit:
    break
```

默认只消费前 200 个字符。这是为了避免真实服务流式输出太慢，导致测试耗时过长。

最后：

```python
await agen.aclose()
```

表示关闭这个异步生成器，释放资源。

## 第十三步：用 try / except / finally 保证清理

测试用例的结构是：

```python
try:
    pipeline, managed_objects = build_pipeline_from_current_env()
    response = await pipeline.run(req)
    记录成功
except Exception as exc:
    记录失败
finally:
    await close_if_needed(*managed_objects)
    restore_provider_env(previous_values)
```

这里最重要的是 `finally`。

不管测试成功还是失败，`finally` 都会执行。

这对测试脚本很重要，因为每个 case 都临时改了环境变量。如果失败后不恢复环境变量，后面的 case 就会被污染。

## 第十四步：理解 *objects

函数定义：

```python
async def close_if_needed(*objects: object) -> None:
```

这里的 `*objects` 表示接收任意数量的位置参数。

你可以这样调用：

```python
await close_if_needed(vector_retriever, keyword_retriever, llm_client)
```

在函数内部，`objects` 会变成一个 tuple：

```python
(vector_retriever, keyword_retriever, llm_client)
```

当前脚本实际调用是：

```python
await close_if_needed(*managed_objects)
```

这里的 `*managed_objects` 是把列表拆开传进去。

如果：

```python
managed_objects = [a, b, c]
```

那么：

```python
close_if_needed(*managed_objects)
```

等价于：

```python
close_if_needed(a, b, c)
```

## 第十五步：为什么 close_if_needed 要用 inspect

```python
close = getattr(obj, "close", None)
```

意思是：从对象上找 `close` 方法。如果没有，就返回 `None`。

```python
if close is None:
    continue
```

如果对象没有 `close()`，就跳过。

```python
result = close()
```

调用关闭方法。

但有些对象的 `close()` 是普通函数，有些对象的 `close()` 是异步函数。

所以脚本检查：

```python
if inspect.isawaitable(result):
    await result
```

如果 `close()` 返回的是可以 await 的对象，就等待它完成。

这样 `close_if_needed()` 同时兼容同步关闭和异步关闭。

## 第十六步：命令行参数怎么写

脚本使用 `argparse` 定义命令行参数。

例如：

```python
parser.add_argument(
    "--mock-only",
    action="store_true",
    help="只运行不依赖真实 LLM、Milvus、Elasticsearch 的 mock 组合",
)
```

`action="store_true"` 的意思是：

- 命令里没有 `--mock-only` 时，`args.mock_only` 是 `False`。
- 命令里有 `--mock-only` 时，`args.mock_only` 是 `True`。

例如运行：

```powershell
python scripts/tests/rag_memory/test_rag_provider_matrix.py --mock-only
```

脚本里就可以这样判断：

```python
if args.mock_only:
    ...
```

再看这个：

```python
parser.add_argument(
    "--modes",
    nargs="+",
    choices=REQUEST_MODES,
    default=["hybrid"],
)
```

`nargs="+"` 表示这个参数可以接收一个或多个值。

例如：

```powershell
python scripts/tests/rag_memory/test_rag_provider_matrix.py --modes vector keyword
```

得到：

```python
args.modes == ["vector", "keyword"]
```

`choices=REQUEST_MODES` 表示只能传：

```python
"vector"
"keyword"
"hybrid"
```

传其他值会直接报参数错误。

## 第十七步：筛选测试场景

脚本先生成全部 16 个 provider 场景，然后根据参数筛选。

```python
scenarios = filter_scenarios(build_provider_scenarios(), args)
```

如果你运行：

```powershell
python scripts/tests/rag_memory/test_rag_provider_matrix.py --mock-only
```

就只保留：

```python
scenario.llm_provider == "mock"
and scenario.vector_retriever_provider == "mock"
and scenario.keyword_retriever_provider == "mock"
```

这些不依赖真实 Qwen、Milvus、Elasticsearch，更适合本地先跑通。

如果你运行：

```powershell
python scripts/tests/rag_memory/test_rag_provider_matrix.py --real-only
```

就只保留至少依赖一个外部服务的场景。

## 第十八步：主循环怎么跑

主循环是：

```python
for scenario in scenarios:
    for mode in modes:
        case_results = await run_one_case(
            scenario=scenario,
            mode=mode,
            args=args,
        )
```

这表示每个 provider scenario 都会搭配每个 request mode 跑一遍。

如果有 16 个 scenario，只有一个 mode：

```text
16 * 1 = 16 个 case
```

如果有 16 个 scenario，开启 `--all-modes`，也就是 3 个 mode：

```text
16 * 3 = 48 个 case
```

如果再开启 `--include-stream`，每个 case 会跑：

- `run`
- `stream`

所以 operation 数量是：

```text
48 * 2 = 96 个 operation
```

## 第十九步：结果对象 CaseResult

脚本用 `CaseResult` 保存每次操作结果：

```python
@dataclass
class CaseResult:
    scenario: ProviderScenario
    mode: str
    operation: str
    ok: bool
    detail: str
```

每个字段的意思是：

- `scenario`：当前 provider 组合。
- `mode`：当前请求模式，例如 `vector`、`keyword`、`hybrid`。
- `operation`：当前测试的是 `run` 还是 `stream`。
- `ok`：是否通过。
- `detail`：成功或失败的细节。

成功时可能是：

```text
answer_length=123, sources=[...]
```

失败时可能是：

```text
ValueError: unknown provider
```

## 第二十步：怎么从零写一个类似脚本

你可以按这个模板写：

```python
from dataclasses import dataclass
from itertools import product
import os


MATRIX = {
    "A_PROVIDER": ("mock", "real"),
    "B_PROVIDER": ("mock", "real"),
}


@dataclass(frozen=True)
class Scenario:
    a_provider: str
    b_provider: str

    @property
    def env(self) -> dict[str, str]:
        return {
            "A_PROVIDER": self.a_provider,
            "B_PROVIDER": self.b_provider,
        }


def build_scenarios() -> list[Scenario]:
    scenarios: list[Scenario] = []

    for a_provider, b_provider in product(
        MATRIX["A_PROVIDER"],
        MATRIX["B_PROVIDER"],
    ):
        scenarios.append(
            Scenario(
                a_provider=a_provider,
                b_provider=b_provider,
            )
        )

    return scenarios


def apply_env(scenario: Scenario) -> dict[str, str | None]:
    previous_values = {
        key: os.environ.get(key)
        for key in scenario.env
    }

    for key, value in scenario.env.items():
        os.environ[key] = value

    return previous_values


def restore_env(previous_values: dict[str, str | None]) -> None:
    for key, value in previous_values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def run_one_case(scenario: Scenario) -> bool:
    previous_values = apply_env(scenario)

    try:
        # 这里换成你的真实测试逻辑：
        # 1. 读取配置
        # 2. 构建对象
        # 3. 调用方法
        # 4. 判断结果
        print("testing", scenario)
        return True
    except Exception as exc:
        print("failed", scenario, exc)
        return False
    finally:
        restore_env(previous_values)


def main() -> int:
    failed = 0

    for scenario in build_scenarios():
        ok = run_one_case(scenario)
        if not ok:
            failed += 1

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

这个最小模板已经有了矩阵测试的核心骨架：

- `MATRIX`：定义测试空间。
- `Scenario`：表示一组配置。
- `build_scenarios()`：生成所有组合。
- `apply_env()`：临时覆盖环境变量。
- `restore_env()`：恢复环境变量。
- `run_one_case()`：执行一个测试用例。
- `main()`：循环执行所有测试并返回退出码。

本项目的 `test_rag_provider_matrix.py` 只是在这个骨架上增加了：

- `get_settings.cache_clear()`。
- RAG 依赖工厂函数。
- `RagChatRequest`。
- async / await。
- `argparse` 命令行参数。
- run / stream 两种 operation。
- mock-only / real-only 场景筛选。

## 推荐学习顺序

如果你现在觉得脚本语法很多，不建议从头到尾硬读。可以按这个顺序学：

1. 先看 `PROVIDER_MATRIX`，理解测试空间从哪里来。
2. 再看 `ProviderScenario`，理解一组配置如何被包装成对象。
3. 再看 `build_provider_scenarios()`，理解 `product(...)` 如何生成 16 个组合。
4. 再看 `apply_provider_env()` 和 `restore_provider_env()`，理解每个 case 如何切换配置。
5. 再看 `build_pipeline_from_current_env()`，理解它为什么不需要 HTTP。
6. 再看 `run_one_case()`，理解一个测试用例的完整生命周期。
7. 最后再看 `argparse` 和 `async_main()`，理解命令行参数和批量执行。

## 常见错误

### 忘记清 settings 缓存

如果测试脚本修改了环境变量，但没有执行：

```python
get_settings.cache_clear()
```

后面的测试可能继续使用旧配置。

### 没有恢复环境变量

如果没有 `finally`，失败用例可能导致环境变量残留，污染后续测试。

所以环境变量恢复必须放在：

```python
finally:
    restore_provider_env(previous_values)
```

### 把一个元素的 tuple 写错

正确：

```python
("qwen",)
```

错误：

```python
("qwen")
```

后者只是字符串。

### 一开始就跑真实 provider

真实 provider 依赖密钥、服务连接和测试数据。建议先跑：

```powershell
python scripts/tests/rag_memory/test_rag_provider_matrix.py --mock-only
```

确认脚本和依赖装配逻辑没问题后，再跑真实 provider。

### 忘记 async 函数要 await

如果函数定义是：

```python
async def run(...):
```

调用它时通常要：

```python
await run(...)
```

否则你拿到的不是结果，而是一个还没执行完成的 coroutine。
