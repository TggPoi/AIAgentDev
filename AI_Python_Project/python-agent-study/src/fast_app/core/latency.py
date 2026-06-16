from logging import Logger
from time import perf_counter

from fast_app.core.logging import format_log_fields


def start_timer() -> float:
    return perf_counter()


def elapsed_ms(start_time: float) -> float:
    return (perf_counter() - start_time) * 1000


def is_slow_latency(latency_ms: float, threshold_ms: float) -> bool:
    return threshold_ms > 0 and latency_ms >= threshold_ms


def log_slow_operation(
    logger: Logger,
    event: str,
    latency_ms: float,
    threshold_ms: float,
    **fields: object,
) -> None:
    if not is_slow_latency(latency_ms, threshold_ms):
        return

    logger.warning(
        "slow_operation %s",
        format_log_fields(
            event=event,
            latency_ms=round(latency_ms, 2),
            threshold_ms=round(threshold_ms, 2),
            **fields,
        ),
    )
