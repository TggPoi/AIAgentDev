// 加载 .env 文件中的环境变量，例如 REDIS_HOST、REDIS_PORT、REDIS_DB。
// 这个示例脚本默认连接本机 Docker 暴露出来的 Redis: localhost:6379。
import "dotenv/config";
import crypto from "node:crypto";
import Redis from "ioredis";

// 创建 Redis 客户端连接对象。
// 注意：redis 变量不是 Redis 数据库本身，而是 Node.js 进程连接 Redis server 的客户端。
// 后面的 redis.get / redis.set / redis.hset 等方法都会通过网络把命令发送给 Redis server。
const redis = new Redis({
  host: process.env.REDIS_HOST ?? "localhost",
  port: Number(process.env.REDIS_PORT ?? 6379),
  db: Number(process.env.REDIS_DB ?? 0),
});

// connect 事件表示客户端已经连上 Redis server。
redis.on("connect", () => {
  console.log("Redis connected");
});

// error 事件用于观察连接失败、认证失败、网络断开等问题。
// 学习 Redis 时建议保留这个监听，否则连接错误可能不明显。
redis.on("error", (error) => {
  console.error("Redis error:", error.message);
});

// 所有学习用 key 都加上统一前缀，避免误删或覆盖其他业务数据。
// 运行结束后，你可以在 redis-cli 中用 SCAN 0 MATCH learn:redis:* COUNT 100 查看这些 key。
const prefix = "learn:redis";

// 示例 key 统一设置 10 分钟过期，避免学习数据永久留在 Redis。
const ttlSeconds = 600;

// 把所有示例 key 集中管理，避免在不同函数里手写字符串导致拼写不一致。
// Redis 本身没有“表”的概念，所以 key 命名就是你的逻辑数据边界。
const keys = {
  string: `${prefix}:string`,
  json: `${prefix}:json`,
  counter: `${prefix}:counter`,
  hash: `${prefix}:hash:task:1001`,
  list: `${prefix}:list:session:001:messages`,
  set: `${prefix}:set:seen_urls:run_1001`,
  zset: `${prefix}:zset:priority_tasks`,
  pipelineA: `${prefix}:pipeline:a`,
  pipelineB: `${prefix}:pipeline:b`,
  txA: `${prefix}:tx:a`,
  txCounter: `${prefix}:tx:counter`,
  stream: `${prefix}:stream:events`,
  lock: `${prefix}:lock:session:001`,
};

async function resetDemoKeys() {
  // DEL 会删除整个 key，不关心 key 里面保存的是 String、Hash、List 还是其他结构。
  // 这里在每次运行前清空旧数据，保证你每次看到的输出都是从干净状态开始。
  await redis.del(...Object.values(keys));
}

async function setTtlForDemoKeys(...selectedKeys) {
  // Pipeline 用于批量发送命令，减少多次网络往返。
  // 这里给多个 key 设置 TTL，不需要每个 expire 都单独 await 一次。
  const pipeline = redis.pipeline();

  for (const key of selectedKeys) {
    // EXPIRE key seconds：给已经存在的 key 设置过期时间。
    pipeline.expire(key, ttlSeconds);
  }

  // exec 会把 pipeline 中排队的命令发送给 Redis。
  await pipeline.exec();
}

async function demoStringAndTtl() {
  console.log("\n1. String + TTL");

  // SET key value EX seconds：
  // - key 是 keys.string，也就是 learn:redis:string。
  // - value 是 "hello redis"。
  // - EX ttlSeconds 表示这个 key 会在 ttlSeconds 秒后自动过期。
  // 执行后 Redis 中的数据形态是：learn:redis:string -> "hello redis"。
  await redis.set(keys.string, "hello redis", "EX", ttlSeconds);

  // GET 读取 String 类型 key 的值。
  console.log("GET =", await redis.get(keys.string));

  // TTL 查看 key 还剩多少秒过期。
  // 返回正整数表示剩余秒数，-1 表示 key 存在但没有过期时间，-2 表示 key 不存在。
  console.log("TTL =", await redis.ttl(keys.string));
}

async function demoJsonString() {
  console.log("\n2. JSON stored as String");

  // Redis 不直接保存 JavaScript 对象。
  // 如果要把对象放进 Redis String，需要先 JSON.stringify 成字符串。
  const toolResult = {
    tool: "weather",
    input: { city: "beijing" },
    output: { temperature: 20, unit: "celsius" },
  };

  // 这里模拟 Agent 工具结果缓存：
  // key:   learn:redis:json
  // value: {"tool":"weather","input":...,"output":...}
  // ttl:   10 分钟
  await redis.set(keys.json, JSON.stringify(toolResult), "EX", ttlSeconds);

  // redis.get 返回的是字符串，不是对象。
  const raw = await redis.get(keys.json);

  // 读取后要 JSON.parse 恢复成 JavaScript 对象。
  // raw 可能是 null，所以这里先判断 raw 是否存在。
  const parsed = raw ? JSON.parse(raw) : null;

  console.log("raw =", raw);
  console.log("parsed.output.temperature =", parsed?.output.temperature);
}

