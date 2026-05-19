
def normalize_text(text: str) -> str:

    # 去掉每行首尾空格
    lines = text.splitlines()

    normalized_lines: list[str] = []

    for line in lines:
        # 过滤空行
        normalized = line.strip()

        if normalized == "":
            continue

        normalized_lines.append(normalized)

    # 重新用 \n 拼接
    return "\n".join(normalized_lines)