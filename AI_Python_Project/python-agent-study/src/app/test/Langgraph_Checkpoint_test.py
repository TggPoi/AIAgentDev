from typing_extensions import NotRequired, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class DocumentState(TypedDict):
    topic: str
    research_notes: NotRequired[str]
    draft: NotRequired[str]


def researcher(state: DocumentState) -> dict:
    print("执行 Researcher")

    return {
        "research_notes": f"已经收集关于《{state['topic']}》的资料"
    }


def writer(state: DocumentState) -> dict:
    print("执行 Writer")

    return {
        "draft": (
            f"主题：{state['topic']}\n"
            f"参考资料：{state['research_notes']}\n"
            "这是生成的文档草稿。"
        )
    }


# 1. 构建图
builder = StateGraph(DocumentState)

builder.add_node("researcher", researcher)
builder.add_node("writer", writer)

builder.add_edge(START, "researcher")
builder.add_edge("researcher", "writer")
builder.add_edge("writer", END)


# 2. 创建内存 Checkpointer
checkpointer = InMemorySaver()


# 3. 编译图时注入 Checkpointer
graph = builder.compile(
    checkpointer=checkpointer,
)


# 4. 为当前任务设置稳定的 thread_id
config = {
    "configurable": {
        "thread_id": "document:task-001"
    }
}


# 5. 首次执行
result = graph.invoke(
    {
        "topic": "RAG权限系统",
    },
    config=config,
)

print("\n最终结果：")
print(result)


# 6. 查询该线程的最新 Checkpoint
latest_state = graph.get_state(config)

print("\n最新 State：")
print(latest_state.values)

print("\n下一步节点：")
print(latest_state.next)

print("\n最新 checkpoint_id：")
print(
    latest_state.config["configurable"]["checkpoint_id"]
)


# 7. 查询该线程的完整 Checkpoint 历史
history = list(graph.get_state_history(config))

print("\nCheckpoint 历史：")

for snapshot in history:
    print("-" * 60)
    print("step:", snapshot.metadata["step"])
    print("values:", snapshot.values)
    print("next:", snapshot.next)
    print(
        "checkpoint_id:",
        snapshot.config["configurable"]["checkpoint_id"],
    )


# 8. 找到 Writer 执行之前的 Checkpoint
before_writer = next(
    snapshot
    for snapshot in history
    if snapshot.next == ("writer",)
)

print("\n从 Writer 之前的 Checkpoint 重新执行：")

replay_result = graph.invoke(
    None,
    config=before_writer.config,
)

print(replay_result)