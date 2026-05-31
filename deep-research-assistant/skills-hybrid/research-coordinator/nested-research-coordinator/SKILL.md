---
name: nested-research-coordinator
description: 在混合流水线的 research 阶段并行委派两个受控子 Agent 并合并结果
---

# 嵌套调研协调

你只负责协调和合并，不要自行联网搜索。

## 步骤

1. 读取任务指定的问题文件。
2. 在同一轮中发出两个 `task` 工具调用，使它们并行执行：
   - `scenario_researcher`：调研适用场景，写入任务指定文件。
   - `limits_researcher`：调研限制和采用建议，写入任务指定文件。
3. 等待两个子 Agent 完成。
4. 读取两个子 Agent 写入的文件。
5. 将合并结果写入任务指定的汇总 `findings` 文件。
6. 用一句话确认完成并立即停止。

## 限制

- 必须调用两个 `task`，每种子 Agent 只调用一次。
- 不要调用第三次 `task`。
- 汇总文件控制在 900 字以内。
- 不要创建任务未指定的文件。
