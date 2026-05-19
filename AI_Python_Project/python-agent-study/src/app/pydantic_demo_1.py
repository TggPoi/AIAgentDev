from pydantic import BaseModel, ValidationError

#`User` 继承了 `BaseModel`
#创建对象时，Pydantic 会根据字段类型执行校验和必要的转换 比普通 class / dataclass 多了运行时数据处理能力
from pydantic import BaseModel


class DocumentMetadata(BaseModel):
    source: str
    chunk_index: int


class Document(BaseModel):
    id: str
    content: str
    metadata: DocumentMetadata


def main() -> None:
    raw_data = {
        "id": "chunk_0",
        "content": "RAG means Retrieval Augmented Generation.",
        "metadata": {
            "source": "data/rag_intro.txt",
            "chunk_index": "0",
        },
    }

    doc = Document.model_validate(raw_data)

    print(doc)
    print(type(doc))
    print(type(doc.metadata.chunk_index))


if __name__ == "__main__":
    main()

# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.pydantic_demo_1
# id='chunk_0' content='RAG means Retrieval Augmented Generation.' metadata=DocumentMetadata(source='data/rag_intro.txt', chunk_index=0)
# <class '__main__.Document'>
# <class 'int'>