# 06. Redis 进阶机制与生产实践

这一章学习 Redis 的进阶机制。你不一定马上在当前工程中全部使用，但如果要把 Redis 用在真实 Agent 服务中，必须知道这些机制的作用和边界。

## 1. 持久化：RDB 和 AOF

Redis 的主要数据在内存中。为了重启后恢复数据，Redis 提供持久化机制。

当前工程在 [docker-compose.yml](../docker-compose.yml#L10) 中使用：

```yaml
command: redis-server --appendonly yes
```

这表示开启 AOF。

### 1.1 RDB

RDB 是快照持久化。Redis 会在某些时间点把内存数据生成快照文件。

优点：

- 文件紧凑。
- 恢复速度通常较快。
- 适合备份。

缺点：

- 两次快照之间的数据可能丢失。
- 生成快照时会有额外开销。

### 1.2 AOF

AOF 是 Append Only File。Redis 会把写命令追加到日志文件。

优点：

- 数据丢失窗口更小。
- 日志更接近“每次写入”的记录。

缺点：

- 文件可能更大。
- 需要 rewrite 压缩。
- 写入磁盘会带来额外开销。

### 1.3 Agent 场景怎么选

| 数据 | 是否需要 Redis 持久化 |
| --- | --- |
| 短期对话记忆 | 不一定，过期即可 |
| 限流计数器 | 不需要 |
| 临时锁 | 不需要 |
| 工具缓存 | 不需要 |
| 任务队列 | 如果只用 Redis 承载任务，最好需要 |
| 事件日志 | 如果 Redis 是唯一来源，需要 |

如果数据非常重要，最好最终写入 PostgreSQL 或其他持久化系统，不要只依赖 Redis 内存和 AOF。

## 2. 内存淘汰策略

Redis 内存不是无限的。当达到 `maxmemory` 后，Redis 会根据策略处理 key。

常见策略：

| 策略 | 含义 |
| --- | --- |
| `noeviction` | 不淘汰，写入报错 |
| `allkeys-lru` | 从所有 key 中淘汰最近最少使用 |
| `volatile-lru` | 只从设置了 TTL 的 key 中淘汰最近最少使用 |
| `allkeys-random` | 从所有 key 中随机淘汰 |
| `volatile-ttl` | 优先淘汰 TTL 更短的 key |
| `allkeys-lfu` | 淘汰低频访问 key |

查看配置：

```redis
CONFIG GET maxmemory
CONFIG GET maxmemory-policy
```

Agent 项目中，如果 Redis 存大量短期记忆和缓存，必须关注：

- key 是否都设置了 TTL。
- 每个 value 是否过大。
- Redis 内存是否持续增长。
- 淘汰策略是否可能删除你不能丢的数据。

## 3. 大 key 问题

大 key 是 Redis 常见性能问题。

示例：

```text
agent:short_memory:session_001:messages
```

如果你一直把所有历史消息追加进一个 JSON String，这个 value 会越来越大。

问题：

- `GET` 一次返回大量数据。
- `SET` 每次重写整个大字符串。
- 网络传输变慢。
- 序列化和反序列化变慢。
- 可能阻塞 Redis。

缓解方式：

- 给短期记忆设置合理 TTL。
- 使用摘要压缩。
- 只保留最近 N 条消息。
- 改用 List 按消息保存，并 `LTRIM`。
- 长期内容落 PostgreSQL。

## 4. Pipeline 和 Transaction 的边界

Pipeline 解决网络往返，不解决一致性。

```js
const pipeline = redis.pipeline();
pipeline.get("k1");
pipeline.get("k2");
const results = await pipeline.exec();
```

Transaction 让多条命令在 `EXEC` 时连续执行：

```js
await redis
  .multi()
  .set("k1", "v1")
  .set("k2", "v2")
  .exec();
```

区别：

| 能力 | Pipeline | Transaction |
| --- | --- | --- |
| 减少网络往返 | 是 | 是 |
| 命令排队一起发送 | 是 | 是 |
| `EXEC` 时连续执行 | 否 | 是 |
| PostgreSQL 式回滚 | 否 | 否 |

如果你只是批量读写，用 Pipeline。如果你希望多条命令在 Redis 中连续执行，用 Transaction。如果你需要复杂判断和原子更新，用 Lua。

## 5. Lua 脚本

Redis 单条命令是原子的，但多条命令组合不一定原子。

例如释放锁的错误写法：

```js
await redis.del(lockKey);
```

如果锁已经过期并被别人获得，这会删掉别人的锁。

正确思路：只有 value 还是自己写入的随机值时，才删除。

Lua：

```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
else
  return 0
end
```

ioredis 调用：

```js
await redis.eval(
  `
  if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
  else
    return 0
  end
  `,
  1,
  lockKey,
  lockValue,
);
```

Lua 常见用途：

- 释放锁。
- 滑动窗口限流。
- 库存扣减。
- 多 key 状态一致更新。

## 6. Pub/Sub

Pub/Sub 是发布订阅。

订阅：

```redis
SUBSCRIBE agent:events
```

发布：

```redis
PUBLISH agent:events "tool finished"
```

特点：

- 实时。
- 不保存历史消息。
- 订阅者不在线就收不到。

适合：

- 在线通知。
- 调试广播。
- 非关键实时事件。

不适合：

- 可靠任务队列。
- 必须保证处理的事件。

## 7. Stream

Stream 更像可持久化事件日志。

写入事件：

```redis
XADD agent:events * type tool_called session_id session-001 tool search
```

读取：

```redis
XRANGE agent:events - +
```

创建消费组：

```redis
XGROUP CREATE agent:events workers $ MKSTREAM
```

消费：

```redis
XREADGROUP GROUP workers worker-1 COUNT 10 STREAMS agent:events >
```

确认：

```redis
XACK agent:events workers 1717400000000-0
```

Stream 适合 Agent 的异步任务和事件流水线，因为它可以支持：

- 多 worker 消费。
- 消息确认。
- 未确认消息排查。
- 事件回放。

## 8. 缓存一致性

Redis 经常作为缓存，但缓存会带来一致性问题。

常见模式：

### 8.1 Cache Aside

读取流程：

```text
先读 Redis
  有 -> 返回
  没有 -> 读数据库 -> 写 Redis -> 返回
```

写入流程：

```text
先写数据库
再删除 Redis 缓存
```

为什么通常是删除缓存，而不是直接更新缓存？

因为数据库写入和缓存更新之间可能出现并发顺序问题。删除缓存可以让下一次读取重新从数据库加载。

### 8.2 缓存穿透

查询一个根本不存在的数据，每次都打到数据库。

缓解：

- 缓存空值，设置短 TTL。
- 参数校验。
- Bloom Filter。

### 8.3 缓存击穿

一个热点 key 过期，大量请求同时打到数据库或外部工具。

缓解：

- 加互斥锁。
- 热点 key 提前刷新。
- 使用较长 TTL 加后台更新。

### 8.4 缓存雪崩

大量 key 同时过期。

缓解：

- TTL 加随机抖动。
- 分批预热。
- 限流和降级。

Agent 工具缓存也会遇到这些问题，尤其是搜索、天气、价格、数据库查询这类工具。

## 9. 观测和排错命令

查看 Redis 是否正常：

```redis
PING
INFO server
INFO memory
INFO clients
```

查看 key：

```redis
SCAN 0 MATCH agent:* COUNT 20
TYPE agent:short_memory:demo_user_001:messages
TTL agent:short_memory:demo_user_001:messages
MEMORY USAGE agent:short_memory:demo_user_001:messages
```

查看慢命令：

```redis
SLOWLOG GET 10
```

查看客户端连接：

```redis
CLIENT LIST
```

调试某个 key 的基本顺序：

```text
1. TYPE key
2. TTL key
3. MEMORY USAGE key
4. 根据 TYPE 使用 GET/HGETALL/LRANGE/SMEMBERS/ZRANGE
```

## 10. 安全和配置

学习环境可以直接暴露本地端口，但生产环境要注意：

- Redis 不应该暴露到公网。
- 应该配置认证。
- 应该限制网络访问来源。
- 应该为不同环境使用不同前缀或不同 DB。
- 敏感数据不要长期存 Redis。
- Agent 记忆可能包含用户隐私，必须设置清理策略。

当前工程是本地学习项目，所以重点是理解机制，不是生产安全配置。

## 11. 本章完成标准

学完本章，你应该能回答：

1. RDB 和 AOF 的区别是什么？
2. 为什么短期记忆不一定需要强持久化？
3. Redis 内存满了以后会发生什么？
4. 什么是大 key，Agent 记忆为什么容易形成大 key？
5. Pipeline、Transaction、Lua 分别解决什么问题？
6. Pub/Sub 和 Stream 的区别是什么？
7. 缓存穿透、击穿、雪崩分别是什么？
8. 排查 Redis key 时应该先看哪些信息？
