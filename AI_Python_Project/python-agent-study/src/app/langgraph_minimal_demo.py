import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class DemoState(TypedDict):
    text: str
    result: str


async def upper_node(state: DemoState) -> dict[str, str]:
    text = state["text"]

    upper_text = text.upper()

    return {
        "result": upper_text,
    }


async def main() -> None:
    builder = StateGraph(DemoState)

    builder.add_node("upper", upper_node)

    builder.add_edge(START, "upper")
    builder.add_edge("upper", END)

    graph = builder.compile()

    initial_state: DemoState = {
        "text": "hello langgraph",
        "result": "",
    }

    final_state = await graph.ainvoke(initial_state)

    print("最终状态：")
    print(final_state)


if __name__ == "__main__":
    asyncio.run(main())