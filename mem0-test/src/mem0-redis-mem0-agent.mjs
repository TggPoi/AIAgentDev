/**
 * Redis 记这轮聊天，Mem0 记值得长期留着的事。
 *
 * 用户层 = 换天聊还认得你；会话层 = 只管当前这个聊天窗口。
 *
 * docker compose up -d redis 后 pnpm agent
 * :clear 清 Redis | :clear-mem0 清 Mem0 | exit/:q 退出
 */
import "dotenv/config";
import Redis from "ioredis";
import * as readline from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { z } from "zod";
import { MemoryClient } from "mem0ai";
import { ChatOpenAI } from "@langchain/openai";
import {
  SystemMessage,
  SystemMessageChunk,
  HumanMessage,
  mapChatMessagesToStoredMessages,
  mapStoredMessagesToChatMessages,
} from "@langchain/core/messages";
import { createAgent, summarizationMiddleware } from "langchain";

const REDIS_HOST = process.env.REDIS_HOST ?? "localhost";
const REDIS_PORT = Number(process.env.REDIS_PORT ?? 6379);
const REDIS_DB = Number(process.env.REDIS_DB ?? 0);
const MEMORY_TTL = Number(process.env.MEMORY_TTL_SECONDS ?? 1800);
const KEY_PREFIX = process.env.MEMORY_KEY_PREFIX ?? "agent:short_memory";

const USER_ID = process.env.MEM0_USER_ID ?? "demo_user_001";
const SESSION_ID = "session_002";
const MEM0_TOP_K = Number(process.env.MEM0_TOP_K ?? 5);

const memorySchema = z.object({
  write_user: z
    .boolean()
    .describe(
      "写入用户层：换一个新会话仍应保留的长期事实（身份、居住地、长期爱好、饮食禁忌、持久偏好）。不含仅本轮任务。",
    ),
  write_session: z
    .boolean()
    .describe(
      "写入会话层：仅当前会话/thread 有效的任务、大纲、进度、待办、临时决策（如「这次先写…」「数据部分明天补」）。",
    ),
  reason: z.string().describe("分类理由，一句话"),
});

const CLASSIFIER_PROMPT = `你是记忆分层分类器。判断本轮对话是否有「新事实」需写入 Mem0，并分到正确层级。

## user 层（跨会话长期）
- 用户身份与画像：姓名、职业、居住地、长期爱好
- 长期偏好与约束：饮食过敏、回答风格、常用技术栈
- 持续数周以上的个人背景（非单次任务）

## session 层（仅当前会话）
- 当前正在做的任务、目标、文档大纲、方案草稿
- 本会话内的进度、决策、待办、临时约定
- 用户明确用「这次」「本轮」「当前会话」描述的工作上下文

## 均不写入
- 寒暄、致谢、纯确认
- 助手生成的通用内容（攻略、示例代码、建议清单），用户未明确采纳为新事实
- 无信息增量的复述

## 决策原则
1. 「这次我们先写 Q1 总结」「当前在排查 XX」→ 优先 session，不要标成 user
2. user 与 session 可同时为 true（如同时说职业+当前任务），但勿把纯会话任务只标 user
3. 一次性请求（如「帮我做旅行攻略」）且未产生需跨轮记住的约定 → 均为 false`;

const summaryPrompt = `你是对话摘要助手。用中文简洁总结：话题、会话内进度/报错/待办。
用户级长期偏好由外部记忆维护，摘要勿重复堆砌。不要编造。

待摘要的对话：
{messages}

摘要：`;

/**
 * 过滤出可以保存到 Redis 的消息列表。
 *
 * 作用：
 * - Mem0 检索结果会临时注入为 SystemMessage，供本轮模型回答参考。
 * - 这些 SystemMessage 只是本轮上下文，不应该写回 Redis，否则后续轮次会重复保存同一批记忆。
 *
 * 输入参数：
 * @param {import("@langchain/core/messages").BaseMessage[]} messages
 * LangChain 消息数组，通常来自 agent.invoke() 返回的 result.messages。
 *
 * 输出结果：
 * @returns {import("@langchain/core/messages").BaseMessage[]}
 * 已移除 SystemMessage/SystemMessageChunk 的消息数组，可安全写入 Redis。
 */
