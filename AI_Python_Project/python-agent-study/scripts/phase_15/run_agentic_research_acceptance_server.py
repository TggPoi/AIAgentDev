"""在独立端口启动当前工作树，用于 Agentic Research 真实链路验收。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)
os.environ["RAG_USE_MOCK"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

uvicorn.run("fast_app.main:app", host="127.0.0.1", port=8010)
