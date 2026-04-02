import "dotenv/config";
import { MilvusClient, MetricType } from '@zilliz/milvus2-sdk-node';
import { OpenAIEmbeddings } from "@langchain/openai";

const COLLECTION_NAME = 'ai_diary';
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
  const result = await embeddings.embedQuery(text);
  return result;
}

async function main() {
  try {
    console.log('Connecting to Milvus...');
    await client.connectPromise;
    console.log('✓ Connected\n');

    // 向量搜索
    console.log('Searching for similar diary entries...');
    const query = '我做饭或学习的日记';
    console.log(`Query: "${query}"\n`);

    //把提问的内容向量化
    const queryVector = await getEmbedding(query);

    const searchResult = await client.search({
      collection_name: COLLECTION_NAME,
      vector: queryVector,//把向量化后的提问内容传给 Milvus 来搜索数据库中的vector字段与queryVector向量相似的
      limit: 2, //最多返回 2 条最相似的结果
      metric_type: MetricType.COSINE,
      output_fields: ['id', 'content', 'date', 'mood', 'tags'] //告诉 Milvus：命中结果返回时，除了相似度分数，也把这些字段一起带回来。
    });

    console.log(`Found ${searchResult.results.length} results:\n`);
    searchResult.results.forEach((item, index) => {
      console.log(`${index + 1}. [Score: ${item.score.toFixed(4)}]`);
      console.log(`   ID: ${item.id}`);
      console.log(`   Date: ${item.date}`);
      console.log(`   Mood: ${item.mood}`);
      console.log(`   Tags: ${item.tags?.join(', ')}`);
      console.log(`   Content: ${item.content}\n`);
    });

  } catch (error) {
    console.error('Error:', error.message);
  }
}

main();