import json
from pathlib import Path
from typing import Any


class FileLoadError(Exception):
    pass


def read_text_file(file_path: str) -> str:
    path = Path(file_path)

    if not path.exists():
        raise FileLoadError(f"文件不存在: {file_path}")

    if not path.is_file():
        raise FileLoadError(f"路径不是文件: {file_path}")

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise FileLoadError(f"文件编码错误，请使用 UTF-8: {file_path}") from e


def read_json_object(file_path: str) -> dict[str, Any]:
    path = Path(file_path)

    if not path.exists():
        raise FileLoadError(f"JSON 文件不存在: {file_path}")

    if not path.is_file():
        raise FileLoadError(f"路径不是文件: {file_path}")

    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except UnicodeDecodeError as e:
        raise FileLoadError(f"JSON 文件编码错误，请使用 UTF-8: {file_path}") from e
    except json.JSONDecodeError as e:
        raise FileLoadError(
            f"JSON 格式错误: {file_path}, line={e.lineno}, column={e.colno}"
        ) from e

    if not isinstance(data, dict):
        raise FileLoadError(f"JSON 顶层结构必须是 object/dict: {file_path}")

    return data