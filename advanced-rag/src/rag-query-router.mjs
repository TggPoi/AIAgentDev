import "dotenv/config";
import { z } from "zod";
import { ChatOpenAI, OpenAIEmbeddings } from "@langchain/openai";
import { Annotation, END, START, StateGraph } from "@langchain/langgraph";
import { Milvus } from "@langchain/community/vectorstores/milvus";

/**
 * 简单路由RAG，判断问题复杂度，简单问题直接回答，复杂问题进行检索后回答。
 */

const llm = new ChatOpenAI({
  temperature: 0,
  model: "qwen-plus",
  configuration: {
      baseURL: process.env.OPENAI_BASE_URL,
  },
  apiKey: process.env.OPENAI_API_KEY,
});

const embeddings = new OpenAIEmbeddings({
  model: "text-embedding-v4",
  dimensions: 1024,
  configuration: { 
    baseURL: process.env.OPENAI_BASE_URL 
  },
  apiKey: process.env.OPENAI_API_KEY,
});

const GraphState = Annotation.Root({
  question: Annotation,
  k: Annotation,
  strategy: Annotation,
  routeReason: Annotation,
  documents: Annotation,
  generation: Annotation,
});

let vectorStore;

// 定义一个函数来检索与用户问题相关的内容，返回包含相似度分数和文档内容的对象数组
async function retrieveRelevantContent(question, k) {
  try {
    const docsWithScores = await vectorStore.similaritySearchWithScore(question, k);
    return docsWithScores.map(([doc, score]) => ({
      score,
      content: doc.pageContent,
      id: doc.metadata?.id ?? "unknown",
      book_id: doc.metadata?.book_id ?? "未知",
      chapter_num: doc.metadata?.chapter_num ?? "未知",
      index: doc.metadata?.index ?? "未知",
    }));
  } catch (error) {
    console.error("检索内容时出错:", error.message);
    return [];
  }
}

const RouteSchema = z.object({
  strategy: z.enum(["simple", "complex"]),
  reason: z.string(),
});

// 路由问题节点：判断用户问题的复杂度，决定是否需要外部检索
const routeQuestionNode = async (state) => {
  console.log("---ROUTE_QUESTION---");
  //绑定LLM输出格式，确保输出符合预期的结构
  const router = llm.withStructuredOutput(RouteSchema);

  const route = await router.invoke(`
你是问答路由器。请判断用户问题是否需要外部检索。

规则：
- simple: 常识问答、简短定义、无需特定小说细节即可回答。
- complex: 需要《天龙八部》具体情节、人物关系、章节事实、原文细节或证据支持。

用户问题：${state.question}
`);

  console.log(`路由策略: ${route.strategy} (${route.reason})`);

  return {
    question: state.question,
    k: state.k,
    strategy: route.strategy,
    routeReason: route.reason,
  };
};

// 检索milvus节点，基于用户问题检索相关内容
const retrieveNode = async (state) => {

  console.log("---RETRIEVE---");
  const documents = await retrieveRelevantContent(state.question, state.k);

  if (documents.length === 0) {
    console.log("RETRIEVE结果: 未命中文档");
  } else {
    console.log(`RETRIEVE结果: 命中 ${documents.length} 条`);

    //整理检索文档格式，如果内容过长则截取前120个字符作为预览，并显示相似度分数、章节信息等元数据
    documents.forEach((item, i) => {
      const preview =
        item.content.length > 120 ? `${item.content.substring(0, 120)}...` : item.content;
      console.log(
        `[R${i + 1}] score=${Number(item.score).toFixed(4)} chapter=${item.chapter_num} index=${item.index}`,
      );

      console.log(`      ${preview}`);
    });
  }

  return {
    question: state.question,
    k: state.k,
    strategy: state.strategy,
    routeReason: state.routeReason,
    documents,
  };
};

