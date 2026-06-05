# 03. Redis 数据结构与命令机制详解

上一版文档的问题是：只列了常用命令，但没有说明“执行这条命令后 Redis 里发生了什么”。这一版按学习方式重写：每种数据结构都会讲清楚它保存的数据形态、命令参数、返回值、执行前后变化，以及 Agent 开发中为什么会用它。

配套代码见 [src/redis-learning-examples.mjs](../src/redis-learning-examples.mjs#L1)。

## 0. 学 Redis 命令时要看什么

每条 Redis 命令都建议按 5 个问题理解：

1. 这条命令操作的是哪个 key？
2. 这个 key 的 value 是哪种 Redis 数据结构？
3. 命令参数分别代表什么？
4. 命令执行后，这个 key 里面的数据发生了什么变化？
5. 命令返回值表示什么？

例如：

```redis
HSET agent:task:1001 status running worker worker-01
```

不要只记 `HSET` 是设置 Hash。要拆开看：

```text
命令: HSET
key: agent:task:1001
数据结构: Hash
field/value:
  status -> running
  worker -> worker-01
执行后:
  agent:task:1001 这个 Hash 里多了两个字段
```

这才是真正理解 Redis 命令。

## 1. String

String 是 Redis 最基础的 value 类型。它可以保存普通文本、数字字符串、JSON 字符串、二进制内容。

你可以把 String 理解成：

```text
key -> 一个字符串 value
```

示例：

```text
learn:string -> "hello redis"
learn:counter -> "3"
learn:cache:weather:beijing -> "{\"temp\":20}"
```

### 1.1 SET

命令：

```redis
SET learn:string "hello"
```

作用：给 key 写入一个字符串 value。

执行前：

```text
learn:string 不存在
```

执行后：

```text
learn:string -> "hello"
```

返回值：

```text
OK
```

如果 key 已经存在，`SET` 会覆盖旧值：

```redis
SET learn:string "hello"
SET learn:string "redis"
GET learn:string
```

最终结果：

```text
"redis"
```

也就是说，`SET` 默认不是“追加”，而是“整体替换”。

### 1.2 GET

命令：

```redis
GET learn:string
```

作用：读取 String 类型 key 的 value。

如果 key 存在：

```text
"redis"
```

如果 key 不存在：

```text
(nil)
```

在 Node.js 的 `ioredis` 里，Redis 的 `(nil)` 会变成 JavaScript 的 `null`。

```js
const value = await redis.get("learn:string");
if (value === null) {
  // key 不存在
}
```

### 1.3 DEL

命令：

```redis
DEL learn:string
```

作用：删除 key。

返回值是删除了几个 key：

```text
1
```

如果 key 不存在：

```text
0
```

`DEL` 不关心 value 是 String、Hash、List 还是其他结构。只要 key 存在，就删除整个 key。

### 1.4 SET ... EX

命令：

```redis
SET learn:cache:weather:beijing "{\"temp\":20}" EX 300
```

作用：写入 String，同时设置 300 秒过期。

拆解：

```text
SET                                      写入
learn:cache:weather:beijing              key
"{\"temp\":20}"                          value
EX 300                                   300 秒后过期
```

执行后：

```text
learn:cache:weather:beijing -> "{\"temp\":20}"
TTL = 300 秒左右
```

验证：

```redis
GET learn:cache:weather:beijing
TTL learn:cache:weather:beijing
```

Agent 场景：工具缓存必须有 TTL。天气、搜索、价格、网页内容都可能变化，不能永久缓存。

### 1.5 INCR

命令：

```redis
INCR learn:counter
```

作用：把 String 当成整数，原子加 1。

如果 key 不存在，Redis 会当成 0，然后加 1。

执行前：

```text
learn:counter 不存在
```

执行：

```redis
INCR learn:counter
```

执行后：

```text
learn:counter -> "1"
```

返回值：

```text
1
```

再次执行：

```redis
INCR learn:counter
```

执行后：

```text
learn:counter -> "2"
```

返回值：

```text
2
```

重点：`INCR` 是原子命令。多个请求同时执行时，Redis 会按顺序处理，不会丢失计数。

Agent 场景：

```text
agent:rate_limit:user_001:minute -> "7"
```

每次请求执行一次 `INCR`，就可以统计用户这一分钟调用了多少次 Agent。

### 1.6 DECR

命令：

```redis
DECR learn:counter
```

作用：把整数减 1。

如果当前值是：

```text
learn:counter -> "2"
```

执行后：

```text
learn:counter -> "1"
```

Agent 场景中 `DECR` 没有 `INCR` 常见，但可以用于配额回滚、库存释放等场景。

### 1.7 String 适合和不适合什么

适合：

- 单个值。
- 整体 JSON。
- 缓存结果。
- 计数器。
- 简单锁。

不适合：

- 经常只更新对象里的某一个字段。
- 需要按字段查询。
- 需要保存很长的列表。

如果你经常这样写：

```js
const raw = await redis.get(key);
const obj = JSON.parse(raw);
obj.status = "finished";
await redis.set(key, JSON.stringify(obj));
```

说明你可能更适合用 Hash。

## 2. Hash

Hash 是一个 key 下面保存多个 field-value。

你可以把 Hash 理解成：

```text
key -> {
  field1: value1,
  field2: value2
}
```

示例：

```text
agent:task:1001 -> {
  status: "running",
  worker: "worker-01",
  step: "search_docs"
}
```

### 2.1 HSET

命令：

```redis
HSET agent:task:1001 status running worker worker-01 step search_docs
```

作用：在 Hash 中设置一个或多个字段。

拆解：

```text
HSET                    命令
agent:task:1001         key
status running          field=status, value=running
worker worker-01        field=worker, value=worker-01
step search_docs        field=step, value=search_docs
```

执行前：

```text
agent:task:1001 不存在
```

执行后：

```text
agent:task:1001 -> {
  status: "running",
  worker: "worker-01",
  step: "search_docs"
}
```

返回值：新增了几个 field。

如果原来没有这些 field，可能返回：

```text
3
```

如果再次执行：

```redis
HSET agent:task:1001 status finished
```

执行后：

```text
agent:task:1001 -> {
  status: "finished",
  worker: "worker-01",
  step: "search_docs"
}
```

`status` 被覆盖，其他字段不变。

### 2.2 HGET

命令：

```redis
HGET agent:task:1001 status
```

作用：读取 Hash 中某一个 field。

返回：

```text
"finished"
```

如果 field 不存在：

```text
(nil)
```

Agent 场景：只想知道任务状态时，不需要读取整个对象。

```redis
HGET agent:task:1001 status
```

### 2.3 HGETALL

命令：

```redis
HGETALL agent:task:1001
```

作用：读取整个 Hash 的所有 field-value。

Redis CLI 输出类似：

```text
1) "status"
2) "finished"
3) "worker"
4) "worker-01"
5) "step"
6) "search_docs"
```

在 `ioredis` 中，`hgetall` 会转成对象：

```js
{
  status: "finished",
  worker: "worker-01",
  step: "search_docs"
}
```

注意：Hash 里的 value 仍然是字符串。数字也会以字符串形式返回。

### 2.4 HINCRBY

命令：

```redis
HINCRBY agent:task:1001 retry_count 1
```

作用：把 Hash 中某个字段当成整数，加上指定值。

如果 field 不存在，Redis 会当成 0。

执行前：

```text
agent:task:1001 -> {
  status: "finished"
}
```

执行：

```redis
HINCRBY agent:task:1001 retry_count 1
```

执行后：

```text
agent:task:1001 -> {
  status: "finished",
  retry_count: "1"
}
```

返回值：

```text
1
```

再次执行后返回 `2`。

Agent 场景：记录某个任务重试了几次。

### 2.5 HDEL

命令：

```redis
HDEL agent:task:1001 worker
```

作用：删除 Hash 中的某个 field，不删除整个 key。

执行前：

```text
agent:task:1001 -> {
  status: "finished",
  worker: "worker-01",
  step: "search_docs"
}
```

执行后：

```text
agent:task:1001 -> {
  status: "finished",
  step: "search_docs"
}
```

返回值是删除了几个 field。

### 2.6 Hash 的学习重点

Hash 适合“通过 id 直接读取一个对象”：

```text
agent:run:run_1001
agent:task:task_1001
agent:tool_call:call_1001
```

但 Hash 不能像 PostgreSQL 表一样查询：

```sql
-- Redis Hash 不能这样做
SELECT * FROM tasks WHERE status = 'running';
```

如果你要找出所有 running 任务，需要额外维护 Set 或 Sorted Set。

## 3. List

List 是有顺序的字符串列表。Redis List 有左边和右边。

可以把它想成：

```text
left                                      right
[ "message-1", "message-2", "message-3" ]
```

命令名里：

- `L` 通常表示 left，左边。
- `R` 通常表示 right，右边。

### 3.1 RPUSH

命令：

```redis
RPUSH agent:session:001:messages "user: hello"
```

作用：从右边追加一个元素。

执行前：

```text
agent:session:001:messages 不存在
```

执行后：

```text
[ "user: hello" ]
```

继续执行：

```redis
RPUSH agent:session:001:messages "assistant: hi"
```

执行后：

```text
[ "user: hello", "assistant: hi" ]
```

返回值：List 当前长度。

```text
2
```

Agent 场景：按时间顺序追加聊天消息。

### 3.2 LRANGE

命令：

```redis
LRANGE agent:session:001:messages 0 -1
```

作用：读取 List 指定范围内的元素。

参数：

```text
0   起始下标，表示第一个元素
-1  结束下标，表示最后一个元素
```

如果 List 是：

```text
[ "user: hello", "assistant: hi", "user: explain TTL" ]
```

执行：

```redis
LRANGE agent:session:001:messages 0 -1
```

返回全部元素。

执行：

```redis
LRANGE agent:session:001:messages 0 1
```

返回前两个元素：

```text
[ "user: hello", "assistant: hi" ]
```

执行：

```redis
LRANGE agent:session:001:messages -2 -1
```

返回最后两个元素：

```text
[ "assistant: hi", "user: explain TTL" ]
```

### 3.3 LTRIM

命令：

```redis
LTRIM agent:session:001:messages -20 -1
```

作用：裁剪 List，只保留指定范围内的元素。

`-20 -1` 表示：

```text
保留最后 20 条
```

如果当前 List 有 100 条消息，执行后只剩最后 20 条。

这条命令会修改 Redis 里的数据，不是只读取。

Agent 场景：只保留最近 N 条聊天消息，避免上下文无限增长。

常用组合：

```redis
RPUSH agent:session:001:messages "{\"role\":\"user\",\"content\":\"hello\"}"
LTRIM agent:session:001:messages -20 -1
EXPIRE agent:session:001:messages 1800
```

含义：

1. 追加一条消息。
2. 保留最近 20 条。
3. 设置 30 分钟过期。

### 3.4 LPOP 和 RPOP

命令：

```redis
LPOP agent:queue:jobs
RPOP agent:queue:jobs
```

作用：

- `LPOP`：从左边弹出一个元素。
- `RPOP`：从右边弹出一个元素。

弹出表示：返回这个元素，并把它从 List 删除。

示例 List：

```text
[ "job-1", "job-2", "job-3" ]
```

执行：

```redis
LPOP agent:queue:jobs
```

返回：

```text
"job-1"
```

List 变成：

```text
[ "job-2", "job-3" ]
```

执行：

```redis
RPOP agent:queue:jobs
```

返回：

```text
"job-3"
```

List 变成：

```text
[ "job-2" ]
```

队列方向要自己设计清楚。例如：

```text
LPUSH 写入 + RPOP 读取 = FIFO 队列
RPUSH 写入 + LPOP 读取 = FIFO 队列
RPUSH 写入 + RPOP 读取 = 栈，后进先出
```

## 4. Set

Set 是不重复集合。它只关心“某个成员是否存在”，不关心顺序。

可以理解成：

```text
agent:seen_urls:run_1001 -> {
  "https://example.com/a",
  "https://example.com/b"
}
```

### 4.1 SADD

命令：

```redis
SADD agent:seen_urls:run_1001 https://example.com/a https://example.com/b https://example.com/a
```

作用：向 Set 添加成员。

注意：`https://example.com/a` 出现了两次，但 Set 不会重复保存。

执行后：

```text
agent:seen_urls:run_1001 -> {
  "https://example.com/a",
  "https://example.com/b"
}
```

返回值：新增了几个成员。

这里返回：

```text
2
```

因为第三个 `a` 是重复的，没有新增。

Agent 场景：网页抓取或搜索时，记录已经访问过的 URL，避免重复处理。

### 4.2 SMEMBERS

命令：

```redis
SMEMBERS agent:seen_urls:run_1001
```

作用：返回 Set 中所有成员。

返回示例：

```text
1) "https://example.com/a"
2) "https://example.com/b"
```

注意：Set 没有顺序，不要依赖返回顺序。

### 4.3 SISMEMBER

命令：

```redis
SISMEMBER agent:seen_urls:run_1001 https://example.com/a
```

作用：判断某个成员是否在 Set 中。

返回值：

```text
1  表示存在
0  表示不存在
```

Agent 场景：

```text
如果 URL 已处理过，就跳过
如果没处理过，就抓取并 SADD
```

### 4.4 SREM

命令：

```redis
SREM agent:seen_urls:run_1001 https://example.com/a
```

作用：从 Set 删除成员。

返回值：删除了几个成员。

### 4.5 SCARD

命令：

```redis
SCARD agent:seen_urls:run_1001
```

作用：返回 Set 的成员数量。

如果 Set 里有两个 URL：

```text
2
```

Agent 场景：统计当前 run 已经访问了多少个 URL。

### 4.6 SINTER、SUNION、SDIFF

Set 可以做集合运算。

准备数据：

```redis
SADD user:001:permissions read_docs call_tools export_report
SADD required:tool:search read_docs call_tools
```

#### SINTER

```redis
SINTER user:001:permissions required:tool:search
```

作用：求交集，也就是两个 Set 都有的成员。

结果：

```text
read_docs
call_tools
```

#### SUNION

```redis
SUNION user:001:permissions required:tool:search
```

作用：求并集，也就是两个 Set 合起来的所有成员，自动去重。

#### SDIFF

```redis
SDIFF required:tool:search user:001:permissions
```

作用：求差集。这里表示“工具要求但用户没有的权限”。

如果返回空，说明用户具备全部所需权限。

## 5. Sorted Set

Sorted Set 也叫 ZSet。它是“成员不重复 + 每个成员有一个 score”的集合。

可以理解为：

```text
agent:priority_queue -> {
  "task-low": 10,
  "task-high": 100
}
```

Redis 会根据 score 排序。

### 5.1 ZADD

命令：

```redis
ZADD agent:priority_queue 100 task-high 10 task-low
```

作用：向 Sorted Set 添加成员和分数。

拆解：

```text
key: agent:priority_queue
member: task-high, score: 100
member: task-low, score: 10
```

执行后：

```text
task-low   -> 10
task-high  -> 100
```

返回值：新增成员数量。

如果再次执行：

```redis
ZADD agent:priority_queue 200 task-high
```

不是新增一个 `task-high`，而是更新它的 score：

```text
task-low   -> 10
task-high  -> 200
```

### 5.2 ZRANGE

命令：

```redis
ZRANGE agent:priority_queue 0 -1 WITHSCORES
```

作用：按 score 从小到大读取成员。

如果数据是：

```text
task-low   -> 10
task-high  -> 200
```

返回：

```text
1) "task-low"
2) "10"
3) "task-high"
4) "200"
```

`WITHSCORES` 表示返回成员时同时返回 score。

### 5.3 ZREVRANGE

命令：

```redis
ZREVRANGE agent:priority_queue 0 -1 WITHSCORES
```

作用：按 score 从大到小读取成员。

返回：

```text
1) "task-high"
2) "200"
3) "task-low"
4) "10"
```

Agent 场景：优先处理 score 高的任务。

### 5.4 ZPOPMAX

命令：

```redis
ZPOPMAX agent:priority_queue
```

作用：取出 score 最大的成员，并从 Sorted Set 中删除它。

如果执行前：

```text
task-low   -> 10
task-high  -> 200
```

执行后返回：

```text
task-high
200
```

Sorted Set 变成：

```text
task-low -> 10
```

注意：`ZPOPMAX` 是“读取 + 删除”。适合做优先级队列。

### 5.5 ZPOPMIN

命令：

```redis
ZPOPMIN agent:priority_queue
```

作用：取出 score 最小的成员，并删除它。

**如果 score 表示“执行时间戳”，越小表示越早到期，这时可以用 `ZPOPMIN` 或 `ZRANGEBYSCORE` 做延迟任务。**

### 5.6 ZRANGEBYSCORE

命令：

```redis
ZRANGEBYSCORE agent:tasks:delayed -inf 1717400000
```

作用：读取 score 在某个范围内的成员。

参数：

```text
-inf        负无穷，表示最小 score
1717400000 结束 score
```

Agent 场景：延迟任务。

```text
score = 任务应该执行的 Unix 时间戳
member = task id
```

**Worker 定期查询：**

```text
找出 score <= 当前时间 的任务
```

## 6. Bitmap

Bitmap 用 bit 保存大量布尔值。它**底层仍然是 String**，但你通过 bit 位操作它。

可以理解成：

```text
offset: 0 1 2 3 4 5
value:  0 0 0 1 0 0
```

每个 offset 只能是 0 或 1。

### 6.1 SETBIT

命令：

```redis
SETBIT user:sign:2026-06 3 1
```

作用：把某个 bit 位置设置为 1。

拆解：

```text
key: user:sign:2026-06
offset: 3
value: 1
```

可以理解为：用户在第 4 天签到。因为 offset 从 0 开始，offset 3 对应第 4 个位置。

返回值：这个 bit 修改前的旧值。

### 6.2 GETBIT

命令：

```redis
GETBIT user:sign:2026-06 3
```

作用：读取 offset 3 的 bit。

返回：

```text
1
```

表示这个位置为 true。

### 6.3 BITCOUNT

命令：

```redis
BITCOUNT user:sign:2026-06
```

作用：统计这个 Bitmap 中有多少个 bit 是 1。

Agent 场景不是很多，但可以用来记录大规模布尔状态，例如某批文档是否处理过。

## 7. HyperLogLog

HyperLogLog 用于**近似统计“去重后的数量”**。它不保存完整成员列表，只保存用于估算基数的数据结构。

### 7.1 PFADD

命令：

```redis
PFADD agent:uv:2026-06-04 user-1 user-2 user-1
```

作用：向 HyperLogLog 中加入元素。

虽然 `user-1` 出现两次，但它只影响去重统计一次。

返回值：内部结构是否发生变化。不要把返回值理解为新增用户数量。

### 7.2 PFCOUNT

命令：

```redis
PFCOUNT agent:uv:2026-06-04
```

作用：返回近似去重数量。

在这个例子里通常返回：

```text
2
```

但 HyperLogLog 是近似算法，数据量很大时可能有小误差。

适合：

- 每天多少独立用户使用 Agent。
- 多少独立 session 调用了某个工具。

不适合：

- 要列出具体用户。
- 要严格精确计数。

如果你需要具体成员列表，用 Set；如果只需要大规模近似数量，用 HyperLogLog。

## 8. Geo

Geo 用于地理位置。Redis Geo 底层基于 Sorted Set，但你通常通过 Geo 命令使用它。

### 8.1 GEOADD

命令：

```redis
GEOADD stores 116.397128 39.916527 beijing-store
```

作用：添加一个地理位置。

参数顺序非常重要：

```text
经度 longitude: 116.397128
纬度 latitude:  39.916527
成员 member:    beijing-store
```

不要把经纬度顺序写反。

### 8.2 GEODIST

命令：

```redis
GEODIST stores beijing-store another-store km
```

作用：计算两个成员之间的距离。

`km` 表示单位是公里。

### 8.3 GEOSEARCH

命令：

```redis
GEOSEARCH stores FROMLONLAT 116.40 39.90 BYRADIUS 5 km
```

作用：从指定经纬度出发，查找半径 5 公里内的成员。

Agent 场景：

- 附近门店查询。
- 附近设备查询。
- 附近服务点推荐。

如果你的 Agent 不涉及位置服务，Geo 可以先了解，不必优先深入。

## 9. Stream

Stream 是 Redis 的追加日志结构。你可以把它理解为有 id 的事件列表。

```text
agent:events:
  1717400000000-0 -> { type: "tool_called", session_id: "session-001", tool: "search" }
  1717400001000-0 -> { type: "tool_finished", session_id: "session-001", tool: "search" }
```

它比 List 更适合可靠事件流，因为 Stream 支持消费组、确认和未确认消息追踪。

### 9.1 XADD

命令：

```redis
XADD agent:events * type tool_called session_id session-001 tool search
```

作用：向 Stream 追加一条事件。

拆解：

```text
XADD             命令
agent:events     Stream key
*                让 Redis 自动生成消息 id
type tool_called field/value
session_id ...   field/value
tool search      field/value
```

返回值：新消息 id。

示例：

```text
1717400000000-0
```

这个 id 大致由时间戳和序号组成。

### 9.2 XRANGE

命令：

```redis
XRANGE agent:events - +
```

作用：按 id 范围读取 Stream 消息。

参数：

```text
-   最小 id
+   最大 id
```

所以 `- +` 表示读取全部消息。

返回结构包含：

```text
消息 id
field/value 列表
```

### 9.3 XLEN

命令：

```redis
XLEN agent:events
```

作用：返回 Stream 中有多少条消息。

### 9.4 XGROUP CREATE

命令：

```redis
XGROUP CREATE agent:events workers $ MKSTREAM
```

作用：给 Stream 创建消费组。

拆解：

```text
agent:events  Stream key
workers       消费组名称
$             从当前最新位置开始消费
MKSTREAM      如果 Stream 不存在，就创建
```

消费组可以让多个 worker 协同处理同一个 Stream。

### 9.5 XREADGROUP

命令：

```redis
XREADGROUP GROUP workers worker-1 COUNT 10 STREAMS agent:events >
```

作用：以消费组方式读取消息。

拆解：

```text
GROUP workers worker-1   消费组 workers，消费者 worker-1
COUNT 10                 最多读取 10 条
STREAMS agent:events >   从未投递给该组的新消息中读取
```

`>` 表示读取新的、还没有投递给这个消费组的消息。

### 9.6 XACK

命令：

```redis
XACK agent:events workers 1717400000000-0
```

作用：确认某条消息已经被消费组处理完成。

如果不 `XACK`，这条消息会留在 pending 状态。之后可以排查或重新分配。

Agent 场景：

- 文档解析任务。
- 工具调用事件。
- 后台 embedding 队列。
- 多 worker 异步处理任务。

## 10. 数据结构选择表

| 需求 | 推荐结构 | 为什么 |
| --- | --- | --- |
| 保存整个 JSON 缓存 | String | 整体读写简单 |
| 保存任务对象字段 | Hash | 可以只更新一个字段 |
| 保存最近 N 条消息 | List | 有顺序，可裁剪 |
| URL 去重 | Set | 自动去重，判断存在快 |
| 优先级任务 | Sorted Set | score 表示优先级 |
| 延迟任务 | Sorted Set | score 表示执行时间 |
| 大量布尔状态 | Bitmap | 省内存 |
| 大规模 UV 统计 | HyperLogLog | 省内存近似计数 |
| 可靠事件流 | Stream | 支持消费组和确认 |

## 11. 从命令执行结果反推数据变化

你可以用下面这些命令检查 Redis 里的 key：

```redis
TYPE key
TTL key
MEMORY USAGE key
```

不同类型用不同读取命令：

| 类型 | 读取命令 |
| --- | --- |
| String | `GET key` |
| Hash | `HGETALL key` |
| List | `LRANGE key 0 -1` |
| Set | `SMEMBERS key` |
| Sorted Set | `ZRANGE key 0 -1 WITHSCORES` |
| Stream | `XRANGE key - +` |

不要看到一个 key 就直接 `GET`。如果它是 Hash、List、Set，`GET` 会报类型错误。

## 12. 本章练习：执行并解释每一步

进入 Redis CLI：

```powershell
docker exec -it agent_redis redis-cli
```

执行：

```redis
DEL learn:task:1001 learn:session:001:messages learn:seen_urls:1001 learn:priority

HSET learn:task:1001 status running step search_docs retry_count 0
HINCRBY learn:task:1001 retry_count 1
HGETALL learn:task:1001

RPUSH learn:session:001:messages "user: hello"
RPUSH learn:session:001:messages "assistant: hi"
LTRIM learn:session:001:messages -2 -1
LRANGE learn:session:001:messages 0 -1

SADD learn:seen_urls:1001 https://a.com https://b.com https://a.com
SCARD learn:seen_urls:1001
SISMEMBER learn:seen_urls:1001 https://a.com

ZADD learn:priority 10 normal_task 100 urgent_task
ZRANGE learn:priority 0 -1 WITHSCORES
ZPOPMAX learn:priority
ZRANGE learn:priority 0 -1 WITHSCORES
```

你要能解释：

1. `HSET` 后 `learn:task:1001` 变成了什么结构？
2. `HINCRBY` 为什么能把 `retry_count` 从 `0` 变成 `1`？
3. `RPUSH` 为什么会把消息放到列表右边？
4. `LTRIM -2 -1` 为什么是保留最后两条？
5. `SADD` 重复添加 `https://a.com` 为什么只算一个？
6. `ZPOPMAX` 为什么执行后 `urgent_task` 会从集合中消失？

## 13. 本章完成标准

学完本章，不要求你背所有命令，但要求你能做到：

1. 看到一条 Redis 命令，能说出它操作的 key 和数据结构。
2. 能解释命令参数的意义。
3. 能说出命令执行后 Redis 里的数据发生了什么变化。
4. 能根据业务场景选择 String、Hash、List、Set、Sorted Set 或 Stream。
5. 能区分“读取命令”和“会修改数据的命令”。
6. 能解释为什么 Agent 记忆、缓存、限流、锁、队列需要不同的数据结构。
