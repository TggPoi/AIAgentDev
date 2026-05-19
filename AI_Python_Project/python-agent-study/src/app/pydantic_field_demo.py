from pydantic import BaseModel, Field, ValidationError


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=100,
        description="用户检索问题",
    )


def main() -> None:
    valid_req = SearchRequest(query="什么是 RAG？")
    print(valid_req)

    try:
        SearchRequest(query="")

    except ValidationError as e:
        print("=== 空字符串校验失败 ===")
        print(e)

    try:
        SearchRequest(query="x" * 101)
        
    except ValidationError as e:
        print("=== 超长字符串校验失败 ===")
        print(e)


if __name__ == "__main__":
    main()