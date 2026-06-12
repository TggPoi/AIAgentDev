import httpx


def main() -> None:
    url = "https://httpbin.org/post"

    payload = {
        "query": "什么是混合检索？",
        "documents": [
            "混合检索结合向量检索和关键词检索。",
            "FastAPI 是一个 Python Web 框架。",
        ],
    }

    response = httpx.post(
        url,
        json=payload,#把 Python dict 序列化成 JSON 字符串 设置请求体为 JSON
        headers={
            "Content-Type": "application/json",
        },
        timeout=10.0,
    )

    print("status_code:", response.status_code)

    data = response.json()

    print("server received json:")
    print(data["json"])


if __name__ == "__main__":
    main()