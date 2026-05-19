from pathlib import Path

# **安全读取文本文件

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
        raise FileLoadError(f"文件编码错误，请确认文件是 UTF-8: {file_path}") from e