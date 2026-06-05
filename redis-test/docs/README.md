# Redis 系统学习路线

这套文档的目标不是让你背命令，而是让你理解 Redis 为什么适合 Agent 开发、每种数据结构解决什么问题、什么时候 Redis 不应该替代数据库，以及如何在 Node.js 项目里把 Redis 用稳。

当前工程已经包含 Redis、RedisInsight、LangChain Agent 记忆示例和一组可运行练习代码。学习时建议同时打开源码和文档，边读边执行命令。

## 学习顺序

1. [01. Redis 必须掌握的知识地图](./01-redis-and-agent-memory.md)
   先建立整体认知：Redis 是什么、为什么快、它和 PostgreSQL 的职责边界是什么、Agent 开发需要掌握哪些 Redis 能力。

2. [02. Redis 基础、Key 设计与 TTL](./02-redis-basics-key-and-ttl.md)
   学会 Redis 的 key-value 模型、命名规范、String、计数器、原子命令、TTL 过期机制。Agent 短期记忆、验证码、缓存、限流都离不开这一章。

3. [03. Redis 数据结构深度学习](./03-redis-data-structures.md)
   系统学习 String、Hash、List、Set、Sorted Set、Bitmap、HyperLogLog、Geo、Stream。重点不是命令数量，而是“什么业务数据应该放进什么结构”。

4. [04. Node.js 使用 ioredis](./04-node-ioredis-code-practice.md)
   学会连接 Redis、序列化 JSON、处理连接错误、使用 Pipeline/Transaction，以及 LangChain 消息对象为什么需要转换后再保存。

5. [05. Agent 开发中的 Redis 记忆系统](./05-redis-for-agent-development.md)
   把 Redis 用到 Agent：短期记忆、会话隔离、工具缓存、限流、锁、任务队列、摘要压缩、Redis 故障降级。

6. [06. Redis 进阶机制与生产实践](./06-redis-production-and-debugging.md)
   学习持久化、内存淘汰、事务、Lua、Pub/Sub、Stream、监控、安全和排错。你不一定马上全用，但必须知道这些机制存在。

## 当前工程源码导航

- [docker-compose.yml](../docker-compose.yml#L1)：Redis 和 RedisInsight 的 Docker 配置。
- [src/agent-with-redis-memory.mjs](../src/agent-with-redis-memory.mjs#L1)：教程中的 Agent 短期记忆示例。
- [src/redis-learning-examples.mjs](../src/redis-learning-examples.mjs#L1)：本套文档配套的 Redis 基础代码案例。
- [Redis：实现 Agent 短期记忆存储的最佳方案.md](../Redis：实现%20Agent%20短期记忆存储的最佳方案.md)：教程原文。
- [redis-data-types.md](../redis-data-types.md)：教程中关于 Redis 数据类型的参考材料。

## 运行环境

启动 Redis：

```powershell
docker compose up -d redis
```

进入 Redis CLI：

```powershell
docker exec -it agent_redis redis-cli
```

打开 RedisInsight：

```text
http://localhost:5540
```

运行 Node.js 示例：

```powershell
pnpm run redis:examples
```

运行 Agent 记忆示例：

```powershell
node src/agent-with-redis-memory.mjs
```

## 学习方法

学习 Redis 时不要只记命令，要追问四个问题：

1. 这个数据应该用什么 Redis 数据结构保存？
2. 这个 key 是否应该设置 TTL？
3. 如果 Redis 重启、key 过期、网络断开，业务是否能接受？
4. 如果多个请求同时操作同一个 key，是否需要原子命令、事务、Lua 或锁？

这四个问题能把“会写 Redis 命令”和“能在 Agent 项目中正确使用 Redis”区分开。

## 学习完成标准

完成这套文档后，你应该能做到：

- 能解释 Redis 为什么快，但也能说出它不是数据库替代品的原因。
- 能根据业务场景选择 String、Hash、List、Set、Sorted Set、Stream。
- 能独立设计 Agent 会话记忆 key，例如 `agent:memory:{sessionId}:messages`。
- 能解释 TTL、缓存失效、短期记忆过期策略。
- 能用 `ioredis` 写出连接、读写、JSON 序列化、Pipeline、事务示例。
- 能解释当前工程里的 `loadMessages` 和 `saveMessages` 为什么要做消息格式转换。
- 能知道 Redis 在 Agent 中还能做缓存、限流、锁和任务队列。
