import json
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


def _normalize_log_value(value: object) -> object:
    if isinstance(value, set):
        return sorted(value)

    if isinstance(value, tuple):
        return list(value)

    return value


def format_log_fields(**fields: object) -> str:
    parts: list[str] = []

    for key, value in fields.items():
        value = _normalize_log_value(value)

        if value is None:
            normalized = "-"
        elif isinstance(value, str):
            normalized = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, (list, dict)):
            normalized = json.dumps(value, ensure_ascii=False)
        else:
            normalized = str(value)

        normalized = normalized.replace("\n", "\\n").replace("\r", "\\r")
        parts.append(f"{key}={normalized}")

    return " ".join(parts)


# `setup_logging(settings)` 最合适的位置是应用启动时
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