function messagesForRedis(messages) {
  return messages.filter(
    (m) => !SystemMessage.isInstance(m) && !SystemMessageChunk.isInstance(m),
  );
}

/**
 * Redis 短期消息存储。
 *
 * 作用：
 * - 按 sessionId 保存当前会话的聊天历史。
 * - 使用 Redis TTL 控制短期记忆生命周期。
 * - 负责 LangChain 消息对象与可 JSON 序列化格式之间的转换。
 */
class RedisMessageStore {
  /**
   * 创建 RedisMessageStore 实例。
   *
   * 输入参数：
   * @param {object} options
   * @param {Redis} options.redis ioredis 客户端实例。
   * @param {string} options.keyPrefix Redis key 前缀，用来隔离不同应用或不同记忆用途。
   * @param {number} options.ttlSeconds 消息写入 Redis 后的过期秒数。
   *
   * 输出结果：
   * @returns {RedisMessageStore}
   * 初始化好的 Redis 短期消息存储实例。
   */
  constructor({ redis, keyPrefix, ttlSeconds }) {
    this.redis = redis;
    this.keyPrefix = keyPrefix;
    this.ttlSeconds = ttlSeconds;
  }

  /**
   * 生成当前会话消息历史使用的 Redis key。
   *
   * 输入参数：
   * @param {string} sessionId 当前会话 ID。
   *
   * 输出结果：
   * @returns {string}
   * Redis key，格式为 `${keyPrefix}:${sessionId}:messages`。
   */
  messagesKey(sessionId) {
    return `${this.keyPrefix}:${sessionId}:messages`;
  }

  /**
   * 从 Redis 读取当前会话的历史消息。
   *
   * 输入参数：
   * @param {string} sessionId 当前会话 ID。
   *
   * 输出结果：
   * @returns {Promise<import("@langchain/core/messages").BaseMessage[]>}
   * Redis 中保存的 LangChain 消息数组；没有历史时返回空数组。
   */
  async loadMessages(sessionId) {
    const raw = await this.redis.get(this.messagesKey(sessionId));
    if (!raw) return [];
    return mapStoredMessagesToChatMessages(JSON.parse(raw));
  }

  /**
   * 将当前会话的消息历史写入 Redis。
   *
   * 输入参数：
   * @param {string} sessionId 当前会话 ID。
   * @param {import("@langchain/core/messages").BaseMessage[]} messages
   * 要保存的 LangChain 消息数组，通常已经通过 messagesForRedis() 过滤。
   *
   * 输出结果：
   * @returns {Promise<void>}
   * 无返回值；写入成功后 Redis key 会带有 ttlSeconds 指定的过期时间。
   */
  async saveMessages(sessionId, messages) {
    const payload = JSON.stringify(mapChatMessagesToStoredMessages(messages));
    await this.redis.set(this.messagesKey(sessionId), payload, "EX", this.ttlSeconds);
  }

  /**
   * 清空当前会话的 Redis 短期记忆。
   *
   * 输入参数：
   * @param {string} sessionId 当前会话 ID。
   *
   * 输出结果：
   * @returns {Promise<void>}
   * 无返回值；对应 Redis key 被删除。
   */
  async clear(sessionId) {
    await this.redis.del(this.messagesKey(sessionId));
  }

  /**
   * 查询当前会话 Redis 消息 key 的剩余 TTL。
   *
   * 输入参数：
   * @param {string} sessionId 当前会话 ID。
   *
   * 输出结果：
   * @returns {Promise<number>}
   * Redis TTL 秒数；遵循 Redis ttl 命令语义，-1 表示无过期时间，-2 表示 key 不存在。
   */
  async ttl(sessionId) {
    return this.redis.ttl(this.messagesKey(sessionId));
  }
}

/**
 * Mem0 长期/会话级记忆存储。
 *
 * 作用：
 * - 从 Mem0 同时检索用户层长期记忆和当前会话层记忆。
 * - 将检索到的记忆拼成 SystemMessage 注入给模型。
 * - 调用分类模型判断本轮对话是否需要写入 Mem0。
 */