// 直接回答节点，基于用户问题直接生成回答，不依赖外部检索内容
const directAnswerNode = async (state) => {
  console.log("---DIRECT_ANSWER---");
  process.stdout.write("\n【AI 回答（流式）】\n");
  let generation = "";
  const stream = await llm.stream(`你是一个中文问答助手，请直接简洁回答问题。

问题：${state.question}
`);
  for await (const chunk of stream) {
    const text = typeof chunk.content === "string" ? chunk.content : "";
    if (!text) continue;
    generation += text;
    process.stdout.write(text);
  }
  process.stdout.write("\n");

  return {
    question: state.question,
    k: state.k,
    strategy: state.strategy,
    routeReason: state.routeReason,
    documents: [],
    generation,
  };
};

//根据检索到的内容和用户问题进行回答
const ragGenerateNode = async (state) => {
  console.log("---RAG_GENERATE---");
  
  const context = state.documents
    .map(
      (item, i) =>
        `[片段 ${i + 1}]
章节: 第 ${item.chapter_num} 章
内容: ${item.content}`,
    )
    .join("\n\n━━━━━\n\n");
  process.stdout.write("\n【AI 回答（流式）】\n");
  let generation = "";
  const stream = await llm.stream(`你是一个专业的《天龙八部》小说助手。基于小说内容回答问题，用准确、详细的语言。

请根据以下《天龙八部》小说片段内容回答问题：
${context || "（未检索到相关内容）"}

用户问题: ${state.question}

回答要求：
1. 如果片段中有相关信息，请结合小说内容给出详细、准确的回答
2. 可以综合多个片段的内容，提供完整的答案
3. 如果片段中没有相关信息，请如实告知用户
4. 回答要准确，符合小说的情节和人物设定
5. 可以引用原文内容来支持你的回答

AI 助手的回答:`);
  for await (const chunk of stream) {
    const text = typeof chunk.content === "string" ? chunk.content : "";
    if (!text) continue;
    generation += text;
    process.stdout.write(text);
  }

  process.stdout.write("\n");

  return {
    question: state.question,
    k: state.k,
    strategy: state.strategy,
    routeReason: state.routeReason,
    documents: state.documents,
    generation,
  };
};

//决定下一步节点的函数，根据路由策略决定是直接回答还是进行检索
function decideNext(state) {
  return state.strategy === "simple" ? "direct_answer" : "retrieve";
}

const graph = new StateGraph(GraphState)
  .addNode("route_question", routeQuestionNode)
  .addNode("direct_answer", directAnswerNode)
  .addNode("retrieve", retrieveNode)
  .addNode("rag_generate", ragGenerateNode)
  .addEdge(START, "route_question")
  //对用户提问进行路由，根据策略决定下一步是直接回答还是检索
  .addConditionalEdges("route_question", decideNext, {
    direct_answer: "direct_answer",
    retrieve: "retrieve",
  })
  .addEdge("retrieve", "rag_generate")
  .addEdge("direct_answer", END)
  .addEdge("rag_generate", END)
  .compile();

