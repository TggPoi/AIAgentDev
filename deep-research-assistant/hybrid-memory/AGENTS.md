# 混合流水线 Memory

这是一份只供 `StateGraph + createDeepAgent` 学习示例使用的只读 memory。

## 固定原则

1. 每个阶段只完成外层 StateGraph 分配的当前任务。
2. 不要跳过 Editor 审阅。
3. 不要修改本 memory。
4. 不要扩展用户问题。
5. 仅将阶段产物写入任务明确指定的路径。
