import httpx


def main() -> None:
    url = "https://httpbin.org/get"

    response = httpx.get(
        url,
        params={
            "query": "hello",
            "page": 1,
        },
        timeout=10.0,
    )

    print("status_code:", response.status_code)
    print("text:", response.text[:200])

    data = response.json()
    print("json args:", data["args"])


if __name__ == "__main__":
    main()



# status_code: 200
# text: {
#   "args": {
#     "page": "1", 
#     "query": "hello"
#   }, 
#   "headers": {
#     "Accept": "*/*", 
#     "Accept-Encoding": "gzip, deflate, zstd", 
#     "Host": "httpbin.org", 
#     "User-Agent": "python-htt
# json args: {'page': '1', 'query': 'hello'}