async function main() {
  //这个问题会触发检索，但是如果直接问蛋羹的做法，不会去检索，会由大模型直接回答
  //const question = "雁门关事件的主谋，他的儿子最终结局是什么？";
  const question = "蛋羹的简易做法";
  const k = 5;

  // 导出为 Mermaid：可复制到 https://mermaid.live 或 Markdown 的 ```mermaid 代码块
  const drawable = await graph.getGraphAsync();
  const mermaid = drawable.drawMermaid({ withStyles: true });
  console.log(mermaid);

  console.log("连接到 Milvus...");

  vectorStore = await Milvus.fromExistingCollection(embeddings, {
    collectionName: "ebook_collection",
    url: "localhost:19530",
    textField: "content",
    primaryField: "id",
    vectorField: "vector",
    indexCreateOptions: {
      metric_type: "COSINE",
      index_type: "HNSW",
      params: { M: 16, efConstruction: 200 },
      search_params: { ef: 64 },
    },
  });

  vectorStore.indexSearchParams = { metric_type: "COSINE", params: JSON.stringify({ ef: 64 }) };
  console.log("✓ 已连接\n");

  try {
    await vectorStore.client.loadCollection({ collection_name: "ebook_collection" });
    console.log("✓ 集合 ebook_collection 已加载\n");

  } catch (error) {
    if (!error.message.includes("already loaded")) {
      throw error;
    }
    console.log("✓ 集合 ebook_collection 已处于加载状态\n");
  }

  console.log("=".repeat(80));
  console.log(`问题: ${question}`);
  console.log("=".repeat(80));

  const result = await graph.invoke({
    question,
    k: Number.isFinite(k) ? k : 5,
    strategy: "",
    routeReason: "",
    documents: [],
    generation: "",
  });

  if (result.strategy === "complex") {
    console.log("\n【检索相关内容】");

    if (result.documents.length === 0) {
      console.log("未找到相关内容");

    } else {
      result.documents.forEach((item, i) => {
        console.log(`\n[片段 ${i + 1}] 相似度: ${item.score.toFixed(4)}`);
        console.log(`书籍: ${item.book_id}`);
        console.log(`章节: 第 ${item.chapter_num} 章`);
        console.log(`片段索引: ${item.index}`);
        console.log(
          `内容: ${item.content.substring(0, 200)}${item.content.length > 200 ? "..." : ""}`,
        );
      });
    }
  }

  console.log(`\n最终策略: ${result.strategy}`);
  
  if (!result.generation?.trim()) {
    console.log("模型未返回内容。");
  }
}

main()


