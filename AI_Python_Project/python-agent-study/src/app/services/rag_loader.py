from app.utils.file_utils import FileLoadError, read_text_file


class RagLoadError(Exception):
    pass


def load_document_as_lines(file_path: str) -> list[str]:
    try:
        content = read_text_file(file_path)
    except FileLoadError as e:
        raise RagLoadError(f"RAG 文档加载失败: {file_path}") from e

    lines: list[str] = []

    for line in content.splitlines():
        normalized = line.strip()

        if normalized == "":
            continue

        lines.append(normalized)

    if len(lines) == 0:
        raise RagLoadError(f"RAG 文档内容为空: {file_path}")

    return lines