class Mem0MemoryStore {
  /**
   * 创建 Mem0MemoryStore 实例。
   *
   * 输入参数：
   * @param {object} options
   * @param {MemoryClient} options.client Mem0 客户端实例。
   * @param {string} options.userId 用户 ID，用于用户层长期记忆的读写过滤。
   * @param {string} options.sessionId 当前会话 ID，写入 Mem0 时映射为 runId。
   * @param {number} options.topK 每次检索最多返回的记忆条数。
   * @param {object} options.classifier 支持 invoke() 的结构化输出分类器。
   *
   * 输出结果：
   * @returns {Mem0MemoryStore}
   * 初始化好的 Mem0 记忆存储实例。
   */
  constructor({ client, userId, sessionId, topK, classifier }) {
    this.client = client;
    this.userId = userId;
    this.sessionId = sessionId;
    this.topK = topK;
    this.classifier = classifier;
  }

  /**
   * 根据用户输入同时检索用户层和当前会话层记忆。
   *
   * 输入参数：
   * @param {string} query 当前用户输入，会作为 Mem0 语义检索查询。
   *
   * 输出结果：
   * @returns {Promise<{ user: object[], session: object[] }>}
   * user 为当前 userId 下的长期记忆结果；session 为当前 userId + sessionId/runId 下的会话记忆结果。
   */
  async search(query) {
    const [userRes, sessionRes] = await Promise.all([
      this.client.search(query, {
        filters: { user_id: this.userId },
        topK: this.topK,
      }),
      this.client.search(query, {
        filters: {
          AND: [{ user_id: this.userId }, { run_id: this.sessionId }],
        },
        topK: this.topK,
      }),
    ]);
    return {
      user: userRes.results ?? [],
      session: sessionRes.results ?? [],
    };
  }

  /**
   * 将 Mem0 检索结果转换为可注入 agent 的 SystemMessage。
   *
   * 输入参数：
   * @param {object} memories
   * @param {object[]} memories.user 用户层长期记忆结果数组。
   * @param {object[]} memories.session 当前会话层记忆结果数组。
   *
   * 输出结果：
   * @returns {SystemMessage | null}
   * 有可用记忆时返回 SystemMessage；两层都没有命中时返回 null。
   */
  buildSystemMessage({ user, session }) {
    const blocks = [];
    if (user.length) {
      blocks.push(`【用户长期记忆】\n${user.map((m) => `- ${m.memory}`).join("\n")}`);
    }
    if (session.length) {
      blocks.push(`【当前会话记忆】\n${session.map((m) => `- ${m.memory}`).join("\n")}`);
    }
    if (!blocks.length) return null;
    return new SystemMessage(`${blocks.join("\n\n")}\n\n请结合以上记忆回答，勿编造。`);
  }

  /**
   * 判断本轮对话是否需要写入 Mem0，并按分类结果持久化。
   *
   * 输入参数：
   * @param {string} userText 当前轮用户输入。
   * @param {string} assistantText 当前轮助手回复。
   *
   * 输出结果：
   * @returns {Promise<{ written: string[], reason: string }>}
   * written 表示实际写入的层级，可能包含 "user"、"session"，也可能为空；reason 为分类模型给出的理由。
   */
  async classifyAndPersist(userText, assistantText) {
    const turn = [
      { role: "user", content: userText },
      { role: "assistant", content: assistantText },
    ];
    //先进行消息分类处理，由classifier大模型判断 当前消息是否值得写入数据库
    const { write_user, write_session, reason } = await this.classifier.invoke([
      new SystemMessage(CLASSIFIER_PROMPT),
      new HumanMessage(`用户：${userText}\n助手：${assistantText}`),
    ]);
    //根据classifier大模型的处理结果，执行数据库写入操作，并且把写入的内容和理由返回
    const written = [];
    if (write_user) {
      await this.client.add(turn, { userId: this.userId });
      written.push("user");
    }
    if (write_session) {
      await this.client.add(turn, { userId: this.userId, runId: this.sessionId });
      written.push("session");
    }
    return { written, reason };
  }

  /**
   * 清空当前用户在 Mem0 中的用户层和当前会话层记忆。
   *
   * 输入参数：
   * 无显式参数；使用构造器传入的 userId 与 sessionId。
   *
   * 输出结果：
   * @returns {Promise<void>}
   * 无返回值；删除 userId 下的长期记忆，以及 userId + sessionId/runId 下的会话记忆。
   */
  async clear() {
    await this.client.deleteAll({ userId: this.userId });
    await this.client.deleteAll({ userId: this.userId, runId: this.sessionId });
  }
}

