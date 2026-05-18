import json
from pathlib import Path
from typing import Any


def read_json_object(file_path: str) -> dict[str, Any]:

    path = Path(file_path)

    # path_name: data\config.json
    print("path_name:", path)

    # 查看当前工程目录，确认当前工作目录是不是项目根目录 D:\AI_Agent_Project\AI_Python_Project\python-agent-study 
    print(Path.cwd())

    if not path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {file_path}")

    content = path.read_text(encoding="utf-8")
    data = json.loads(content)

    if not isinstance(data, dict):
        raise ValueError("JSON 顶层必须是 object")

    return data


def main() -> None:
    # 这个相对路径不是基于当前 `.py` 文件所在目录，而是基于 **当前运行命令时所在的工作目录。 Path.cwd() **
    config = read_json_object("data/config.json")

    print("app_name:", config["app_name"])
    print("retrieval_mode:", config["retrieval_mode"])
    print("top_k:", config["top_k"])


if __name__ == "__main__":
    main()