import httpx


def main() -> None:
    url = "https://httpbin.org/status/401"

    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()

        data = response.json()
        print(data)

    except httpx.HTTPStatusError as exc:
        print("HTTP 状态码错误")
        print("status_code:", exc.response.status_code)
        print("response_text:", exc.response.text)

    except httpx.RequestError as exc:
        print("请求发送失败或网络错误")
        print("error:", repr(exc))


if __name__ == "__main__":
    main()