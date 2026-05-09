import { Client } from '@elastic/elasticsearch';

/**
 * 初始化创建es索引
 */

const client = new Client({
  node: 'http://localhost:9200'
});

const INDEX_NAME = 'travel_journal';

async function createIndex() {
  const exists = await client.indices.exists({ index: INDEX_NAME });
  if (exists) {
    console.log(`ℹ️ 索引已存在: ${INDEX_NAME}`);
    return;
  }

  await client.indices.create({
    index: INDEX_NAME,
    mappings: {
      properties: {
        note_title: { type: 'text', analyzer: 'ik_max_word', search_analyzer: 'ik_smart' },
        note_body: { type: 'text', analyzer: 'ik_max_word', search_analyzer: 'ik_smart' },
        tags: { type: 'keyword' },
        mood: { type: 'keyword' },
        priority: { type: 'integer' },
        created_at: { type: 'date' },
        updated_at: { type: 'date' }
      }
    }
  });

  console.log(`✅ 索引创建成功: ${INDEX_NAME}`);
}

//初始化数据
async function seedData() {
  const now = new Date().toISOString();
  const docs = [
    {
      note_title: '杭州西湖半日游',
      note_body: '早上绕湖慢跑，中午吃片儿川，下午在断桥拍照放松。',
      tags: ['旅行', '周末', '杭州'],
      mood: 'relaxed',
      priority: 2,
      created_at: now,
      updated_at: now
    },
    {
      note_title: '城市骑行计划',
      note_body: '周六沿江骑行 20 公里，带上水和简易修车工具。',
      tags: ['运动', '骑行'],
      mood: 'energetic',
      priority: 3,
      created_at: now,
      updated_at: now
    },
    {
      note_title: '雨天宅家阅读',
      note_body: '下雨天在家看书，整理本周笔记并做晚餐。',
      tags: ['生活', '阅读'],
      mood: 'calm',
      priority: 1,
      created_at: now,
      updated_at: now
    }
  ];


  //如果使用map会生成嵌套数组，不满足Bulk API 要求
  /**
   * const badResult = docs.map(doc => [
    { index: { _index: INDEX_NAME } }, 
    doc
    ]);

    // 结果是嵌套数组（不符合 Bulk API 要求！）：
    [
    [ { index: { _index: 'notes' } }, { note_title: '杭州西湖半日游', ... } ],
    [ { index: { _index: 'notes' } }, { note_title: '城市骑行计划', ... } ],
    ...
    ]

    const operations = docs.flatMap(doc => [
    { index: { _index: INDEX_NAME } }, // 操作指令行
    doc                               // 文档数据行
    ]);
   */
  const operations = docs.flatMap((doc) => [{ index: { _index: INDEX_NAME } }, doc]);
  //bulk 批量添加 refresh: true 写入后立即刷新索引（使数据立刻可搜索）
  await client.bulk({ refresh: true, operations });
  console.log(`✅ 初始化数据完成，共 ${docs.length} 条`);
}

async function run() {
  await createIndex();
  await seedData();
}

run().catch((err) => {
  console.error('❌ 创建阶段失败:', err);
  process.exit(1);
});