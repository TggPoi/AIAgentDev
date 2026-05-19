from app.schemas.document import Document
from app.services.text_splitter import split_text_by_size
from app.utils.file_utils import FileLoadError, read_text_file
from app.utils.text_utils import normalize_text

# 1. 读取文件
# 2. 清洗文本
# 3. 判断文本是否为空
# 4. 按 chunk_size 切分
# 5. 构造 Document 列表

class DocumentLoadError(Exception):
    pass


def load_and_split_text_file(
    file_path: str,
    chunk_size: int = 200,
) -> list[Document]:
    
    try:
        raw_text = read_text_file(file_path)

    except FileLoadError as e:
        # 将文件读取错误转换为文档加载错误 的业务报错，提供更高层次的异常信息
        raise DocumentLoadError(f"文档加载失败: {file_path}") from e

    normalized_text = normalize_text(raw_text)

    if normalized_text == "":
        raise DocumentLoadError(f"文档内容为空: {file_path}")

    try:
        chunks = split_text_by_size(normalized_text, chunk_size=chunk_size)

    except ValueError as e:
        raise DocumentLoadError(f"文档切分失败: {file_path}") from e

    documents: list[Document] = []

    #enumerate 为遍历的每个元素提供索引
    for index, chunk in enumerate(chunks):

        #将chunk内容封装为document对象
        document: Document = {
            "id": f"chunk_{index}",
            "content": chunk,
            "metadata": {
                "source": file_path,
                "chunk_index": index,
            },
        }

        documents.append(document)

    return documents