/**
 * 执行一次带 Redis 短期记忆和 Mem0 长期/会话记忆的 agent 调用。
 *
 * 作用：
 * - 先从 Redis 加载当前会话历史。
 * - 再从 Mem0 检索用户层和会话层记忆，并将命中结果作为 SystemMessage 注入。
 * - 调用 LangChain agent 得到助手回复。
 * - 将过滤后的消息历史写回 Redis。
 * - 使用分类器判断本轮对话是否需要写入 Mem0。
 *
 * 输入参数：
 * @param {ReturnType<typeof createAgent>} agent LangChain agent 实例。
 * @param {RedisMessageStore} redisStore Redis 短期消息存储实例。
 * @param {Mem0MemoryStore} mem0Store Mem0 记忆存储实例。
 * @param {string} sessionId 当前会话 ID。
 * @param {string} userText 当前轮用户输入。
 *
 * 输出结果：
 * @returns {Promise<{
 *   messages: import("@langchain/core/messages").BaseMessage[],
 *   redisMessages: import("@langchain/core/messages").BaseMessage[],
 *   assistantText: string
 * }>}
 * messages 为 agent 原始返回消息；redisMessages 为过滤后已写入 Redis 的消息；assistantText 为本轮助手回复文本。
 */
async function invokeWithMemory(agent, redisStore, mem0Store, sessionId, userText) {
  const history = await redisStore.loadMessages(sessionId);
  console.log(`  ↳ Redis 加载 ${history.length} 条历史`);

  const mem = await mem0Store.search(userText);
  if (mem.user.length) console.log(`  ↳ Mem0 用户层 ${mem.user.length} 条`);
  if (mem.session.length) console.log(`  ↳ Mem0 会话层 ${mem.session.length} 条`);

  const memoryMsg = mem0Store.buildSystemMessage(mem);
  const invokeMessages = [
    ...(memoryMsg ? [memoryMsg] : []),
    ...history,
    new HumanMessage(userText),
  ];

  const result = await agent.invoke(
    { messages: invokeMessages },
    { recursionLimit: 30 },
  );
  //过滤之前注入的System message
  const redisMessages = messagesForRedis(result.messages);
  const dropped = result.messages.length - redisMessages.length;
  await redisStore.saveMessages(sessionId, redisMessages);
  const ttl = await redisStore.ttl(sessionId);
  console.log(
    `  ↳ Redis 写回 ${redisMessages.length} 条` +
      (dropped ? `（过滤 ${dropped} 条 SystemMessage）` : "") +
      ` (TTL ${ttl}s)`,
  );
  //把最新一次的对话进行分类处理，取出AI最新一次的回答内容
  const assistantText = String(result.messages.at(-1)?.content ?? "");
  const { written, reason } = await mem0Store.classifyAndPersist(userText, assistantText);
  console.log(`  ↳ 分类: ${reason}`);
  console.log(written.length ? `  ↳ Mem0 写入: ${written.join(", ")}` : "  ↳ Mem0 未写入");

  return { messages: result.messages, redisMessages, assistantText };
}
//创建Agent，redis，mem0的客户端实例 Start-----------------------
if (!process.env.MEM0_API_KEY || !process.env.OPENAI_API_KEY) {
  console.error("需要 MEM0_API_KEY 与 OPENAI_API_KEY");
  process.exit(1);
}

const redis = new Redis({ host: REDIS_HOST, port: REDIS_PORT, db: REDIS_DB });
const mem0 = new MemoryClient({ apiKey: process.env.MEM0_API_KEY });

redis.on("connect", () => console.log("✅ Redis 已连接"));
redis.on("error", (err) => console.error("❌ Redis 错误:", err.message));

try {
  await redis.ping();
} catch {
  console.error("Redis 未连接，请先执行: docker compose up -d redis");
  process.exit(1);
}

const redisStore = new RedisMessageStore({
  redis,
  keyPrefix: KEY_PREFIX,
  ttlSeconds: MEMORY_TTL,
});

