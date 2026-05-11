import 'dotenv/config'
import { Neo4jGraph } from '@langchain/community/graphs/neo4j_graph'
import { ChatOpenAI } from '@langchain/openai'
import { StateGraph, END, START } from '@langchain/langgraph'
import { HumanMessage } from '@langchain/core/messages'

// ----------------------
// 连接 Neo4j 知识图谱
// ----------------------
const graph = new Neo4jGraph({
  url: 'bolt://localhost:7687',
  username: 'neo4j',
  password: '12345678',
})

// ----------------------
// 大模型
// ----------------------
const llm = new ChatOpenAI({
  model: process.env.MODEL_NAME,
  temperature: 0,
  configuration: { baseURL: process.env.OPENAI_BASE_URL }
})

// ----------------------
// 定义状态
// ----------------------
const state = {
  messages: {
    value: (left, right) =>
      left.concat(Array.isArray(right) ? right : [right]),
    default: () => [],
  },
  cypher: null,
  context: null,
  answer: null,
}

function userQuery(state) {
  const last = state.messages[state.messages.length - 1]
  return last.content
}

// ----------------------
// 步骤1：生成 Cypher
// ----------------------
async function generateCypher(state) {
    const prompt = `
      你是一个专业的 Neo4j Cypher 生成器。
      严格按照下面的结构生成正确语句，只返回纯 Cypher 代码，不要任何解释、不要标点、不要 markdown。
  
      节点：
      - Product: 奶茶产品
      - Ingredient: 配料
      - Type: 奶茶类型
      - Method: 制作工艺
      - People: 适合人群
  
      关系方向（必须严格遵守）：
      - (Product)-[:属于]->(Type)
      - (Product)-[:包含]->(Ingredient)
      - (Product)-[:适合]->(People)
      - (Ingredient)-[:使用]->(Method)
  
      规则：
      1. 关系方向绝对不能反
      2. 多跳查询请使用多个 MATCH，不要连错路径
      3. 只返回最终可运行的 Cypher 语句
  
      用户问题：${userQuery(state)}
    `
    const res = await llm.invoke([new HumanMessage(prompt)])
    return { cypher: res.content }
  }

// ----------------------
// 步骤2：执行图查询
// ----------------------
async function executeGraphQuery(state) {
  try {
    const res = await graph.query(state.cypher)
    return { context: JSON.stringify(res) }
  } catch (e) {
    return { context: '未查询到相关知识' }
  }
}

// ----------------------
// 步骤3：生成答案
// ----------------------
async function generateAnswer(state) {
  const prompt = `
    你是奶茶专家，根据下方「检索结果」回答用户问题；检索结果为空或不足时简要说明无法从图谱得到答案，不要编造。
    回答要求：
    - 直接列出事实，不要推断图谱里未出现的配料（如水、冰、添加剂等）。

    检索结果：${state.context}
    用户问题：${userQuery(state)}
  `
  const res = await llm.invoke([new HumanMessage(prompt)])
  return { answer: res.content }
}

// ----------------------
// 构建 LangGraph 工作流
// ----------------------
const workflow = new StateGraph({ channels: state })
  .addNode('generateCypher', generateCypher)
  .addNode('executeGraph', executeGraphQuery)
  .addNode('generateAnswer', generateAnswer)

  .addEdge(START, 'generateCypher')
  .addEdge('generateCypher', 'executeGraph')
  .addEdge('executeGraph', 'generateAnswer')
  .addEdge('generateAnswer', END)

const app = workflow.compile()

async function printWorkflowMermaid() {
  const drawable = await app.getGraphAsync()
  const mermaid = drawable.drawMermaid({ withStyles: true })
  console.log('--- LangGraph 工作流 (Mermaid) ---')
  console.log(mermaid)
  console.log('-----------------------------------------------------------')
}

// ----------------------
// 运行 GraphRAG
// ----------------------
async function runGraphRAG(question) {
  const res = await app.invoke({
    messages: [new HumanMessage(question)],
  })

  console.log('======================================')
  console.log('用户问题：', question)
  console.log('生成 Cypher：', res.cypher)
  console.log('检索结果：', res.context)
  console.log('最终回答：', res.answer)
  console.log('======================================')
}

// ======================
// 测试
// ======================
;(async () => {
  await printWorkflowMermaid()
  await Promise.all([
    runGraphRAG('我们这款珍珠奶茶有哪些配料？'),
    runGraphRAG('台式奶茶的饮品都有哪些配料？'),
    runGraphRAG('珍珠奶茶适合哪些人群饮用？'),
  ])
})().catch(console.error)


/**
 * PS D:\AI_Agent_Project\neo4j-graphrag> node .\src\graphrag.mjs
--- LangGraph 工作流 (Mermaid) ---
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        generateCypher(generateCypher)
        executeGraph(executeGraph)
        generateAnswer(generateAnswer)
        __end__([<p>__end__</p>]):::last
        __start__ --> generateCypher;
        executeGraph --> generateAnswer;
        generateAnswer --> __end__;
        generateCypher --> executeGraph;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

-----------------------------------------------------------
======================================
用户问题： 我们这款珍珠奶茶有哪些配料？
生成 Cypher： MATCH (p:Product {name: "珍珠奶茶"})-[:包含]->(i:Ingredient) RETURN i.name
检索结果： [{"i.name":"珍珠"},{"i.name":"果糖"},{"i.name":"红茶"},{"i.name":"牛奶"}]
最终回答： 珍珠、果糖、红茶、牛奶
======================================
======================================
用户问题： 珍珠奶茶适合哪些人群饮用？
生成 Cypher： MATCH (p:Product {name: "珍珠奶茶"})-[:适合]->(peo:People) RETURN peo.name
检索结果： [{"peo.name":"年轻人"},{"peo.name":"学生"},{"peo.name":"甜食爱好者"}]
最终回答： - 年轻人  
- 学生  
- 甜食爱好者
======================================
======================================
用户问题： 台式奶茶的饮品都有哪些配料？
生成 Cypher： MATCH (t:Type {name: "台式奶茶"})<-[:属于]-(p:Product)-[:包含]->(i:Ingredient) RETURN i.name
检索结果： [{"i.name":"牛奶"},{"i.name":"红茶"},{"i.name":"果糖"},{"i.name":"珍珠"}]
最终回答： 台式奶茶的配料包括：牛奶、红茶、果糖、珍珠。
======================================
 */