import logging

from fast_app.core.config import Settings

# `setup_logging(settings)` 最合适的位置是应用启动时，也就是后续阶段 4-5 的 `lifespan`。
# 但现在还没有学习 lifespan。
# 所以本节先采用一个简单、安全的方式
def setup_logging(settings: Settings) -> None:
    log_level = settings.log_level.upper()
    # 影响整个 Python 程序的 logging 行为
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)