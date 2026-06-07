# Mem0 学习文档入口

这组文档基于当前工程代码生成，教程原文不存在，因此已跳过原文阅读。学习顺序从“记忆系统是什么”开始，再进入 Mem0 API、scope 隔离，最后学习 Redis 短期记忆和 Mem0 长期记忆如何组合进 Agent。

## 当前工程先看什么

当前工程里有四类示例：

- 离线机制演示：[src/mem0-learning-offline-demo.mjs](../src/mem0-learning-offline-demo.mjs#L1)。不需要 API Key，用本地数组模拟 add/search/deleteAll 和记忆注入。
- Mem0 云端基础 CRUD：[src/mem0-test.mjs](../src/mem0-test.mjs#L13)。演示 `MemoryClient` 的 `add/search/getAll/get/update/history/deleteAll`。
- Mem0 scope 隔离：[src/mem0-scoped-memory-test.mjs](../src/mem0-scoped-memory-test.mjs#L23)。演示 `userId`、`runId`、`agentId` 三类记忆空间。
- Redis + Mem0 Agent：[src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L364)。演示短期消息历史、长期记忆检索、SystemMessage 注入和分类写回。

## 学习顺序

1. [01. 从 Agent 记忆基础理解 Mem0](./01-mem0-memory-basics.md)
2. [02. Mem0 API、scope 与可运行示例](./02-mem0-api-and-scopes.md)
3. [03. Redis 短期记忆与 Mem0 长期记忆组合进 Agent](./03-redis-mem0-agent-memory.md)

## 本地运行顺序

先运行不依赖外部服务的离线脚本：

```powershell
pnpm.cmd mem0:offline
```

如果 PowerShell 拦截 `pnpm`，使用 `pnpm.cmd`。这不是项目代码问题，而是 Windows 执行策略阻止了 `pnpm.ps1`。

有 `MEM0_API_KEY` 后再运行云端示例：

```powershell
pnpm.cmd mem0:basic
pnpm.cmd mem0:scoped
```

有 `OPENAI_API_KEY`、`MEM0_API_KEY`，并启动 Redis 后，再运行 Agent 示例：

```powershell
docker compose up -d redis
pnpm.cmd agent
```

语法检查：

```powershell
pnpm.cmd check
```
