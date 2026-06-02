import { pool } from "./db.mjs";
import * as users from "./users.mjs";
import * as conversations from "./conversations.mjs";
import * as messages from "./messages.mjs";

async function run() {
  console.log("=== 用户 CRUD ===");

  const user = await users.createUser("张三");
  console.log("创建用户:", user);

  const fetchedUser = await users.getUserById(user.id);
  console.log("查询用户:", fetchedUser);

  const updatedUser = await users.updateUser(user.id, "李四");
  console.log("更新用户:", updatedUser);

  console.log("\n=== 会话 CRUD ===");

  const conversation = await conversations.createConversation(
    user.id,
    "第一次对话"
  );
  console.log("创建会话:", conversation);

  const userConversations = await conversations.getConversationsByUserId(
    user.id
  );
  console.log("用户的会话列表:", userConversations);

  const updatedConversation = await conversations.updateConversation(
    conversation.id,
    { title: "更新后的标题" }
  );
  console.log("更新会话:", updatedConversation);

  console.log("\n=== 消息 CRUD ===");

  const userMessage = await messages.createMessage(
    conversation.id,
    "user",
    "你好，请介绍一下 PostgreSQL"
  );
  console.log("创建用户消息:", userMessage);

  const assistantMessage = await messages.createMessage(
    conversation.id,
    "assistant",
    "PostgreSQL 是一个功能强大的开源关系型数据库。"
  );
  console.log("创建 AI 消息:", assistantMessage);

  const conversationMessages = await messages.getMessagesByConversationId(
    conversation.id
  );
  console.log("会话消息列表:", conversationMessages);

  const updatedMessage = await messages.updateMessage(
    userMessage.id,
    "你好，请介绍一下 pgvector"
  );
  console.log("更新消息:", updatedMessage);

  console.log("\n=== 语义检索 ===");

  const seedMessages = [
    { role: "user", content: "PostgreSQL 支持哪些数据类型？" },
    {
      role: "assistant",
      content:
        "PostgreSQL 支持整数、文本、JSON、数组，以及 pgvector 扩展提供的向量类型。",
    },
    { role: "user", content: "怎么做相似度搜索？" },
    {
      role: "assistant",
      content:
        "可以使用 pgvector 的 cosine 距离运算符 <=>，配合 hnsw 索引加速向量检索。",
    },
  ];

  for (const msg of seedMessages) {
    await messages.createMessage(
      conversation.id,
      msg.role,
      msg.content,
      true
    );
  }
  console.log(`已写入 ${seedMessages.length} 条带 embedding 的消息`);

  const searchQueries = ["向量相似度怎么查", "关系型数据库有哪些类型"];

  for (const searchText of searchQueries) {
    console.log(`\n搜索: "${searchText}"`);
    const results = await messages.searchSimilarMessages(
      conversation.id,
      searchText,
      3
    );
    if (results.length === 0) {
      console.log("  无匹配结果");
      continue;
    }
    for (const [i, row] of results.entries()) {
      console.log(
        `  ${i + 1}. [${row.role}] ${row.content} (similarity: ${Number(row.similarity).toFixed(4)})`
      );
    }
  }

  // console.log("\n=== 清理 ===");

  // await messages.deleteMessage(assistantMessage.id);
  // await messages.deleteMessage(updatedMessage.id);
  // await conversations.deleteConversation(conversation.id);
  // await users.deleteUser(user.id);

  // console.log("演示数据已清理");
}

run()
  .catch((err) => {
    console.error("运行失败:", err.message);
    process.exit(1);
  })
  .finally(() => pool.end());

export { users, conversations, messages };


// PS D:\AI_Agent_Project\pgsql-test> node .\src\index.mjs
// === 用户 CRUD ===
// 创建用户: { id: 4, name: '张三', created_at: 2026-06-02T04:32:19.542Z }
// 查询用户: { id: 4, name: '张三', created_at: 2026-06-02T04:32:19.542Z }
// 更新用户: { id: 4, name: '李四', created_at: 2026-06-02T04:32:19.542Z }

// === 会话 CRUD ===
// 创建会话: {
//   id: 3,
//   user_id: 4,
//   title: '第一次对话',
//   created_at: 2026-06-02T04:32:19.564Z
// }
// 用户的会话列表: [
//   {
//     id: 3,
//     user_id: 4,
//     title: '第一次对话',
//     created_at: 2026-06-02T04:32:19.564Z
//   }
// ]
// 更新会话: {
//   id: 3,
//   user_id: 4,
//   title: '更新后的标题',
//   created_at: 2026-06-02T04:32:19.564Z
// }

// === 消息 CRUD ===
// 创建用户消息: {
//   id: 3,
//   conversation_id: 3,
//   role: 'user',
//   content: '你好，请介绍一下 PostgreSQL',
//   embedding: null,
//   created_at: 2026-06-02T04:32:19.582Z
// }
// 创建 AI 消息: {
//   id: 4,
//   conversation_id: 3,
//   role: 'assistant',
//   content: 'PostgreSQL 是一个功能强大的开源关系型数据库。',
//   embedding: null,
//   created_at: 2026-06-02T04:32:19.593Z
// }
// 会话消息列表: [
//   {
//     id: 3,
//     conversation_id: 3,
//     role: 'user',
//     content: '你好，请介绍一下 PostgreSQL',
//     created_at: 2026-06-02T04:32:19.582Z
//   },
//   {
//     id: 4,
//     conversation_id: 3,
//     role: 'assistant',
//     content: 'PostgreSQL 是一个功能强大的开源关系型数据库。',
//     created_at: 2026-06-02T04:32:19.593Z
//   }
// ]
// 更新消息: {
//   id: 3,
//   conversation_id: 3,
//   role: 'user',
//   content: '你好，请介绍一下 pgvector',
//   embedding: null,
//   created_at: 2026-06-02T04:32:19.582Z
// }

// === 语义检索 ===
// 已写入 4 条带 embedding 的消息

// 搜索: "向量相似度怎么查"
//   1. [user] 怎么做相似度搜索？ (similarity: 0.7986)
//   2. [assistant] 可以使用 pgvector 的 cosine 距离运算符 <=>，配合 hnsw 索引加速向量检索。 (similarity: 0.6657)
//   3. [assistant] PostgreSQL 支持整数、文本、JSON、数组，以及 pgvector 扩展提供的向量类型。 (similarity: 0.4967)

// 搜索: "关系型数据库有哪些类型"
//   1. [user] PostgreSQL 支持哪些数据类型？ (similarity: 0.5835)
//   2. [assistant] PostgreSQL 支持整数、文本、JSON、数组，以及 pgvector 扩展提供的向量类型。 (similarity: 0.5036)
//   3. [assistant] 可以使用 pgvector 的 cosine 距离运算符 <=>，配合 hnsw 索引加速向量检索。 (similarity: 0.3335)