from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from fast_app.core.config import Settings
from fast_app.domain.prompt_guard_models import PromptGuardResult
from fast_app.domain.rag_models import RetrievedDoc
from fast_app.services.rag.prompt_guard_service import (
    MAX_PARALLEL_DOCUMENT_CLASSIFICATIONS,
    PromptGuardService,
)


class RecordingPromptGuard(PromptGuardService):
    """不调用真实模型，只记录 filter_retrieved_docs 的实际并发数。"""

    def __init__(self) -> None:
        super().__init__(
            Settings(
                _env_file=None,
                PROMPT_GUARD_ENABLED=True,
                PROMPT_GUARD_RETRIEVED_DOCUMENT_CHECK_ENABLED=True,
            )
        )
        self.active = 0
        self.max_active = 0
        self.call_count = 0

    async def classify_retrieved_doc(self, doc, *, source):
        self.call_count += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            # 给事件循环切换机会，证明多个分类任务确实重叠执行。
            await asyncio.sleep(0.01)
            return PromptGuardResult(reason=f"{doc.id}_allowed")
        finally:
            self.active -= 1


async def main() -> None:
    guard = RecordingPromptGuard()
    docs = [
        RetrievedDoc(
            id=f"doc-{index}",
            content=f"content-{index}",
            score=1.0,
            source="test",
            metadata={},
        )
        for index in range(10)
    ]

    filtered = await guard.filter_retrieved_docs(docs, source="test.parallel")

    # 安全过滤不能改变检索排名；并发必须大于 1 且不超过服务端硬上限。
    assert [item.id for item in filtered] == [item.id for item in docs]
    assert 1 < guard.max_active <= MAX_PARALLEL_DOCUMENT_CLASSIFICATIONS

    guard.settings.prompt_guard_retrieved_document_check_enabled = False
    guard.call_count = 0
    assert await guard.filter_retrieved_docs(docs, source="test.disabled") == docs
    assert guard.call_count == 0
    print("prompt_guard_document_parallelism=passed")


if __name__ == "__main__":
    asyncio.run(main())