const llmOpts = {
  apiKey: process.env.OPENAI_API_KEY,
  configuration: { baseURL: process.env.OPENAI_BASE_URL },
  temperature: 0,
};

const model = new ChatOpenAI({ model: process.env.MODEL_NAME, ...llmOpts });

const classifier = new ChatOpenAI({
  model: process.env.MODEL_NAME,
  ...llmOpts,
}).withStructuredOutput(memorySchema);

const mem0Store = new Mem0MemoryStore({
  client: mem0,
  userId: USER_ID,
  sessionId: SESSION_ID,
  topK: MEM0_TOP_K,
  classifier,
});

const agent = createAgent({
  model,
  tools: [],
  systemPrompt:
    "你是会话助手。结合系统消息中的长期/会话记忆回答，中文简短。有对话摘要则据此继续。",
  middleware: [
    summarizationMiddleware({
      model,
      summaryPrompt,
      trigger: { messages: 8 },
      keep: { messages: 4 },
    }),
  ],
});
//创建Agent，redis，mem0的客户端实例 End-----------------------
console.log(`用户 ${USER_ID} | 会话 ${SESSION_ID}`);
console.log("输入 exit / quit / :q 退出；:clear 清空 Redis；:clear-mem0 清空 Mem0\n");

const rl = readline.createInterface({ input: stdin, output: stdout });
let prevCount = (await redisStore.loadMessages(SESSION_ID)).length;

try {
  while (true) {
    const userText = (await rl.question("你: ")).trim();
    if (!userText) continue;

    if (["exit", "quit", ":q"].includes(userText.toLowerCase())) break;

    if (userText === ":clear") {
      await redisStore.clear(SESSION_ID);
      prevCount = 0;
      console.log("已清空 Redis 短期记忆\n");
      continue;
    }

    if (userText === ":clear-mem0") {
      await mem0Store.clear();
      console.log("已清空 Mem0 用户层与当前会话层\n");
      continue;
    }

    const { redisMessages, assistantText } = await invokeWithMemory(
      agent,
      redisStore,
      mem0Store,
      SESSION_ID,
      userText,
    );

    console.log("\n助手:", assistantText);
    console.log(`Redis 消息数: ${redisMessages.length}`);
    if (redisMessages.length < prevCount + 2) {
      console.log("  ⚡ 已触发压缩");
    }
    prevCount = redisMessages.length;
    console.log();
  }
} finally {
  rl.close();
}

await redis.quit();

/*
 * 测试对话（复制进终端，先来 :clear-mem0 和 :clear）
 *
 * 一、寒暄
 * 你好 / 在吗 / 谢谢
 * → 纯客套，Mem0 不用记。
 *
 * 二、自我介绍
 * 我叫小明，住在杭州，平时喜欢骑行和摄影。
 * 我对海鲜过敏，出差尽量别安排沿海城市。
 * → 换天聊还得知道的事，写 user 层。
 *
 * 三、这会儿在干嘛
 * 这次我们先写 Q1 季度总结，大纲分三块：项目复盘、数据指标、下季度计划。
 * 项目复盘里重点写 order-service 的 500 错误排查过程。
 * → 只管这次聊天的事，写 session 层。
 *
 * 四、长期背景 + 手头活
 * 我长期做后端开发，这次会话的任务是排查 payment-api 超时，先从 P99 日志看起。
 * 另外我之后技术回答都希望带代码示例，这个一直记住。
 * → 职业和当前任务可能两层都写，偏好那条走 user。
 *
 * 五、Redis 和 Mem0 各管啥
 * 刚才说的 payment-api，超时阈值先假设 3 秒。
 * 上一句我说的阈值是多少？
 * → 刚说过的话 Redis 兜得住，不用等 Mem0。
 *
 * 重启 agent（别清 mem0）再问：我是谁？有什么过敏？
 * → 新会话 Redis 是空的，user 层还能认出你。
 *
 * 六、聊多了会压缩（可选，连聊 8 轮以上）
 * 继续完善 Q1 总结 / 把第二段改短 / 加个标题……
 * → 终端会出现「已触发压缩」，老消息变摘要。
 *
 * 推荐顺序：清空 → 寒暄 → 自我介绍 → 当前任务 → 重启验 user → 清 mem0 验 session 没了
 */
