from pathlib import Path
from typing import Protocol

from fast_app.domain.knowledge_models import LoadedDocument
from fast_app.ingestion.metadata_models import build_document_metadata

# 文档读取层 loader

class BaseDocumentLoader(Protocol):
    def load(self, base_dir: str) -> list[LoadedDocument]:
        pass

# 从知识库目录递归读取 .md 文件 保留 source_path 使用 UTF-8 读取中文 Markdown 返回原始 MarkdownDocument
class MarkdownDocumentLoader:
    def load(self, base_dir: str) -> list[LoadedDocument]:
        root = Path(base_dir)
        documents: list[LoadedDocument] = []

        for path in sorted(root.rglob("*.md")):
            source_path = path.as_posix()
            documents.append(
                LoadedDocument(
                    source_path=source_path,
                    content=path.read_text(encoding="utf-8"),
                    document_type="markdown",
                    metadata=build_document_metadata(
                        source_path=source_path,
                        document_type="markdown",
                    ),
                )
            )

        return documents
    

class TextDocumentLoader:
    def load(self, base_dir: str) -> list[LoadedDocument]:
        root = Path(base_dir)
        documents: list[LoadedDocument] = []

        for path in sorted(root.rglob("*.txt")):
            source_path = path.as_posix()
            documents.append(
                LoadedDocument(
                    source_path=source_path,
                    content=path.read_text(encoding="utf-8"),
                    document_type="text",
                    metadata=build_document_metadata(
                        source_path=source_path,
                        document_type="text",
                    ),
                )
            )

        return documents
    
# 组合 loader
class CompositeDocumentLoader:
    def __init__(self, loaders: list[BaseDocumentLoader]):
        self.loaders = loaders

    def load(self, base_dir: str) -> list[LoadedDocument]:
        documents: list[LoadedDocument] = []

        for loader in self.loaders:
            documents.extend(loader.load(base_dir))

        return documents
    

