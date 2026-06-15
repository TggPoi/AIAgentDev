import logging

from fast_app.core.config import Settings
from fast_app.core.request_context import get_request_id, get_trace_id


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        record.trace_id = get_trace_id() or "-"
        return True


def _has_request_context_filter(filters: list[logging.Filter]) -> bool:
    return any(isinstance(item, RequestContextFilter) for item in filters)


def _add_request_context_filter(root_logger: logging.Logger) -> None:
    if not _has_request_context_filter(root_logger.filters):
        root_logger.addFilter(RequestContextFilter())

    for handler in root_logger.handlers:
        if not _has_request_context_filter(handler.filters):
            handler.addFilter(RequestContextFilter())

# `setup_logging(settings)` 最合适的位置是应用启动时，也就是后续阶段 4-5 的 `lifespan`。
# 但现在还没有学习 lifespan。
# 所以本节先采用一个简单、安全的方式
def setup_logging(settings: Settings) -> None:
    log_level = settings.log_level.upper()
    # 影响整个 Python 程序的 logging 行为
    logging.basicConfig(
        level=log_level,
        format=(
            "%(asctime)s | %(levelname)s | %(name)s | "
            "request_id=%(request_id)s | trace_id=%(trace_id)s | %(message)s"
        ),
    )

    root_logger = logging.getLogger()
    _add_request_context_filter(root_logger)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
