from pathlib import Path


def write_text_file(file_path: str, content: str) -> None:
    path = Path(file_path)
    
    print(f"Writing to file: {path}")

    path.write_text(content, encoding="utf-8")