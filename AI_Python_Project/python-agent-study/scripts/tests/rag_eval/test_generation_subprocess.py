"""隔离生成指标 Worker 边界的确定性契约测试。"""

import asyncio
import sys

from fast_app.rag_eval.generation import (
    GenerationWorkerError,
    SubprocessGenerationEvaluator,
)
from fast_app.rag_eval.models import GenerationEvaluationRequest


def request() -> GenerationEvaluationRequest:
    return GenerationEvaluationRequest(
        case_id="case-1",
        question="问题",
        answer="答案",
        retrieval_context=["上下文"],
        required_key_facts=["事实"],
        metrics=["generation_faithfulness"],
    )


async def success_test() -> None:
    code = (
        "import json,sys; p=json.load(sys.stdin); "
        "json.dump({'case_id':p['case_id'],'judge_model':'fake-qwen',"
        "'metrics':{'generation_faithfulness':{"
        "'metric_name':'generation_faithfulness','score':0.8,'threshold':0.5,"
        "'passed':True,'status':'evaluated','short_reason':'ok','error':None}}},"
        "sys.stdout)"
    )
    evaluator = SubprocessGenerationEvaluator(
        command=[sys.executable, "-c", code],
        timeout_seconds=5,
    )
    result = await evaluator.evaluate(request())
    assert result.judge_model == "fake-qwen"
    assert result.metrics["generation_faithfulness"].score == 0.8


async def invalid_json_test() -> None:
    evaluator = SubprocessGenerationEvaluator(
        command=[sys.executable, "-c", "print('not-json')"],
        timeout_seconds=5,
    )
    try:
        await evaluator.evaluate(request())
    except GenerationWorkerError as exc:
        assert "非法 JSON" in str(exc)
    else:
        raise AssertionError("非法 Worker JSON 必须失败")


async def timeout_test() -> None:
    evaluator = SubprocessGenerationEvaluator(
        command=[sys.executable, "-c", "import time; time.sleep(2)"],
        timeout_seconds=0.05,
    )
    try:
        await evaluator.evaluate(request())
    except GenerationWorkerError as exc:
        assert "超过" in str(exc)
    else:
        raise AssertionError("Worker 超时必须失败")


async def main() -> None:
    await success_test()
    await invalid_json_test()
    await timeout_test()


if __name__ == "__main__":
    asyncio.run(main())
    print("rag_eval generation subprocess tests passed")
