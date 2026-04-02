import "dotenv/config";
import { MilvusClient, DataType, MetricType, IndexType } from '@zilliz/milvus2-sdk-node';
import { OpenAIEmbeddings } from "@langchain/openai";

//集合名是 ai_diary，用来放日记数据的
const COLLECTION_NAME = 'ai_diary';
//指定维度是 1024 维
const VECTOR_DIM = 1024;

const embeddings = new OpenAIEmbeddings({
  apiKey: process.env.OPENAI_API_KEY,
  model: process.env.EMBEDDINGS_MODEL_NAME,
  configuration: {
    baseURL: process.env.OPENAI_BASE_URL
  },
  dimensions: VECTOR_DIM
});

const client = new MilvusClient({
  address: 'localhost:19530'
});

async function getEmbedding(text) {
  const result = await embeddings.embedQuery(text); //这里的 vector 字段需要用嵌入模型来向量化，向量化后才能insert到 Milvus 中
  return result;
}

async function main() {
  try {
    console.log('Connecting to Milvus...');
    await client.connectPromise;
    console.log('✓ Connected\n');

    // 创建集合
    console.log('Creating collection...');
    await client.createCollection({
      collection_name: COLLECTION_NAME,
      fields: [
        { name: 'id', data_type: DataType.VarChar, max_length: 50, is_primary_key: true },
        { name: 'vector', data_type: DataType.FloatVector, dim: VECTOR_DIM },//FloatVector 类型，也就是向量
        { name: 'content', data_type: DataType.VarChar, max_length: 5000 },
        { name: 'date', data_type: DataType.VarChar, max_length: 50 },
        { name: 'mood', data_type: DataType.VarChar, max_length: 50 },
        { name: 'tags', data_type: DataType.Array, element_type: DataType.VarChar, max_capacity: 10, max_length: 50 }
      ]
    });
    console.log('Collection created');

    // 创建索引
    console.log('\nCreating index...');
    await client.createIndex({
      collection_name: COLLECTION_NAME,
      field_name: 'vector',
      index_type: IndexType.IVF_FLAT, //IVF 可以先理解成“倒排文件式的向量分组索引思想” 核心直觉是“先粗分组，再细搜索”，FLAT 是一种最简单的索引类型，直接在每个分组内进行暴力搜索
      metric_type: MetricType.COSINE, //metric_type 指定用余弦相似度作为距离度量
      params: { nlist: 1024 } //向量粗分组时分成多少个列表 / 桶 / 聚类单元
    });
    console.log('Index created');

    // 加载集合
    console.log('\nLoading collection...');
    await client.loadCollection({ collection_name: COLLECTION_NAME });
    console.log('Collection loaded');

    // 插入日记数据
    console.log('\nInserting diary entries...');
    const diaryContents = [
      {
        id: 'diary_001',
        content: '今天天气很好，去公园散步了，心情愉快。看到了很多花开了，春天真美好。',
        date: '2026-01-10',
        mood: 'happy',
        tags: ['生活', '散步']
      },
      {
        id: 'diary_002',
        content: '今天工作很忙，完成了一个重要的项目里程碑。团队合作很愉快，感觉很有成就感。',
        date: '2026-01-11',
        mood: 'excited',
        tags: ['工作', '成就']
      },
      {
        id: 'diary_003',
        content: '周末和朋友去爬山，天气很好，心情也很放松。享受大自然的感觉真好。',
        date: '2026-01-12',
        mood: 'relaxed',
        tags: ['户外', '朋友']
      },
      {
        id: 'diary_004',
        content: '今天学习了 Milvus 向量数据库，感觉很有意思。向量搜索技术真的很强大。',
        date: '2026-01-12',
        mood: 'curious',
        tags: ['学习', '技术']
      },
      {
        id: 'diary_005',
        content: '晚上做了一顿丰盛的晚餐，尝试了新菜谱。家人都说很好吃，很有成就感。',
        date: '2026-01-13',
        mood: 'proud',
        tags: ['美食', '家庭']
      }
    ];

    console.log('Generating embeddings...');

    /** 这里的 diaryData 是一个数组，
     * 每个元素都是一个对象，包含了日记的内容、日期、心情、标签等字段，以及一个 vector 字段，
     * 这个 vector 字段是通过 getEmbedding 函数生成的向量表示。 
     * 
     * 这里就是通过map函数对 diaryContents 数组中的每个日记对象进行处理，生成一个新的对象，其中包含了原有的字段（通过 ...diary 复制过来）以及一个新的 vector 字段，
     * 这个 vector 字段是通过调用 getEmbedding 函数生成的。由于 getEmbedding 是一个异步函数，所以我们使用 Promise.all 来等待所有的向量生成完成后再继续执行插入操作。
     * */
    const diaryData = await Promise.all(
      diaryContents.map(async (diary) => ({
        ...diary, //其他字段直接复制过来
        vector: await getEmbedding(diary.content)
      }))
    );

    const insertResult = await client.insert({
      collection_name: COLLECTION_NAME,
      data: diaryData
    });
    console.log(`✓ Inserted ${insertResult.insert_cnt} records\n`);

  } catch (error) {
    console.error('Error:', error.message);
  }
}

main();