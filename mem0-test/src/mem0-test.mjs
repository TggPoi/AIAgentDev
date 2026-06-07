import 'dotenv/config';
import { MemoryClient } from 'mem0ai';

const USER_ID = 'demo-user';

function log(title, data) {
  console.log(`\n=== ${title} ===`);
  console.log(typeof data === 'string' ? data : JSON.stringify(data, null, 2));
}

async function main() {

  const client = new MemoryClient({ 
    apiKey: process.env.MEM0_API_KEY
  });

  /**
   * 添加记忆
   */
//   const conversation = [
//     { role: 'user', content: '我是素食主义者，而且对坚果过敏。' },
//     { role: 'assistant', content: '好的，我会记住你的饮食偏好。' },
//     { role: 'user', content: '我住在北京，平时喜欢跑步。' },
//     { role: 'assistant', content: '已记录：北京、爱好跑步。' },
//   ];

//   const added = await client.add(conversation, { userId: USER_ID });
//   log('添加记忆', added);


  /**
   * 检索记忆
   */
  const searchResult = await client.search('用户的饮食限制是什么？中文回答', {
    filters: { user_id: USER_ID },
    topK: 5
  });
  log('搜索记忆', searchResult);

    /**
     * 列出全部记忆
     */
  const allMemories = await client.getAll({
    filters: { user_id: USER_ID },
    pageSize: 10,
  });
  log('列出全部记忆', allMemories);

    /**
     * 获取、更新、历史记录
     */
  const firstMemory = allMemories.results?.[0] ?? searchResult.results?.[0];
  if (firstMemory?.id) {
    const memory = await client.get(firstMemory.id);
    log('获取单条记忆', memory);

    const updated = await client.update(firstMemory.id, {
      text: `${memory.memory ?? firstMemory.memory}（已通过示例脚本更新）`,
    });
    log('更新记忆', updated);

    const history = await client.history(firstMemory.id);
    log('记忆变更历史', history);
  }

  if (process.argv.includes('--cleanup')) {
    const deleted = await client.deleteAll({ userId: USER_ID });
    log('清理测试数据', deleted);
  } else {
    console.log('\n提示: 运行 `node src/mem0-test.mjs --cleanup` 可删除本次测试用户的全部记忆');
  }
}

main().catch((error) => {
  console.error('\n执行失败:', error.message ?? error);
  if (error.suggestion) {
    console.error('建议:', error.suggestion);
  }
  process.exit(1);
});

/*
=== 搜索记忆 ===
{
  "results": [
    {
      "id": "31d6c963-c08d-4d7d-8de1-d4cb130cb774",
      "memory": "User is a vegetarian and is allergic to nuts",
      "userId": "demo-user",
      "agentId": null,
      "appId": null,
      "runId": null,

      "score": 0.2346,

      "scoreBreakdown": {
        "semantic": 0.5866,
        "bm25": 0,
        "entity": 0
      },
      "metadata": {},
      "categories": [
        "food",
        "health"
      ],
      "createdAt": "2026-06-07T07:37:54+00:00",
      "updatedAt": "2026-06-07T07:38:27.266723+00:00"
    },
    {
      "id": "ba24117c-cabb-42ec-9996-99046bb756e2",
      "memory": "User lives in Beijing and enjoys running as a regular activity",
      "userId": "demo-user",
      "agentId": null,
      "appId": null,
      "runId": null,

      "score": 0.1811,

      "scoreBreakdown": {
        "semantic": 0.4527,
        "bm25": 0,
        "entity": 0
      },
      "metadata": {},
      "categories": [
        "hobbies"
      ],
      "createdAt": "2026-06-07T07:37:54+00:00",
      "updatedAt": "2026-06-07T07:38:24.601946+00:00"
    }
  ]
}
*/


/**
=== 列出全部记忆 ===
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "31d6c963-c08d-4d7d-8de1-d4cb130cb774",
      "memory": "User is a vegetarian and is allergic to nuts",
      "userId": "demo-user",
      "metadata": null,
      "categories": [
        "food",
        "health"
      ],
      "createdAt": "2026-06-07T00:37:54-07:00",
      "updatedAt": "2026-06-07T00:38:27-07:00",
      "expirationDate": null,
      "structuredAttributes": {
        "year": 2026,
        "month": 6,
        "day": 7,
        "hour": 7,
        "minute": 37,
        "dayOfWeek": "sunday",
        "weekOfYear": 23,
        "dayOfYear": 158,
        "quarter": 2,
        "isWeekend": true
      }
    },
    {
      "id": "ba24117c-cabb-42ec-9996-99046bb756e2",
      "memory": "User lives in Beijing and enjoys running as a regular activity",
      "userId": "demo-user",
      "metadata": null,
      "categories": [
        "hobbies"
      ],
      "createdAt": "2026-06-07T00:37:54-07:00",
      "updatedAt": "2026-06-07T00:38:24-07:00",
      "expirationDate": null,
      "structuredAttributes": {
        "year": 2026,
        "month": 6,
        "day": 7,
        "hour": 7,
        "minute": 37,
        "dayOfWeek": "sunday",
        "weekOfYear": 23,
        "dayOfYear": 158,
        "quarter": 2,
        "isWeekend": true
      }
    }
  ]
}
*/