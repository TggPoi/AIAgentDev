from pydantic import ValidationError

from app.schemas.document_model import Document, DocumentMetadata
from app.services.text_splitter import split_text_by_size
from app.utils.file_utils import FileLoadError, read_text_file
from app.utils.text_utils import normalize_text


class DocumentLoadError(Exception):
    pass


def load_and_split_text_file_model(
    file_path: str,
    chunk_size: int = 200,
) -> list[Document]:
    try:
        raw_text = read_text_file(file_path)
    except FileLoadError as e:
        raise DocumentLoadError(f"文档加载失败: {file_path}") from e

    normalized_text = normalize_text(raw_text)

    if normalized_text == "":
        raise DocumentLoadError(f"文档内容为空: {file_path}")

    try:
        chunks = split_text_by_size(normalized_text, chunk_size=chunk_size)
    except ValueError as e:
        raise DocumentLoadError(f"文档切分失败: {file_path}") from e

    documents: list[Document] = []

    for index, chunk in enumerate(chunks):
        try:
            document = Document(
                id=f"chunk_{index}",
                content=chunk,
                metadata=DocumentMetadata(
                    source=file_path,
                    chunk_index=index,
                ),
            )
        except ValidationError as e:
            raise DocumentLoadError(f"Document 数据结构校验失败: {file_path}") from e

        documents.append(document)

    return documents