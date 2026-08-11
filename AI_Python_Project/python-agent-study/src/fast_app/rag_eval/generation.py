"""主工程调用隔离 DeepEval Worker 的稳定 JSON 边界。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Protocol, Sequence

from fast_app.rag_eval.models import (
    GenerationEvaluationRequest,
    GenerationEvaluationResponse,
)


class GenerationEvaluator(Protocol):
    """Runner 所依赖的最小生成指标边界。"""

    async def evaluate(
        self,
        request: GenerationEvaluationRequest,
    ) -> GenerationEvaluationResponse: ...


class GenerationWorkerError(RuntimeError):
    """隔离 Worker 启动、超时或协议失败。"""


class SubprocessGenerationEvaluator:
    """使用独立 Python 环境运行 DeepEval，避免污染生产依赖。"""

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        timeout_seconds: float = 300.0,
        project_root: Path | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("generation worker timeout 必须大于 0")
        self.project_root = (project_root or Path.cwd()).resolve()
        self.command = list(command or self._default_command())
        self.timeout_seconds = timeout_seconds

    def _default_command(self) -> list[str]:
        configured = os.getenv("RAG_EVAL_JUDGE_PYTHON", "").strip()
        python = (
            Path(configured)
            if configured
            else self.project_root / ".venv-rag-eval" / "Scripts" / "python.exe"
        )
        if not python.is_file():
            raise GenerationWorkerError(
                f"未找到隔离 Eval Python: {python}; 请先创建 .venv-rag-eval"
            )
        return [str(python), "-m", "fast_app.rag_eval.generation_worker"]

    async def evaluate(
        self,
        request: GenerationEvaluationRequest,
    ) -> GenerationEvaluationResponse:
        if os.getenv("CONFIDENT_API_KEY", "").strip():
            raise GenerationWorkerError(
                "检测到 CONFIDENT_API_KEY；轻量 Eval 禁止 DeepEval 云端上传"
            )
        env = os.environ.copy()
        src = str(self.project_root / "src")
        env["PYTHONPATH"] = (
            src + os.pathsep + env["PYTHONPATH"]
            if env.get("PYTHONPATH")
            else src
        )
        process = await asyncio.create_subprocess_exec(
            *self.command,
            cwd=str(self.project_root),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        payload = request.model_dump_json().encode("utf-8")
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(payload),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise GenerationWorkerError(
                f"DeepEval Worker 超过 {self.timeout_seconds:g} 秒"
            ) from exc

        diagnostic = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            raise GenerationWorkerError(
                "DeepEval Worker 执行失败"
                + (f": {diagnostic[-1000:]}" if diagnostic else "")
            )
        try:
            data = json.loads(stdout.decode("utf-8"))
            response = GenerationEvaluationResponse.model_validate(data)
        except Exception as exc:
            raise GenerationWorkerError("DeepEval Worker 返回了非法 JSON 协议") from exc
        if response.case_id != request.case_id:
            raise GenerationWorkerError("DeepEval Worker case_id 与请求不一致")
        if set(response.metrics) != set(request.metrics):
            raise GenerationWorkerError("DeepEval Worker 返回的指标集合与请求不一致")
        return response


__all__ = [
    "GenerationEvaluator",
    "GenerationWorkerError",
    "SubprocessGenerationEvaluator",
]
