
import asyncio

# 只是创建了一个协程对象，并没有真正执行里面的代码逻辑
async def fetch_data() -> str:
    print("fetch_data is running")
    return "data"


async def main() -> None:
    result = await fetch_data()
    print(result)


if __name__ == "__main__":
    asyncio.run(main())


# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.async_demo_1
# <coroutine object fetch_data at 0x000002A09AE25000>
# D:\AI_Agent_Project\AI_Python_Project\python-agent-study\src\app\async_demo_1.py:12: RuntimeWarning: coroutine 'fetch_data' was never awaited
#   main()
# RuntimeWarning: Enable tracemalloc to get the object allocation traceback