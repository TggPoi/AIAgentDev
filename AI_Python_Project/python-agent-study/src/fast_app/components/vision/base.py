"""Vision Provider seam。"""

from __future__ import annotations

from typing import Awaitable, Callable, Protocol

from fast_app.domain.knowledge_models import VisionAnalysisResult, VisionImageContent


BeforeExternalCall = Callable[[], Awaitable[None]]


class VisionAnalysisError(RuntimeError):
    """对内隐藏 Provider 细节的稳定 Vision 错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VisionExternalCallRejected(RuntimeError):
    """ownership/cancellation hook 拒绝开始下一次 Provider 调用。"""


class BaseVisionClient(Protocol):
    """DocumentVisionService 唯一需要了解的 Provider interface。"""

    async def analyze(
        self,
        *,
        content: VisionImageContent,
        mode: str,
        before_provider_call: BeforeExternalCall | None = None,
    ) -> VisionAnalysisResult: ...


__all__ = [
    "BaseVisionClient",
    "BeforeExternalCall",
    "VisionAnalysisError",
    "VisionExternalCallRejected",
]