async function demoCounter() {
  console.log("\n3. Atomic counter");

  // INCR 会把 String 当作整数进行原子加 1。
  // 如果 key 不存在，Redis 会先把它当成 0，再加 1。
  // 第一次执行后：learn:redis:counter -> "1"。
  console.log("INCR =", await redis.incr(keys.counter));

  // 第二次执行后：learn:redis:counter -> "2"。
  // INCR 是原子命令，适合做限流计数、访问次数、消息数量统计。
  console.log("INCR =", await redis.incr(keys.counter));

  // 给计数器设置 TTL，模拟“每个时间窗口内的计数”。
  // Agent 限流常见设计：agent:rate_limit:{userId}:minute -> 当前分钟请求次数。
  await redis.expire(keys.counter, ttlSeconds);
  console.log("TTL =", await redis.ttl(keys.counter));
}

async function demoHash() {
  console.log("\n4. Hash for task state");

  // Hash 适合保存“一个对象的多个字段”。
  // 这里模拟一个 Agent 后台任务：
  // learn:redis:hash:task:1001 -> {
  //   status: "running",
  //   worker: "worker-01",
  //   step: "search_docs",
  //   retry_count: "0"
  // }
  await redis.hset(keys.hash, {
    status: "running",
    worker: "worker-01",
    step: "search_docs",
    retry_count: "0",
  });

  // HINCRBY 会把 Hash 中某个 field 当成整数增加指定值。
  // 执行后 retry_count 从 "0" 变成 "1"。
  await redis.hincrby(keys.hash, "retry_count", 1);

  // HSET 也可以只更新某一个 field，不需要重写整个对象。
  // 执行后 step 从 "search_docs" 变成 "call_model"。
  await redis.hset(keys.hash, "step", "call_model");

  // Hash key 本身也可以设置 TTL。TTL 作用在整个 key 上，不是单独作用在某个 field 上。
  await redis.expire(keys.hash, ttlSeconds);

  // HGETALL 读取整个 Hash。
  // ioredis 会把 Redis 返回的 field/value 列表转换成普通 JS 对象。
  console.log(await redis.hgetall(keys.hash));
}

async function demoList() {
  console.log("\n5. List for recent messages");

  // List 是有顺序的字符串列表。
  // RPUSH 表示从列表右侧追加元素，所以这里三条消息会按写入顺序排列：
  // [user hello, assistant hi, user explain Redis TTL]
  await redis.rpush(
    keys.list,
    JSON.stringify({ role: "user", content: "hello" }),
    JSON.stringify({ role: "assistant", content: "hi, how can I help?" }),
    JSON.stringify({ role: "user", content: "explain Redis TTL" }),
  );

  // LTRIM key start stop 会裁剪列表，只保留指定范围。
  // -2 -1 表示只保留最后两个元素。
  // 执行后第一条 "user: hello" 会被裁掉。
  await redis.ltrim(keys.list, -2, -1);

  // 给整个消息列表设置 TTL。
  await redis.expire(keys.list, ttlSeconds);

  // LRANGE key 0 -1 表示读取整个列表。
  // 列表里保存的是 JSON 字符串，所以读取后逐条 JSON.parse。
  const messages = await redis.lrange(keys.list, 0, -1);
  console.log(messages.map((message) => JSON.parse(message)));
}

async function demoSet() {
  console.log("\n6. Set for deduplication");

  // Set 是不重复集合。
  // 这里故意把 https://example.com/a 添加两次，Redis 只会保存一份。
  // 适合 Agent 抓网页、搜索资料时记录“已经处理过哪些 URL”。
  await redis.sadd(
    keys.set,
    "https://example.com/a",
    "https://example.com/b",
    "https://example.com/a",
  );

  await redis.expire(keys.set, ttlSeconds);

  // SCARD 返回 Set 中成员数量。因为 a 重复了，所以这里应该是 2。
  console.log("SCARD =", await redis.scard(keys.set));

  // SISMEMBER 判断某个成员是否存在。存在返回 1，不存在返回 0。
  console.log("SISMEMBER a =", await redis.sismember(keys.set, "https://example.com/a"));

  // SMEMBERS 返回全部成员。Set 没有顺序，不要依赖返回顺序。
  console.log("members =", await redis.smembers(keys.set));
}

async function demoSortedSet() {
  console.log("\n7. Sorted Set for priority queue");

  // Sorted Set，也叫 ZSet，是“成员 + score”的集合。
  // member 不重复，score 用于排序。
  // 这里用 score 表示任务优先级：分数越高，优先级越高。
  await redis.zadd(
    keys.zset,
    10,
    "normal_task",
    100,
    "urgent_task",
    50,
    "medium_task",
  );

  await redis.expire(keys.zset, ttlSeconds);

  // ZREVRANGE 从高分到低分读取。
  // WITHSCORES 表示同时返回 member 和 score。
  console.log("all =", await redis.zrevrange(keys.zset, 0, -1, "WITHSCORES"));

  // ZPOPMAX 取出 score 最大的成员，并从 Sorted Set 中删除它。
  // 这里会取出 urgent_task。
  console.log("pop max =", await redis.zpopmax(keys.zset));
}

