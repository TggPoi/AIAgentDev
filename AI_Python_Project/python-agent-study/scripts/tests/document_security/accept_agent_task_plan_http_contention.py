from __future__ import annotations

"""四 Worker HTTP 层争抢同一 TaskPlan 的验收脚本。

对同一个处于 waiting_confirmation 的新 TaskPlan 同时发出 20 个不同幂等键的
confirm，只接受 `1 个 2xx + 19 个 AGENT_TASK_PLAN_BUSY`。它还要回读最终
TaskPlan，防止"只有一个请求返回成功，但任务事实仍卡在 running"。日志中若出现
两个真实 ToolCall、两个 MR 或两个发布版本，即使 HTTP 断言通过也必须判失败。

用法（先以四 Worker 启动真实应用）：
  uvicorn fast_app.main:app --host 127.0.0.1 --port 8000 --workers 4
  python -B scripts/tests/document_security/accept_agent_task_plan_http_contention.py `
    --task-plan-id "task_plan_替换为全新待确认任务" --token-env LOAD_USER_01_TOKEN
"""

import argparse
import asyncio
import json
import os
from collections import Counter
from uuid import uuid4

import httpx


def read_error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("code") if isinstance(body, dict) else None


async def main_async(args) -> None:
    token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise RuntimeError(f"missing token env: {args.token_env}")
    start = asyncio.Event()
    headers = {"Authorization": f"Bearer {token}"}
    url = (
        f"{args.base_url.rstrip('/')}/agent/task-plans/"
        f"{args.task_plan_id}/confirm"
    )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(args.timeout_seconds),
        limits=httpx.Limits(max_connections=args.attempts),
    ) as client:
        async def attempt(number: int) -> tuple[int, str | None]:
            await start.wait()
            response = await client.post(
                url,
                headers={
                    **headers,
                    "Idempotency-Key": f"contention-{number:03d}-{uuid4().hex}",
                },
                json={"confirmed": True},
            )
            return response.status_code, read_error_code(response)

        tasks = [asyncio.create_task(attempt(i)) for i in range(args.attempts)]
        start.set()
        results = await asyncio.gather(*tasks)

        state_response = await client.get(
            f"{args.base_url.rstrip('/')}/agent/task-plans/{args.task_plan_id}",
            headers=headers,
        )
        state_response.raise_for_status()
        final_state = state_response.json()

    status_counts = Counter(status for status, _code in results)
    code_counts = Counter(code for _status, code in results if code)
    winners = sum(1 for status, _code in results if 200 <= status < 300)
    busy = code_counts["AGENT_TASK_PLAN_BUSY"]
    non_busy = sum(1 for _status, code in results if code != "AGENT_TASK_PLAN_BUSY")
    if args.allow_winner_business_failure:
        # 控制面验收模式：计划内容为空（无可执行文档动作）时，唯一进入业务路径的
        # 请求会得到业务失败，而不是 2xx。核心不变量不变：恰好一个非 409 执行者、
        # 其余全部 409 BUSY，且任务收敛到稳定终态（租约被唯一执行者释放）。
        assert non_busy == 1, results
        assert busy == args.attempts - 1, results
        assert final_state.get("status") in {
            "completed",
            "completed_with_warnings",
            "failed",
            "cancelled",
        }, final_state
    else:
        assert winners == 1, results
        assert busy == args.attempts - 1, results
        assert final_state.get("status") in {
            "completed",
            "completed_with_warnings",
        }, final_state
    print(
        json.dumps(
            {
                "status_counts": dict(status_counts),
                "error_code_counts": dict(code_counts),
                "final_status": final_state.get("status"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("http_multiworker_single_owner=passed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-plan-id", required=True)
    parser.add_argument("--token-env", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--attempts", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--allow-winner-business-failure",
        action="store_true",
        help="控制面验收模式：唯一非 409 执行者允许返回业务失败（计划无真实可确认动作时使用）。",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