/**
 * PS D:\AI_Agent_Project\advanced-rag> node .\src\rag-query-router.mjs      
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        route_question(route_question)
        direct_answer(direct_answer)
        retrieve(retrieve)
        rag_generate(rag_generate)
        __end__([<p>__end__</p>]):::last
        __start__ --> route_question;
        direct_answer --> __end__;
        rag_generate --> __end__;
        retrieve --> rag_generate;
        route_question -.-> direct_answer;
        route_question -.-> retrieve;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

连接到 Milvus...
✓ 已连接

✓ 集合 ebook_collection 已加载

================================================================================
问题: 雁门关事件的主谋，他的儿子最终结局是什么？
================================================================================
---ROUTE_QUESTION---
路由策略: complex (问题涉及《天龙八部》核心情节‘雁门关事件’的主谋身份（需确认是萧远山而非慕容博，因原著中慕容博伪作契丹武士、嫁祸萧远山，实为幕后煽动者；而萧远山是受害者兼后续复仇者，主谋应为慕容博），以及该主谋之子（慕容复）的最终结局（疯癫、坐于土坟上幻想称帝）。二者均需依据小说具体人物关系、关键情节走向及结局描写（第四十八回等），无法仅凭常识或泛泛定义回答，必须援引原著事实。)
---RETRIEVE---
RETRIEVE结果: 命中 5 条
[R1] score=0.0237 chapter=105 index=15
      慕容复最后才和段誉相见，话道：“段兄，你好。”段誉神色惨然，摇头道：“你才好了，我……我一点儿也不好。”王语嫣“啊”的一声，道：“段公子，你也在这里。”段誉道：“是，我……我……”慕容复向他瞪了几眼，不再理睬，走到棋局之旁，拈起白子，下在棋...
[R2] score=0.0221 chapter=111 index=9
      善于“锁喉枪”的，挺枪去刺慕容复咽喉，给他“斗转星移”一转，这一枪便刺入了自己咽喉，而所用劲力法门，全是出于他本门的秘传诀窍；善用“断臂刀”的，挥刀砍出，却砍上了自己手臂。兵器便是这件兵器，招数便是这记招数。只要不是亲眼目睹慕容氏施这“斗转...
[R3] score=0.0180 chapter=39 index=43
      本因方丈道：“如何徒具虚名，倒要领教。”鸠摩智道：“当年慕容先生所钦仰的，是六脉神剑的剑法，并不是六脉神剑的剑阵。天龙寺的这座剑阵固然威力甚大，但充其量，也只和少林寺的罗汉剑阵、昆仑派的混沌剑阵相伯仲而已，似乎算不得是天下无双的剑法。”他说...
[R4] score=0.0162 chapter=39 index=25
      大轮明王道：“得罪！”举步进了堂中，向枯荣大师合十为礼，说道：“吐蕃国晚辈鸠摩智，参见前辈大师。有常无常，双树枯荣，南北西东，非假非空！”

段誉寻思：“这四句偈言是甚么意思？”枯荣大师却心中一惊：“大轮明王博学精深，果然名不虚传。他一见面...
[R5] score=0.0146 chapter=111 index=10
      他转是转了，移也移了，不过是转移到了第三者身上。丁春秋暗施“逍遥三笑散”，弹杯送毒，逼射毒酒，每一次都给慕容复轻轻易易的找了替死鬼。

待得丁春秋使到“化功大法”，慕容复已然无法将之移转，恰好那星宿弟子急于献媚讨好，张口一呼，显示了身形所在...
---RAG_GENERATE---

【AI 回答（流式）】
片段中**没有提及雁门关事件的主谋及其儿子的任何信息**。

雁门关事件是《天龙八部》全书最核心的悲剧性前史：北宋年间，以少林方丈玄慈为首，联合汪剑通（丐帮帮主）、智光大师、赵钱孙、谭公谭婆、单正等二十余位中原武林高手，受“契丹武士作乱中原”的虚假情报蒙蔽，在雁门关外伏击一支契丹萧氏商旅队伍，导致萧远山一家惨遭屠戮——萧远山之妻被杀、襁褓中的幼子萧峰（即后来的乔峰）被夺走，萧远山本人跳崖诈死，隐忍三十年后归来复仇。

该事件的**主谋实为玄慈方丈**（时任少林方丈，亦是带头大哥），而**他的儿子正是虚竹**——当年玄慈与叶二娘私通所生，婴儿期即被叶二娘盗走，辗转流落少林，成为少林寺一名地位低微的小沙弥，后因机缘巧合破解珍珑棋局、继承无崖子七十年内力与逍遥派掌门之位，并最终成为灵鹫宫主人、逍遥派正宗传人。

但以上全部关键情节（雁门关事件始末、玄慈身份、虚竹身世）**均未出现在所提供的五个片段中**。  
- 片段1讲慕容复与鸠摩智对弈及“逐鹿中原”之讽；  
- 片段2详述“斗转星移”的原理与实战局限；  
- 片段3、4聚焦鸠摩智挑战天龙寺、六脉神剑与枯荣禅理；  
- 片段5描写慕容复对阵丁春秋时以“移转”之术嫁祸星宿弟子。

**五处原文均未出现“雁门关”“玄慈”“萧远山”“乔峰”“虚竹身世”“叶二娘”等任何相关字眼或暗示**。因此，依据用户明确限定的“根据以下《天龙八部》小说片段内容回答问题”的要求，必须严格恪守文本边界。

✅ 正确结论：  
**所提供的五个片段中，完全没有涉及雁门关事件的主谋（玄慈方丈）及其儿子（虚竹）的相关信息，因此无法从中得出答案。**

（注：若脱离给定片段，依全书情节，答案应为：主谋是玄慈方丈，其子虚竹最终成为灵鹫宫主人、逍遥派掌门、西夏驸马，并与段誉、乔峰并列为全书三大主角之一，结局圆满。但此属外部知识，不符合本题“基于以下片段”的硬性要求。）

【检索相关内容】

[片段 1] 相似度: 0.0237
书籍: 1
章节: 第 105 章
片段索引: 15
内容: 慕容复最后才和段誉相见，话道：“段兄，你好。”段誉神色惨然，摇头道：“你才好了，我……我一点儿也不好。”王语嫣“啊”的一声，道：“段公子，你也在这里。”段誉道：“是，我……我……”慕容复向他瞪了几眼，不再理睬，走到棋局之旁，拈起白子，下在棋局之中。鸠摩智微微一笑，说道：“慕容公子，你武功虽强，这弈道只怕也是平常。”说着下了一枚黑子。慕容复道：“未必便输于你。”说着下了一枚白子。鸠摩智应了一着。

...

[片段 2] 相似度: 0.0221
书籍: 1
章节: 第 111 章
片段索引: 9
内容: 善于“锁喉枪”的，挺枪去刺慕容复咽喉，给他“斗转星移”一转，这一枪便刺入了自己咽喉，而所用劲力法门，全是出于他本门的秘传诀窍；善用“断臂刀”的，挥刀砍出，却砍上了自己手臂。兵器便是这件兵器，招数便是这记招数。只要不是亲眼目睹慕容氏施这“斗转星移”之术，那就谁也猜想不到这些人所以丧命，其实都是出于“自杀”。出手的人武功越高，死法越是巧妙。慕容氏若非单打独斗，若不是有把握定能致敌死命，这“斗转星移”的...

[片段 3] 相似度: 0.0180
书籍: 1
章节: 第 39 章
片段索引: 43
内容: 本因方丈道：“如何徒具虚名，倒要领教。”鸠摩智道：“当年慕容先生所钦仰的，是六脉神剑的剑法，并不是六脉神剑的剑阵。天龙寺的这座剑阵固然威力甚大，但充其量，也只和少林寺的罗汉剑阵、昆仑派的混沌剑阵相伯仲而已，似乎算不得是天下无双的剑法。”他说这是“剑阵”而非“剑法”，是指摘对方六人一齐动手，排下阵势，并不是一个人使动六脉神剑，便如他使火焰刀一般。

本因方丈觉得他所说确然有理，无话可驳。本参却冷笑道...

[片段 4] 相似度: 0.0162
书籍: 1
章节: 第 39 章
片段索引: 25
内容: 大轮明王道：“得罪！”举步进了堂中，向枯荣大师合十为礼，说道：“吐蕃国晚辈鸠摩智，参见前辈大师。有常无常，双树枯荣，南北西东，非假非空！”

段誉寻思：“这四句偈言是甚么意思？”枯荣大师却心中一惊：“大轮明王博学精深，果然名不虚传。他一见面便道破了我所参枯禅的来历。”

世尊释迦牟尼当年在拘户那城婆罗双树之间入灭，东西南北，各有双树，每一面的两株树都是一荣一枯，称之为“四枯四荣”，据佛经中言道：东...

[片段 5] 相似度: 0.0146
书籍: 1
章节: 第 111 章
片段索引: 10
内容: 他转是转了，移也移了，不过是转移到了第三者身上。丁春秋暗施“逍遥三笑散”，弹杯送毒，逼射毒酒，每一次都给慕容复轻轻易易的找了替死鬼。

待得丁春秋使到“化功大法”，慕容复已然无法将之移转，恰好那星宿弟子急于献媚讨好，张口一呼，显示了身形所在。

慕容复情急之下，无暇多想，一将那星宿弟子抓到，立时旁拨侧挑，推气换劲，将他换作了自身。他冒险施展，竟然生效，星宿老怪本意在“化”慕容复之“功”，岂知化去的...

最终策略: complex
 */


/**
 * PS D:\AI_Agent_Project\advanced-rag> node .\src\rag-query-router.mjs
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        route_question(route_question)
        direct_answer(direct_answer)
        retrieve(retrieve)
        rag_generate(rag_generate)
        __end__([<p>__end__</p>]):::last
        __start__ --> route_question;
        direct_answer --> __end__;
        rag_generate --> __end__;
        retrieve --> rag_generate;
        route_question -.-> direct_answer;
        route_question -.-> retrieve;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

连接到 Milvus...
✓ 已连接

✓ 集合 ebook_collection 已加载

================================================================================
问题: 蛋羹的简易做法
================================================================================
---ROUTE_QUESTION---
路由策略: simple (问题与《天龙八部》无关，属于生活常识类烹饪问题，无需小说相关检索。)
---DIRECT_ANSWER---

【AI 回答（流式）】
鸡蛋打散，加1.5倍温水（约40℃）和少许盐搅匀，过筛去泡；盖保鲜膜扎孔，水开后上锅中火蒸10–12分钟，关火焖2分钟即可。

最终策略: simple
 */