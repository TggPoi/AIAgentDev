from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    """把评测报告对象转换成 json.dumps 可以处理的结构。

    评测报告里混合了 dataclass、Pydantic model、list、dict。
    这个函数统一把它们转换成基础 Python 类型。
    """

    if is_dataclass(value):
        return to_jsonable(asdict(value))

    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump())

    if isinstance(value, dict):
        return {
            str(key): to_jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]

    if isinstance(value, Path):
        return str(value)

    return value
