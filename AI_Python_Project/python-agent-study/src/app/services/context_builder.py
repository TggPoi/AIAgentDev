from app.schemas.document import RetrievedDoc

# 这个文件负责把检索结果构造成 context。

def build_context(docs: list[RetrievedDoc]) -> str:
    contents: list[str] = []

    for doc in docs:
        contents.append(f"[{doc['source']}] {doc['content']}")

# join 会把列表里的每个字符串依次拼接起来，元素与元素之间插入分隔符 "\n\n"，最后返回拼接好的完整字符串
    return "\n\n".join(contents)