"""Upload one non-sensitive synthetic trace and verify that LangSmith can read it back."""

from datetime import UTC, datetime
from time import sleep
from uuid import uuid4

from langchain_core.tracers.langchain import wait_for_all_tracers
from langsmith import Client

from fast_app.core.config import get_settings
from fast_app.core.langsmith import configure_langsmith, langsmith_trace


settings = get_settings()
configure_langsmith(settings)
probe_name = f"codex.synthetic.health.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
client = Client(
    api_url=settings.langsmith_endpoint,
    api_key=settings.langsmith_api_key,
    # 健康检查必须在同一进程内得到确定结果，因此禁用后台批处理；生产业务
    # tracing 仍使用 SDK 默认批处理，不受此探针影响。
    auto_batch_tracing=False,
)
with langsmith_trace(
    settings,
    probe_name,
    "chain",
    {"probe": "synthetic-non-sensitive"},
    {"probe_kind": "health_check"},
    ["synthetic-health-check"],
) as run:
    probe_run_id = run.id
    run.end(outputs={"status": "ok", "contains_private_document": False})

wait_for_all_tracers()
# 该探针显式传入了自定义 Client；其批处理队列不属于 LangChain 全局 tracer，
# 因此还要主动 flush，才能在紧接着的读回请求中看到刚上传的 run。
run.client.flush()
# Hosted LangSmith 的写入与读取可能短暂最终一致；健康检查等待索引可见。
sleep(5)
try:
    uploaded_run = client.read_run(probe_run_id)
except Exception as exc:
    uploaded_run = None
    print(f"langsmith_probe_read_error={type(exc).__name__}: {exc}")
print(f"langsmith_probe_name={probe_name}")
print(f"langsmith_probe_uploaded={uploaded_run is not None}")
if uploaded_run is not None:
    print(f"langsmith_probe_run_id={uploaded_run.id}")

# 再走一次 Client 的同步 CRUD，区分 SDK trace 上下文问题与 API Key/项目权限问题。
direct_run_id = uuid4()
started_at = datetime.now(UTC)
client.create_run(
    name=f"{probe_name}.direct-api",
    inputs={"probe": "synthetic-direct-api"},
    run_type="chain",
    project_name=settings.langsmith_project,
    id=direct_run_id,
    start_time=started_at,
)
client.update_run(
    direct_run_id,
    outputs={"status": "ok", "contains_private_document": False},
    end_time=datetime.now(UTC),
)
# 新版 SDK 还可能启用 run-ops buffer；直接 CRUD 之后也必须 flush。
client.flush()
sleep(5)
try:
    direct_run = client.read_run(direct_run_id)
except Exception as exc:
    direct_run = None
    print(f"langsmith_direct_api_read_error={type(exc).__name__}: {exc}")
print(f"langsmith_direct_api_uploaded={direct_run is not None}")
if direct_run is not None:
    print(f"langsmith_direct_api_run_id={direct_run.id}")
