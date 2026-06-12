import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from fast_app.core.logging import get_logger
from fast_app.services.exceptions import ExternalServiceTimeoutError

# 作用：接收一个 async 外部调用，进行策略判断
# 判断异常是否可重试
# 控制最大重试次数
# 记录 retry 日志
# 把 httpx timeout 转成统一的 ExternalServiceTimeoutError

logger = get_logger(__name__)

T = TypeVar("T")


RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}

# 判断是否作为httpx异常进行重试的函数，主要包括超时、传输错误以及特定的HTTP状态码错误。
def is_retryable_httpx_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True

    if isinstance(exc, httpx.TransportError):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_HTTP_STATUS_CODES

    return False

# 通用的重试机制，可以用于任何异步操作，不仅限于HTTP请求。通过传入不同的is_retryable函数，可以灵活地控制哪些异常应该触发重试。
async def call_with_retry(
    operation_name: str,
    func: Callable[[], Awaitable[T]],
    max_retries: int,
    base_delay: float,
    is_retryable: Callable[[Exception], bool],
) -> T:
    attempt = 0

    while True:
        try:
            return await func()

        except Exception as exc:
            if isinstance(exc, httpx.TimeoutException):
                wrapped_exc = ExternalServiceTimeoutError(
                    f"{operation_name} 调用超时: {exc}"
                )
            else:
                wrapped_exc = exc
            # 判断当前异常 是否允许重试，重试次数是否超过最大重试次数
            should_retry = is_retryable(exc) and attempt < max_retries

            if not should_retry:
                raise wrapped_exc from exc

            attempt += 1
            delay = base_delay * attempt

            logger.warning(
                "外部调用失败，准备重试: operation=%s, attempt=%s, delay=%s, error=%s",
                operation_name,
                attempt,
                delay,
                exc,
            )

            await asyncio.sleep(delay)