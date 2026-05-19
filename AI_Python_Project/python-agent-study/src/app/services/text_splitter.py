
# 按照固定字符数切分文本。

def split_text_by_size(text: str, chunk_size: int = 200) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if text == "":
        return []

    chunks: list[str] = []

    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end

    return chunks