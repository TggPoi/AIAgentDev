from pathlib import Path

from app.utils.text_utils import normalize_line


def load_text_lines(file_path: str) -> list[str]:
    
    path = Path(file_path)

    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    result: list[str] = []

    for line in lines:
        normalized = normalize_line(line)

        if normalized == "":
            continue

        result.append(normalized)

    return result