async function demoPipeline() {
  console.log("\n8. Pipeline for batch commands");

  // MSET 一次写入多个 String key。
  await redis.mset(keys.pipelineA, "value-a", keys.pipelineB, "value-b");

  // 给两个 key 设置 TTL。内部用 pipeline 批量发送 EXPIRE 命令。
  await setTtlForDemoKeys(keys.pipelineA, keys.pipelineB);

  // Pipeline 会把多条命令打包发送，减少网络往返。
  // 注意：Pipeline 不是事务，它只是批量发送命令。
  const results = await redis
    .pipeline()
    .get(keys.pipelineA)
    .get(keys.pipelineB)
    .ttl(keys.pipelineA)
    .exec();

  // ioredis pipeline 的返回结构是：
  // [
  //   [error, result],
  //   [error, result],
  //   ...
  // ]
  console.log(results);
}

async function demoTransaction() {
  console.log("\n9. Transaction for grouped commands");

  // multi() 创建 Redis 事务队列，exec() 时按顺序执行。
  // Redis 事务和 PostgreSQL 事务不同：Redis 没有复杂回滚机制。
  // 这里演示把多条相关命令放在一个 EXEC 中执行。
  const results = await redis
    .multi()
    .set(keys.txA, "created")
    .incr(keys.txCounter)
    .expire(keys.txA, ttlSeconds)
    .expire(keys.txCounter, ttlSeconds)
    .exec();

  console.log(results);
}

async function demoStream() {
  console.log("\n10. Stream for append-only events");

  // Stream 适合保存“追加事件”。
  // XADD key * field value field value ...
  // * 表示让 Redis 自动生成消息 id。
  // 这里模拟 Agent 工具调用事件：某个 session 调用了 search 工具。
  const eventId = await redis.xadd(
    keys.stream,
    "*",
    "type",
    "tool_called",
    "session_id",
    "session-001",
    "tool",
    "search",
  );

  await redis.expire(keys.stream, ttlSeconds);

  console.log("event id =", eventId);

  // XRANGE key - + 表示读取 Stream 中从最小 id 到最大 id 的所有事件。
  console.log("events =", await redis.xrange(keys.stream, "-", "+"));
}

async function demoLock() {
  console.log("\n11. Simple lock with SET NX EX");

  // 锁的 value 使用随机值，而不是固定字符串。
  // 原因：释放锁时要确认“这个锁还是不是我持有的锁”。
  const lockValue = crypto.randomUUID();

  // SET key value NX EX seconds 是 Redis 简单锁的基础：
  // - NX 表示 key 不存在时才设置，避免多个请求同时拿到锁。
  // - EX 30 表示 30 秒后自动过期，避免进程崩溃后锁永久存在。
  const result = await redis.set(keys.lock, lockValue, "NX", "EX", 30);

  console.log(result === "OK" ? "lock acquired" : "lock failed");

  // 不能直接 DEL lockKey 释放锁。
  // 因为锁可能已经过期，并被另一个请求重新获取。
  // 下面用 Lua 脚本保证“只有 value 还是自己写入的 lockValue 时，才删除锁”。
  const releaseResult = await redis.eval(
    `
    if redis.call("GET", KEYS[1]) == ARGV[1] then
      return redis.call("DEL", KEYS[1])
    else
      return 0
    end
    `,
    1,
    keys.lock,
    lockValue,
  );

  console.log("lock released =", releaseResult === 1);
}

async function printDemoKeys() {
  console.log("\n12. Keys left for inspection");

  // SCAN 用于分批扫描 key。
  // 学习阶段你可能见过 KEYS *，但生产环境不建议用 KEYS 扫全库。
  // MATCH learn:redis:* 表示只看本示例创建的 key。
  const [cursor, foundKeys] = await redis.scan(0, "MATCH", `${prefix}:*`, "COUNT", 100);

  console.log("cursor =", cursor);
  console.log(foundKeys.sort());
  console.log(`These keys expire in about ${ttlSeconds} seconds.`);
}

async function run() {
  try {
    // 每次运行前先删除上一次学习留下的 key，保证输出稳定。
    await resetDemoKeys();

    // 按文档学习顺序依次演示 Redis 常用结构和机制。
    await demoStringAndTtl();
    await demoJsonString();
    await demoCounter();
    await demoHash();
    await demoList();
    await demoSet();
    await demoSortedSet();
    await demoPipeline();
    await demoTransaction();
    await demoStream();
    await demoLock();
    await printDemoKeys();
  } finally {
    // 脚本结束前关闭 Redis 连接。
    // 如果不 quit，Node.js 进程可能因为连接还开着而不退出。
    await redis.quit();
  }
}

await run();
