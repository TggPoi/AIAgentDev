"""证明隔离 Worker 不读取项目 dotenv，也拒绝 Confident 云端密钥。"""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def main() -> None:
    root = Path.cwd().resolve()
    python = root / ".venv-rag-eval" / "Scripts" / "python.exe"
    assert python.is_file(), "缺少 .venv-rag-eval 兼容性环境"
    with TemporaryDirectory() as directory:
        workdir = Path(directory)
        (workdir / ".env").write_text(
            "CONFIDENT_API_KEY=must-not-be-loaded\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.pop("CONFIDENT_API_KEY", None)
        for name in (
            "DEEPEVAL_DISABLE_DOTENV",
            "DEEPEVAL_TELEMETRY_OPT_OUT",
            "DEEPEVAL_DISABLE_LEGACY_KEYFILE",
            "DEEPEVAL_NO_INSPECT_PROMPT",
            "DEEPEVAL_FILE_SYSTEM",
        ):
            env.pop(name, None)
        env["PYTHONPATH"] = str(root / "src")
        code = (
            "from fast_app.rag_eval.deep_eval_adapter import "
            "configure_deepeval_environment; "
            "from deepeval.config.settings import get_settings; "
            "assert get_settings().CONFIDENT_API_KEY is None; "
            "print('dotenv-disabled')"
        )
        result = subprocess.run(
            [str(python), "-c", code],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "dotenv-disabled" in result.stdout
        assert sorted(path.name for path in workdir.iterdir()) == [".env"]

        env["CONFIDENT_API_KEY"] = "must-be-rejected"
        rejected = subprocess.run(
            [str(python), "-c", "import fast_app.rag_eval.deep_eval_adapter"],
            cwd=workdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert rejected.returncode != 0
        assert "禁止配置 CONFIDENT_API_KEY" in rejected.stderr


if __name__ == "__main__":
    main()
    print("rag_eval DeepEval process safety tests passed")
