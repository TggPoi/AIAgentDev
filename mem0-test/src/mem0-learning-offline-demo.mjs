/**
 * Mem0 学习用离线模拟脚本。
 *
 * 这个脚本不连接 Mem0 云服务、OpenAI 或 Redis，目的是把“记忆系统到底做了什么”
 * 拆成可以本地观察的数据变化：
 *
 * 1. add：把一轮对话提炼成 memory 文本，并挂到 userId/runId/agentId 这些 scope 上。
 * 2. search：用查询文本匹配已有 memory，并按 scope 过滤，模拟“检索相关记忆”。
 * 3. buildMemoryPrompt：把检索结果组装成 SystemMessage 文本，模拟注入给 Agent 的上下文。
 * 4. deleteAll：按 scope 删除测试数据，观察不同层级的隔离效果。
 *
 * 运行：
 *   node src/mem0-learning-offline-demo.mjs
 *   pnpm mem0:offline
 */

const USER_ID = "learning_user";
const RUN_ID = "learning_session";
const AGENT_ID = "learning_agent";

function printStep(title, data) {
  console.log(`\n=== ${title} ===`);
  console.log(typeof data === "string" ? data : JSON.stringify(data, null, 2));
}

function normalizeText(text) {
  return text
    .toLowerCase()
    .replace(/[，。！？、：；（）()]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function queryHints(query) {
  const normalized = normalizeText(query);
  const hints = [normalized];

  if (normalized.includes("住")) hints.push("住在", "杭州", "北京");
  if (normalized.includes("喜欢")) hints.push("喜欢", "骑行", "摄影", "跑步");
  if (normalized.includes("会话") || normalized.includes("这次")) hints.push("这次", "会话", "q1", "总结", "复盘");
  if (normalized.includes("agent") || normalized.includes("风格")) hints.push("agent", "学习导师", "解释为什么");

  return [...new Set(hints.filter(Boolean))];
}

function scoreMemory(query, memory) {
  const memoryText = normalizeText(memory);

  let score = 0;
  for (const hint of queryHints(query)) {
    if (memoryText.includes(hint)) score += hint.length;
  }

  return score;
}

function matchesScope(memory, filters = {}) {
  if (filters.user_id && memory.userId !== filters.user_id) return false;
  if (filters.run_id && memory.runId !== filters.run_id) return false;
  if (filters.agent_id && memory.agentId !== filters.agent_id) return false;
  return true;
}

class OfflineMemoryClient {
  constructor() {
    this.nextId = 1;
    this.memories = [];
  }

  /**
   * 模拟 Mem0 的 add。
   *
   * 为什么输入是 messages：
   * Mem0 接收的是一轮或多轮对话，而不是用户手写的单条 memory。真实服务会做抽取、
   * 去重和更新；这里为了离线学习，只把 user 消息拼成一条可观察的 memory。
   *
   * 执行后发生什么：
   * memories 数组新增一条对象，里面同时保存 memory 文本和 scope 字段。
   */
  async add(messages, { userId, runId, agentId } = {}) {
    const userFacts = messages
      .filter((message) => message.role === "user")
      .map((message) => message.content)
      .join(" ");

    const memory = {
      id: `mem_${this.nextId++}`,
      memory: userFacts,
      userId: userId ?? null,
      runId: runId ?? null,
      agentId: agentId ?? null,
      createdAt: new Date().toISOString(),
    };

    this.memories.push(memory);
    return [memory];
  }

  /**
   * 模拟 Mem0 的 search。
   *
   * filters 决定“在哪个记忆空间里找”。例如只传 user_id 会找到用户长期记忆；
   * 同时传 user_id + run_id 才会限定到某个会话。
   *
   * 返回值保留 results 字段，是为了贴近当前工程里 MemoryClient.search() 的使用方式。
   */
  async search(query, { filters = {}, topK = 5 } = {}) {
    const scored = this.memories
      .filter((memory) => matchesScope(memory, filters))
      .map((memory) => ({ ...memory, score: scoreMemory(query, memory.memory) }))
      .filter((memory) => memory.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);

    return { results: scored };
  }

  async getAll({ filters = {} } = {}) {
    return {
      count: this.memories.filter((memory) => matchesScope(memory, filters)).length,
      results: this.memories.filter((memory) => matchesScope(memory, filters)),
    };
  }

  async deleteAll({ userId, runId, agentId } = {}) {
    const before = this.memories.length;
    this.memories = this.memories.filter((memory) => {
      if (userId && memory.userId !== userId) return true;
      if (runId && memory.runId !== runId) return true;
      if (agentId && memory.agentId !== agentId) return true;
      return false;
    });
    return { deleted: before - this.memories.length };
  }
}

function buildMemoryPrompt({ userMemories, sessionMemories, agentMemories }) {
  const blocks = [];

  if (userMemories.length) {
    blocks.push(`【用户长期记忆】\n${userMemories.map((m) => `- ${m.memory}`).join("\n")}`);
  }

  if (sessionMemories.length) {
    blocks.push(`【当前会话记忆】\n${sessionMemories.map((m) => `- ${m.memory}`).join("\n")}`);
  }

  if (agentMemories.length) {
    blocks.push(`【Agent 角色记忆】\n${agentMemories.map((m) => `- ${m.memory}`).join("\n")}`);
  }

  return blocks.length
    ? `${blocks.join("\n\n")}\n\n请结合以上记忆回答，不能把没有命中的内容当事实。`
    : null;
}

async function main() {
  const client = new OfflineMemoryClient();

  await client.add(
    [
      { role: "user", content: "我叫小明，住在杭州，长期喜欢骑行和摄影。" },
      { role: "assistant", content: "好的，这属于跨会话也有用的用户画像。" },
    ],
    { userId: USER_ID },
  );

  await client.add(
    [
      { role: "user", content: "这次会话先写 Q1 总结，重点补项目复盘。" },
      { role: "assistant", content: "明白，这只对当前会话有用。" },
    ],
    { userId: USER_ID, runId: RUN_ID },
  );

  await client.add(
    [
      { role: "user", content: "这个 Agent 是学习导师，回答时要解释为什么。" },
      { role: "assistant", content: "好的，我会保持教学风格。" },
    ],
    { agentId: AGENT_ID },
  );

  printStep("1. 全部记忆", await client.getAll());

  const userMemories = await client.search("用户住在哪里，喜欢什么", {
    filters: { user_id: USER_ID },
  });
  printStep("2. 只按 user_id 检索", userMemories.results);

  const sessionMemories = await client.search("这次会话要写什么", {
    filters: { user_id: USER_ID, run_id: RUN_ID },
  });
  printStep("3. 按 user_id + run_id 检索", sessionMemories.results);

  const wrongSession = await client.search("这次会话要写什么", {
    filters: { user_id: USER_ID, run_id: "other_session" },
  });
  printStep("4. run_id 不匹配时没有会话记忆", wrongSession.results);

  const agentMemories = await client.search("Agent 的回答风格", {
    filters: { agent_id: AGENT_ID },
  });

  printStep(
    "5. 组装给 Agent 的记忆提示",
    buildMemoryPrompt({
      userMemories: userMemories.results,
      sessionMemories: sessionMemories.results,
      agentMemories: agentMemories.results,
    }),
  );

  printStep("6. 清理当前会话记忆", await client.deleteAll({ userId: USER_ID, runId: RUN_ID }));
  printStep("7. 清理后再查当前会话", await client.search("这次会话要写什么", {
    filters: { user_id: USER_ID, run_id: RUN_ID },
  }));
  printStep("8. 用户长期记忆仍然存在", await client.search("用户住在哪里", {
    filters: { user_id: USER_ID },
  }));
}

main().catch((error) => {
  console.error("\n执行失败:", error.message ?? error);
  process.exit(1);
});
