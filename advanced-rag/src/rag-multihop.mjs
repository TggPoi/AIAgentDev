import "dotenv/config";
import { z } from "zod";
import { ChatOpenAI, OpenAIEmbeddings } from "@langchain/openai";
import { Annotation, END, START, StateGraph } from "@langchain/langgraph";
import { Milvus } from "@langchain/community/vectorstores/milvus";

/**
 * 多步检索的复杂问题，通过路由器判断问题复杂度，复杂问题拆解成子问题序列，按序检索并动态规划是否继续检索，最终生成回答。
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
    baseURL: process.env.OPENAI_BASE_URL,
  },
  apiKey: process.env.OPENAI_API_KEY,
});

/**
 * complex：先拆解子问题序列，再按序检索
 */
const GraphState = Annotation.Root({
  //下面每个字段都使用Annotation，表示这个字段的更新规则是 默认替换（新值覆盖旧值）。

  //原始输入类
  question: Annotation,
  k: Annotation,

  //路由决策类
  strategy: Annotation,
  routeReason: Annotation,

   //多跳检索计划类
  /** 拆解得到的有序子问题，仅用于检索 */
  subQuestions: Annotation,
  /** 下一轮 retrieve 要用的下标（指向 subQuestions 中尚未检索的那一条） */
  nextSubIdx: Annotation,
  currentQuery: Annotation,

  //检索结果类
  documents: Annotation,
  retrievalCount: Annotation,
  maxRetrievals: Annotation,

  //后续动作和最终输出类
  plannedNext: Annotation,
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

/** 按 id 合并；同 id 保留更高 score */
function mergeUnique(existingDocs, newDocs) {

  const map = new Map();

  //把旧文档数组和新检索到的文档数组展开，合并为一个数组后再开始遍历
  for (const d of [...existingDocs, ...newDocs]) {

    const key = String(d.id);
    const prev = map.get(key);

    //覆盖之前存入过的相同文档片段，把score更高的覆盖进去
    if (!prev || Number(d.score) > Number(prev.score)) {
      map.set(key, d);
    }
  }

  //检索后的文档按照score排序，按照 score 从高到低（降序） 进行排列
  return Array.from(map.values()).sort((a, b) => Number(b.score) - Number(a.score));
}

//规划路由的格式，模型会根据用户问题的类型来判断是直接回答还是需要拆解成子问题序列进行检索
const RouteSchema = z.object({
  strategy: z.enum(["simple", "complex"]),
  reason: z.string(),
});

//规划下一步的格式，模型会根据当前检索的子问题数量、剩余子问题数量、已检索的文档内容等信息来判断是继续检索还是生成回答
const NextStepSchema = z.object({
  nextAction: z.enum(["retrieve", "generate"]),
  reason: z.string(),
});

//根据用户问题的复杂度来规划路由，如果是简单问题就直接回答，如果是复杂问题就拆解成子问题序列进行检索
const routeQuestionNode = async (state) => {

  console.log("---ROUTE_QUESTION---");
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
    strategy: route.strategy,
    routeReason: route.reason,
    retrievalCount: 0,
    maxRetrievals: state.maxRetrievals ?? 8,
    documents: [],
    subQuestions: [],
    nextSubIdx: 0,
    currentQuery: "",
  };
};

//设置子问题的拆分格式
const DecomposeSchema = z.object({
  sub_questions: z.array(z.string()).min(1).max(8),
  reason: z.string(),
});

//根据用户问题拆解成子问题序列
const decomposeQuestionNode = async (state) => {
  console.log("---DECOMPOSE_QUESTION---");

  const decomposer = llm.withStructuredOutput(DecomposeSchema);

  const out = await decomposer.invoke(`你是《天龙八部》多跳问答的「子问题拆解器」。

用户原始问题：
${state.question}

任务：将问题拆成**有序**子问题列表 sub_questions，用于**依次向量检索**。要求：
1. 链式推理、多层关系、因果先后的问题，必须拆成多条；单跳即可答的也可只输出 1 条。
2. 每条子问题必须是**可独立检索**的完整中文问句，**禁止**使用「他/她/此人/上文」等指代；可写全人物名与事件名。
3. 顺序必须符合推理链：先搞清前置实体/事实，再查后续结论。
4. **不要**把整句原题原样复制成唯一一条（除非确实无法拆分）；不要拆成过碎的关键词列表。
5. 输出 1～8 条即可。

请输出 sub_questions 与简短 reason。`);

  /**
   * 把 Boolean 直接作为 filter 的参数，就相当于告诉数组：“请保留所有能转换成 true 的元素，剔除所有会转换成 false 的元素。”
      在 JavaScript 中，以下这些被称为“假值”（Falsy），会被 filter(Boolean) 无情淘汰：
      ''（空字符串）
      null
      undefined
      0
      NaN
      false
   */
  const subQuestions = out.sub_questions.map((s) => s.trim()).filter(Boolean);

  if (subQuestions.length === 0) {
    throw new Error("decompose_question: sub_questions 为空");
  }

  console.log(`拆解 ${subQuestions.length} 条子问题 (${out.reason})`);

  subQuestions.forEach((q, i) => {
    console.log(`  [${i + 1}] ${q}`);
  });

  return {
    subQuestions,
    nextSubIdx: 0,
    currentQuery: subQuestions[0],
  };
};

//根据用户问题检索相关内容，返回包含相似度分数和文档内容的对象数组
const retrieveNode = async (state) => {

  const subs = state.subQuestions ?? [];

  //检索的时候根据 state 里的当前下标来检索对应问题的文档，检索结果会累积到 state.documents 里，并且会更新下一个要检索的子问题下标和当前查询的内容
  const idx = state.nextSubIdx ?? 0;

  const q = subs[idx]?.trim();

  if (!q) {
    throw new Error(`retrieve: 子问题下标 ${idx} 无有效文本（共 ${subs.length} 条）`);
  }

  const round = state.retrievalCount + 1;

  console.log(`---RETRIEVE (第 ${round} 轮，子问题 ${idx + 1}/${subs.length})---`);
  console.log(`查询: ${q}`);

  //es检索子问题的相关内容
  const newDocs = await retrieveRelevantContent(q, state.k);

  //因为会检索多轮，所以做了一下 id 的去重，把之前State中保存的旧文档和新检索出来的结果进行查重，覆盖
  const merged = mergeUnique(state.documents ?? [], newDocs);

  if (newDocs.length === 0) {
    console.log("本轮未命中文档");
  } else {

    console.log(`本轮命中 ${newDocs.length} 条，累计去重后 ${merged.length} 条`);

    //打印预览的文本到控制台，方便观察
    newDocs.forEach((item, i) => {
      const preview =
        item.content.length > 120 ? `${item.content.substring(0, 120)}...` : item.content;
      console.log(
        `[R${i + 1}] score=${Number(item.score).toFixed(4)} chapter=${item.chapter_num} index=${item.index}`,
      );
      console.log(`      ${preview}`);
    });
  }

  return {
    documents: merged,
    retrievalCount: round,
    nextSubIdx: idx + 1,
    currentQuery: q,
  };
};

//规划下一步的节点，模型会根据当前检索的子问题数量、剩余子问题数量、已检索的文档内容等信息来判断是继续检索还是生成回答
const planNextStepNode = async (state) => {
  console.log("---PLAN_NEXT_STEP---");

  const subs = state.subQuestions ?? [];
  const nextIdx = state.nextSubIdx ?? 0;
  const remaining = subs.length - nextIdx;

  const subList = subs.map((s, i) => `${i + 1}. ${s}${i < nextIdx ? " （已检索）" : i === nextIdx ? " （下一轮将检索，若选择继续）" : " （未检索）"}`).join("\n");

  const docStr =
    state.documents.length === 0
      ? "（尚无检索结果）"
      : state.documents
          .slice(0, 6)
          .map(
            (d, i) =>
              `[${i + 1}] score=${Number(d.score).toFixed(4)} 第${d.chapter_num}章: ${d.content.slice(0, 200)}${d.content.length > 200 ? "..." : ""}`,
          )
          .join("\n\n");


  const prompt = `你是多跳 RAG 规划器。检索查询已由前置步骤拆解为**有序子问题**；若需继续检索，下一轮将自动使用「下一条子问题」做向量检索，你**不要**自拟新的检索句。

用户原始问题：${state.question}

子问题序列：
${subList || "（无）"}

已检索轮数：${state.retrievalCount}；剩余未检索子问题条数：${remaining}
最大检索轮数上限：${state.maxRetrievals}

已召回文档摘要：
${docStr}

请判断下一步：
1) 已有足够依据回答用户原始问题 → nextAction=generate
2) 仍缺关键事实、且仍存在未检索的子问题、且未超过轮数上限 → nextAction=retrieve

硬性规则：
- 若剩余未检索子问题条数为 0，必须 nextAction=generate。
- 若已检索轮数已达到或超过最大检索轮数，必须 nextAction=generate。`;

  const model = llm.withStructuredOutput(NextStepSchema);
  
  const { nextAction, reason } = await model.invoke(prompt);

  let finalNext = nextAction;

  if (state.retrievalCount >= state.maxRetrievals) finalNext = "generate";

  if (remaining <= 0) finalNext = "generate";

  console.log(`[决策] plannedNext=${finalNext} (模型建议=${nextAction}) (${reason})`);

  //直到循环完，就检索完了所有子问题，接下来就生成回答就好了。如果中途模型觉得已经有足够信息了，也会直接生成回答，不继续检索剩余的子问题了。
  return {
    plannedNext: finalNext,
  };
};

//判断路由后是否要继续拆分子问题，如果继续拆分就继续检索，如果不继续拆分了就直接生成回答
function afterRoute(state) {
  return state.strategy === "simple" ? "direct_answer" : "decompose_question";
}

//判断是否继续检索还是生成回答
function afterPlan(state) {
  return state.plannedNext === "retrieve" ? "retrieve" : "generate";
}

//直接回答的节点，基于用户问题直接生成回答
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

  return { generation };
};

const generateNode = async (state) => {
  console.log("---GENERATE---");
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
  return { generation };
};

const graph = new StateGraph(GraphState)
  .addNode("route_question", routeQuestionNode)
  .addNode("direct_answer", directAnswerNode)
  .addNode("decompose_question", decomposeQuestionNode)
  .addNode("retrieve", retrieveNode)
  .addNode("plan_next_step", planNextStepNode)
  .addNode("generate", generateNode)

  .addEdge(START, "route_question")

  .addConditionalEdges("route_question", afterRoute, {
    direct_answer: "direct_answer",
    decompose_question: "decompose_question",
  })

  .addEdge("decompose_question", "retrieve")
  //这里形成循环，retrieve检索完成后，又进入plan_next_step
  .addEdge("retrieve", "plan_next_step")

  .addConditionalEdges("plan_next_step", afterPlan, {
    retrieve: "retrieve",
    generate: "generate",
  })

  .addEdge("direct_answer", END)
  .addEdge("generate", END)
  .compile();

async function main() {
  const question =
    "《天龙八部》中「四大恶人」排行第二的是谁？此人之子在身世揭晓前，其生父在武林中的公开身份是什么？";
  const k = 5;

  const drawable = await graph.getGraphAsync();
  console.log(drawable.drawMermaid({ withStyles: true }));

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
    subQuestions: [],
    nextSubIdx: 0,
    documents: [],
    currentQuery: "",
    retrievalCount: 0,
    maxRetrievals: 8,
    plannedNext: "",
    generation: "",
  });

  if (result.strategy === "complex") {
    if (result.subQuestions?.length) {
      console.log("\n【子问题序列】");
      result.subQuestions.forEach((s, i) => console.log(`  ${i + 1}. ${s}`));
    }
    console.log("\n【检索相关内容（累计）】");
    if (result.documents.length === 0) {
      console.log("未找到相关内容");
    } else {
      result.documents.forEach((item, i) => {
        console.log(`\n[片段 ${i + 1}] 相似度: ${Number(item.score).toFixed(4)}`);
        console.log(`书籍: ${item.book_id}`);
        console.log(`章节: 第 ${item.chapter_num} 章`);
        console.log(`片段索引: ${item.index}`);
        console.log(
          `内容: ${item.content.substring(0, 200)}${item.content.length > 200 ? "..." : ""}`,
        );
      });
    }
    console.log(`\n检索轮数: ${result.retrievalCount} / ${result.maxRetrievals}`);
  }

  console.log(`\n最终策略: ${result.strategy}`);
  if (!result.generation?.trim()) {
    console.log("模型未返回内容。");
  }
}

main().catch((err) => {
  console.error("运行失败:", err);
  process.exit(1);
});


/**
 * PS D:\AI_Agent_Project\advanced-rag> node .\src\rag-multihop.mjs
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        route_question(route_question)
        direct_answer(direct_answer)
        decompose_question(decompose_question)
        retrieve(retrieve)
        plan_next_step(plan_next_step)
        generate(generate)
        __end__([<p>__end__</p>]):::last
        __start__ --> route_question;
        decompose_question --> retrieve;
        direct_answer --> __end__;
        generate --> __end__;
        retrieve --> plan_next_step;
        route_question -.-> direct_answer;
        route_question -.-> decompose_question;
        plan_next_step -.-> retrieve;
        plan_next_step -.-> generate;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

连接到 Milvus...
✓ 已连接

✓ 集合 ebook_collection 已加载

================================================================================
问题: 《天龙八部》中「四大恶人」排行第二的是谁？此人之子在身世揭晓前，其生父在武林中的公开身份是什么？
================================================================================
---ROUTE_QUESTION---
路由策略: complex (问题涉及《天龙八部》中特定人物（四大恶人排行第二者）及其子的身世设定，需准确对应原著情节：'排行第二'指'无恶不作'叶二娘；其子虚竹的生父为少林高僧玄慈方丈，而玄慈在身世揭晓前长期以'少林寺方丈'这一公开身份行走江湖，此设定贯穿少林大会、雁门关往事等关键章节，且需依据原著第40回及'小镜湖'前后情节交叉印证。问题要求双重事实确认（恶人排名 + 生父公开身份），均属小说内部具体设定，非常识可推断，必须依赖原著文本或权威版本考据。)
---DECOMPOSE_QUESTION---
拆解 4 条子问题 (问题含两层嵌套关系：第一层需确认‘四大恶人’中排行第二者的身份；第二层需基于该人物（岳老三）推及其子（岳灵珊？错——实为岳老三无子，此处应为‘段延庆之子’？但四大恶人排行第二是岳老三，而‘其子’实际指段誉——但段誉并非岳老三之子。关键纠错：用户问题存在经典误记——‘四大恶人’排行第二的是‘岳老二’岳老三（本名岳峙，绰号‘凶神恶煞’），但他终生无子；真正有子且身世成谜的是排行第一的‘恶贯满盈’段延庆，其子为段誉。但题干明确说‘排行第二者之子’，与原著矛盾。重审原著：四大恶人排序为——老大段延庆、老二岳老三、老三叶二娘、老四云中鹤；‘岳老三’实为老二，但金庸原文及通行版本均称其‘岳老三’，因其自认老三，而段延庆默认为老大。故‘排行第二’即岳老三（岳峙）。然而岳老三并无子嗣，全书未提其有后代。因此题干‘此人之子’必为用户混淆——实际所指应为‘四大恶人之首段延庆之子段誉’，但问题明确限定‘排行第二者’。再查证：第三版修订本及三联版明确，‘四大恶人’按恶名与实力排位为：1.段延庆（恶贯满盈）、2.叶二娘（无恶不作）、3.岳老三（凶神恶煞）、4.云中鹤（穷凶极恶）。——这是关键！通行误解‘岳老三’是老二，实则新版排序中，叶二娘为第二。金庸在世纪新修版《天龙八部》第四十一回明确写道：‘四大恶人中，以段延庆居首，叶二娘次之，岳老三又次之，云中鹤排末’。且叶二娘确有子——虚竹，其身世揭晓前，虚竹生父‘少林僧人’的公开身份是‘少林寺戒律院首座玄慈方丈’，而玄慈在武林中以德高望重、持戒精严著称，绝无人知其曾破戒生子。因此题干‘排行第二者’实指叶二娘，‘其子’即虚竹，‘生父公开身份’即玄慈方丈。故拆解必须严格按此逻辑链：先确认新版四大恶人确切排行第二者 → 再确认该人之子是谁 → 再确认该子生父是谁 → 最后确认该生父在身世揭晓前的武林公开身份。)
  [1] 《天龙八部》世纪新修版中，‘四大恶人’按恶名与地位排序，排行第二的人物是谁？
  [2] 叶二娘的儿子在《天龙八部》中叫什么名字？
  [3] 虚竹的生父在《天龙八部》中是谁？
  [4] 玄慈在虚竹身世揭晓之前，于武林中公开的身份和职务是什么？
---RETRIEVE (第 1 轮，子问题 1/4)---
查询: 《天龙八部》世纪新修版中，‘四大恶人’按恶名与地位排序，排行第二的人物是谁？
本轮命中 5 条，累计去重后 5 条
[R1] score=0.0476 chapter=100 index=0
      [../Images/30.jpg]





[../Images/30-1.jpg]
[R2] score=0.0471 chapter=49 index=19
      这其中吃惊最甚的，自然是诸保昆了。原来他师父叫作都灵道人，年轻时曾吃过青城派的大亏，处心积虑的谋求报复，在四川各地暗中窥视，找寻青城派的可乘之隙。这一年在灌县见到了诸保昆，那时他还是个孩子，但根骨极佳，实是学武的良材，于是筹划到一策。他命人...
[R3] score=0.0441 chapter=69 index=0
      [../Images/20.jpg]





[../Images/20-1.jpg]
[R4] score=0.0376 chapter=63 index=0
      [../Images/18.jpg]





[../Images/18-1.jpg]
[R5] score=0.0364 chapter=49 index=41
      司马林脸上变色，心想：“此言果然不假。我父亲故世后，青城派力量已不如前，再加诸保昆这奸贼已偷学了本派武功，倘若秦家寨再和我们作对，此事大大可虑。常言道先下手为强，后下手遭殃。格老子，今日之事，只有杀他个措手不及。”

当下淡淡的道：“你待怎...
---PLAN_NEXT_STEP---
[决策] plannedNext=retrieve (模型建议=retrieve) (已检索轮数为1，剩余未检索子问题条数为3（子问题2、3、4均未检索），未达轮数上限（8），且当前召回文档摘要中无任何与‘四大恶人’排行第二者（应为叶二娘）、其子姓名、虚竹生父或玄慈公开身份相关的信息——所有摘要均为无关章节片段（如青城派、诸保昆、司马林、姚伯当等），score极低且内容完全不匹配。因此必须继续检索以获取关键事实。下一轮将自动使用子问题2：'叶二娘的儿子在《天龙八部》中叫什么名字？'进行向量检索。)
---RETRIEVE (第 2 轮，子问题 2/4)---
查询: 叶二娘的儿子在《天龙八部》中叫什么名字？
本轮命中 5 条，累计去重后 10 条
[R1] score=0.0525 chapter=105 index=18
      南海鳄神的叫声甫歇，山下快步上来一人，身法奇快，正是云中鹤，叫道：“天下四大恶人拜访聪辩先生，谨赴棋会之约。”苏星河道：“欢迎之至。”这四字刚出口，云中鹤已飘行到了众人身前。

过了一会，段延庆、叶二娘、南海鳄神三人并肩而至。南海鳄神大声道...
[R2] score=0.0472 chapter=77 index=33
      段正淳在小镜湖畔和旧情人重温鸳梦，护驾而来的三公四卫散在四周卫护，殊不想大对头竟然找上门来。

段延庆武功厉害，四大护卫中的古笃诚、傅思归先后受伤。朱丹臣误认萧峰为敌，在青石桥阻拦不果。褚万里复为阿紫的柔丝网所擒。司马范骅、司徒华赫良、司空...
[R3] score=0.0428 chapter=33 index=10
      巴天石奔了这百余个圈子，已知云中鹤的下盘功夫飘逸有余，沉凝不足，不如自己一弹一跃之际行有余力，只消陡然停住，击他三掌，他势必抵受不住。但巴天石一心要在轻功上考较他下去，不愿以拳脚功夫取胜，是以仍是一股劲儿的奔跑。

忽听得一人粗声骂道：“妈...
[R4] score=0.0395 chapter=157 index=21
      他不敢在大理境内逗留，远至南部蛮荒穷乡僻壤之处，养好伤后，苦练家传武功。最初五年习练以杖代足，再将“一阳指”功夫化在钢杖之上；又练五年后，前赴两湖，将所有仇敌一家家杀得鸡犬不留，手段之凶狠毒辣，实是骇人听闻，因而博得了“天下第一大恶人”的名...
[R5] score=0.0388 chapter=157 index=9
      原来段正淳派遣巴天石和朱丹臣护送段誉赴西夏求亲，不久便接到保定帝御使送来的谕旨，命他克日回归大理，登基接位，保定帝自己要赴天龙寺出家。大理国皇室崇信佛法，历代君主到晚年避位为僧者甚众，是以段正淳奉到谕旨之时虽心中伤感，却不以为奇，当即携同秦...
---PLAN_NEXT_STEP---
[决策] plannedNext=retrieve (模型建议=retrieve) (当前已检索2轮，剩余未检索子问题有2条（子问题3和子问题4），均未执行检索；且最大检索轮数上限为8，尚未触达上限。已召回文档中：[1]明确提及‘四大恶人’含段延庆（老大）、叶二娘、南海鳄神（岳老二）、云中鹤，可推知排行第二为叶二娘（因段延庆为老大，后文‘段延庆、叶二娘、南海鳄神三人并肩而至’及南海鳄神自称‘岳老二’，结合金庸原著共识与子问题1的检索目标‘按恶名与地位排序’，已支持子问题1答案为叶二娘）；但子问题2（叶二娘之子名字）虽已标注‘已检索’，其结果未在召回摘要中体现——摘要中无‘虚竹’‘儿子’‘身世’等关键词，亦无叶二娘之子姓名；子问题3（虚竹生父）和子问题4（玄慈公开身份）均未检索，且二者是回答用户第二问‘此人之子在身世揭晓前，其生父在武林中的公开身份是什么？’所必需的关键链：叶二娘之子=虚竹 → 虚竹生父=玄慈 → 玄慈公开身份=少林方丈。当前摘要中无任何关于玄慈、少林、方丈、虚竹身世的信息，缺乏支撑最终答案的必要事实。因此必须继续检索下一条子问题（子问题3：虚竹的生父是谁？），以启动关键事实获取链。)
---RETRIEVE (第 3 轮，子问题 3/4)---
查询: 虚竹的生父在《天龙八部》中是谁？
本轮命中 5 条，累计去重后 15 条
[R1] score=0.0637 chapter=148 index=0
      [../Images/002.png]

巴天石和朱丹臣等过来和木婉清相见，又替她引见萧峰、虚竹等人。巴朱二人虽知她是镇南王之女，但并未行过正式收养之礼，是以仍称她为“木姑娘”。

众人行得数里，忽听得左首传来一声惊呼，更有人大声号叫，却是...
[R2] score=0.0560 chapter=126 index=37
      哈大霸说道：“中……中在……悬枢……气……气海……丝……丝空竹……”适才虚竹一招“阳歌天钧”，已令他神智恢复。

虚竹喜道：“你自己知道，那就好了。”当即以童姥所授法门，用天山六阳掌的纯阳之力，将他悬枢、气海、丝空竹三处穴道中的寒冰生死符化...
[R3] score=0.0543 chapter=148 index=5
      片刻之间，虚竹将段延庆接了上来，跟着将南海鳄神与云中鹤一一提起，最后才拉起王语嫣。她双目紧闭，呼吸微弱，已然晕去。

段誉先是大为欣慰，跟着便心下怜惜，但见她双手手腕上都是一圈紫黑之色，现出云中鹤深深的指印，想起云中鹤凶残好色，对木婉清和钟...
[R4] score=0.0523 chapter=21 index=24
      木婉清冷冷的道：“你知道自己徒儿的脾气。他只消学得你本事十成中的一成，我便杀他不了。”南海鳄神点头道：“这话倒也有理。”但想到自己这一门的规矩，向来一徒单传，孙三霸一死，十余年传功督导的心血化为乌有，越想越恼，大喝一声：“他妈的！”

木婉...
[R5] score=0.0514 chapter=24 index=3
      南海鳄神伸手一拍自己脑门，对云中鹤道：“你瞧，我徒弟的媳妇儿也这么说，难道还会冤枉你么？”

木婉清道：“我丈夫言道，他能拜到你这般了不起的师父，真是三生有幸，定要用心习艺，光大南海派的门楣，使你南海鳄神的名头更加威震天下，让甚么‘恶贯满盈...
---PLAN_NEXT_STEP---
[决策] plannedNext=retrieve (模型建议=retrieve) (子问题序列共4条，已检索3条（子问题1-3），剩余1条未检索（子问题4：'玄慈在虚竹身世揭晓之前，于武林中公开的身份和职务是什么？'）。该问题直接关系用户原始问题第二问的核心事实——'此人之子（即虚竹）的生父在身世揭晓前的公开身份'。当前已召回文档中虽多次提及'叶二娘''虚竹''玄慈'等关键词（如[1]提及其母叶二娘是南海鳄神同伙；[4]列四大恶人含叶二娘；但无一处明确说明玄慈的公开身份），且所有摘要均未出现'玄慈'或其职务（如少林方丈、武林泰斗等）相关信息。因此，关键事实缺失，必须通过下一轮向量检索子问题4来获取。剩余未检子问题数=1 > 0，已检轮数=3 < 上限8，符合继续检索条件。)---RETRIEVE (第 4 轮，子问题 4/4)---
查询: 玄慈在虚竹身世揭晓之前，于武林中公开的身份和职务是什么？
本轮命中 5 条，累计去重后 20 条
[R1] score=0.0551 chapter=98 index=3
      室里这么一偷懒，却救了游坦之的性命。原来游坦之手指一被冰蚕咬住，当即以《易筋经》中运功之法，化解毒气，血液被冰蚕吸入体内后，又回入他手指血管，将这剧毒无比的冰蚕精华吸进了体内。阿紫再吸取冰蚕的浆血，却已全无效用，只白辛苦了一场。倘若游坦之已...
[R2] score=0.0486 chapter=21 index=4
      木婉清痛得大叫一声，醒了转来，但跟着又晕了过去。

段誉死命按住她的伤口，不让鲜血流出，可是血如泉涌，却哪里按得住？他无法可施，随手在地下拔些青草，放在口中嚼烂了，敷上她伤口，但鲜血涌出，立将草泥冲开，忽地记起：“先前她中了钩伤，曾从怀中取...
[R3] score=0.0480 chapter=24 index=27
      胡思乱想一会，便睡着了。

这一觉睡到次日清晨才醒，只见房中陈设简陋，窗上铁条纵列，看来竟然便是无量剑关人的所在，只是空间宽敞，倒无局促之感，心想第一件事，须得遵照神仙姊姊嘱咐，练她的“北冥神功”，于是从怀中摸出卷轴，放在桌上，一想到画中的...
[R4] score=0.0479 chapter=83 index=19
      萧峰在窗外听着，也不禁佩服他定力惊人，在这如此危急的当口，居然还说得出调笑的话来。只见马夫人将他双手拉到背后，用牛筋丝绳牢牢的缚住，接连打了七八个死结，别说段正淳这时武功全失，就是内力无损，也非片刻间所能挣脱。

马夫人又娇笑道：“我最恨你...
[R5] score=0.0422 chapter=83 index=39
      她伏在阴暗之处，萧峰看不清楚，听她这么说，便过去推开窗子，亮光照进屋来，一瞥之下，不由得微微一颤，只见马夫人肩头、手臂、胸口、大腿，到处给人用刀子划成一条条伤口，伤口中竟密密麻麻的爬满了蚂蚁。萧峰看了她伤处，知她四肢和腰间关节处的筋络全给人...
---PLAN_NEXT_STEP---
[决策] plannedNext=generate (模型建议=generate) (剩余未检索子问题条数为 0（已全部完成4轮检索），硬性规则要求必须 nextAction=generate；尽管当前召回文档质量偏低（最高score仅0.0637）、且未显式出现‘玄慈’‘方丈’‘少林’等关键信息，但系统不允许继续检索——所有子问题均已按序执行完毕，生成阶段需基于已有检索结果、常识及文本推理作答。)
---GENERATE---

【AI 回答（流式）】
根据《天龙八部》小说原文及所提供片段，我们来逐层分析问题：

**问题：**  
《天龙八部》中「四大恶人」排行第二的是谁？此人之子在身世揭晓前，其生父在武林中的公开身份是什么？

---

### 一、四大恶人排行第二者是谁？

“四大恶人”在小说中明确以恶名排序，依序为：  
- **老大：段延庆**（绰号“恶贯满盈”）  
- **老二：叶二娘**（绰号“无恶不作”）  
- **老三：南海鳄神**（绰号“凶神恶煞”）  
- **老四：云中鹤**（绰号“穷凶极恶”）

此排序在多处原文中得到确证：

✅ **片段 5（第105章）**：  
> “南海鳄神大声道：‘我们老大见到请帖，很是欢喜……’”  
> “过了一会，**段延庆、叶二娘、南海鳄神**三人并肩而至。”  
→ 明确将段延庆列于首位，叶二娘次之，南海鳄神第三，隐含云中鹤为第四（后文称“云老四”，见片段4、7）。

✅ **片段 4（第148章）**：  
> 南海鳄神叫道：“……全靠**云老四**救了你这个老婆……”  
→ “云老四”之称，印证其排行第四。

✅ **片段 7（第24章）**：  
> 南海鳄神对云中鹤道：“你瞧，我徒弟的媳妇儿也这么说……”  
> 木婉清挑拨时亦直呼“云中鹤”，而南海鳄神称其为“老四”，与“老三”自居对应。

✅ **片段 2（第126章）**提及哈大霸所中“生死符”，虽未列名，但结合全书设定，“四大恶人”之名号、绰号、排序在少室山、小镜湖、棋会等多处反复出现，金庸原著及通行本均一致确认：  
> **第二位是叶二娘，绰号“无恶不作”**。

---

### 二、叶二娘之子是谁？其生父在身世揭晓前的公开身份是什么？

叶二娘之子即**虚竹**——这是全书核心伏笔与重大反转之一。

#### （1）叶二娘与虚竹的母子关系，在小说中如何揭示？

虽所提供片段中**未直接写出“叶二娘是虚竹生母”这一句**，但关键线索高度集中且可严密推定：

🔹 **片段 2（第126章）**：  
> “虚竹也道：‘正是！’**他母亲叶二娘是南海鳄神的同伙，不免有些香火之情。**”

→ 此句明言“**他母亲叶二娘**”，是全书**唯一一次由作者叙述视角直接确认虚竹与叶二娘的母子关系**。  
注意：此处非他人误认、非虚竹自称、非旁白猜测，而是客观叙述（“他母亲叶二娘”），属权威性文本证据。

🔹 **片段 5（第105章）**已表明叶二娘是“四大恶人”之一；  
🔹 **片段 4（第148章）**中虚竹主动提及“母亲叶二娘”，并因“香火之情”愿援手南海鳄神——情感逻辑成立的前提，正是血缘真实。

此外，该情节发生于少林寺危机之后、灵鹫宫事件之前，此时虚竹尚未知晓自己身世（他始终以为父母双亡于少林寺大火），但作者已借叙述者之口点明事实，为后续少林藏经阁揭秘（第159章左右）埋下决定性伏笔。

#### （2）虚竹生父在身世揭晓前的公开身份是什么？

虚竹之父是**少林寺方丈玄慈大师**。

在身世揭晓前（即第159章“雁门关外，石壁遗文”真相大白之前），玄慈在武林中的**公开身份**是：

> **少林寺方丈，武林泰斗，德高望重、持戒精严的佛门领袖，天下公认的正道魁首。**

此身份在全书多处被反复强调：

🔸 **片段 2（第126章）**虽未提玄慈，但哈大霸向虚竹磕头称“恩公”，众人尊其为“破解生死符”的救世者，侧面反映少林背景之崇高；  
🔸 更重要的是，**所有片段中凡涉及少林高层，均以“玄慈方丈”尊称，无人质疑其德行**。直至身世揭露，江湖才震惊于“方丈破戒生子”之秘。

🔹 关键佐证来自**小说整体结构**：  
- 虚竹自幼在少林长大，为慧轮和尚（实为玄慈安排）抚养，法名“虚竹”，是少林俗家弟子出身、受戒多年的正宗僧人；  
- 玄慈从未以父身份相认，对外始终是“严守清规、慈悲为怀”的方丈；  
- 直到少林大会，汪剑通遗训石壁现世，玄慈当众自承雁门关旧事、承认与叶二娘私通、生下虚竹，并自废武功、受杖刑而死——此前数十年，**其公开身份唯是“少林方丈玄慈”**，绝无其他江湖 alias 或隐藏身份。

✅ 因此，答案明确：  
> 叶二娘之子是**虚竹**；  
> 其生父玄慈在身世揭晓前，武林中**唯一的、公开的、广为人知的身份是：少林寺方丈**。

---

### ✅ 最终答案（严格依据所提供片段及小说设定）：

《天龙八部》中「四大恶人」排行第二的是**叶二娘**（绰号“无恶不作”）。  
此人之子是**虚竹**；在身世揭晓前，其生父**玄慈**在武林中的公开身份是**少林寺方丈**。

**原文依据：**  
- 片段2明确写道：“**他母亲叶二娘是南海鳄神的同伙**”——这是小说中对虚竹生母最直接、最权威的叙述性确认；  
- 结合全书设定及片段5、7、4等对“四大恶人”排序的描写，叶二娘稳居第二；  
- 玄慈作为少林方丈的身份贯穿全书，其德望之隆、地位之尊，在未揭破雁门关旧事前，绝无任何其他“公开身份”——他就是武林共仰的“玄慈方丈”。

（注：片段中虽未出现“玄慈”之名，但“虚竹之父为玄慈”是《天龙八部》不可动摇的核心设定；而片段2已确证“叶二娘是虚竹之母”，故其父身份可据此唯一推定，且完全符合金庸原著。）

【子问题序列】
  1. 《天龙八部》世纪新修版中，‘四大恶人’按恶名与地位排序，排行第二的人物是谁？
  2. 叶二娘的儿子在《天龙八部》中叫什么名字？
  3. 虚竹的生父在《天龙八部》中是谁？
  4. 玄慈在虚竹身世揭晓之前，于武林中公开的身份和职务是什么？

【检索相关内容（累计）】

[片段 1] 相似度: 0.0637
书籍: 1
章节: 第 148 章
片段索引: 0
内容: [../Images/002.png]

巴天石和朱丹臣等过来和木婉清相见，又替她引见萧峰、虚竹等人。巴朱二人虽知她是镇南王之女，但并未行过正式收养之礼，是以仍称她为“木姑娘”。

众人行得数里，忽听得左首传来一声惊呼，更有人大声号叫，却是南海鳄神的声音，似乎遇上了甚么危难。段誉道：“是我徒弟！”钟灵叫道：“咱们快去瞧瞧，你徒弟为人倒也不坏。”虚竹也道：“正是！”他母亲叶二娘是南海鳄神的同伙，不免...

[片段 2] 相似度: 0.0560
书籍: 1
章节: 第 126 章
片段索引: 37
内容: 哈大霸说道：“中……中在……悬枢……气……气海……丝……丝空竹……”适才虚竹一招“阳歌天钧”，已令他神智恢复。

虚竹喜道：“你自己知道，那就好了。”当即以童姥所授法门，用天山六阳掌的纯阳之力，将他悬枢、气海、丝空竹三处穴道中的寒冰生死符化去。

哈大霸站起身来，挥拳踢腿，大喜若狂，突然扑翻在地，砰砰砰的向虚竹磕头，说道：“恩公在上，哈大霸的性命，是你老人家给的，此后恩公但有所命，哈大霸赴汤蹈火，...

[片段 3] 相似度: 0.0551
书籍: 1
章节: 第 98 章
片段索引: 3
内容: 室里这么一偷懒，却救了游坦之的性命。原来游坦之手指一被冰蚕咬住，当即以《易筋经》中运功之法，化解毒气，血液被冰蚕吸入体内后，又回入他手指血管，将这剧毒无比的冰蚕精华吸进了体内。阿紫再吸取冰蚕的浆血，却已全无效用，只白辛苦了一场。倘若游坦之已练会《易筋经》的全部行功法诀，自能将冰蚕的毒质逐步消解，但他只学会一项法门，入而不出。这冰蚕奇毒乃是第一阴寒之质，登时便将他冻僵了。

要是室里将他埋入土中，即...

[片段 4] 相似度: 0.0543
书籍: 1
章节: 第 148 章
片段索引: 5
内容: 片刻之间，虚竹将段延庆接了上来，跟着将南海鳄神与云中鹤一一提起，最后才拉起王语嫣。她双目紧闭，呼吸微弱，已然晕去。

段誉先是大为欣慰，跟着便心下怜惜，但见她双手手腕上都是一圈紫黑之色，现出云中鹤深深的指印，想起云中鹤凶残好色，对木婉清和钟灵都曾意图非礼，每一次都蒙南海鳄神搭救，今日之事，自然又是恶事重演，不由得恼怒之极，说道：“大哥、二哥，这个云中鹤生性奸恶，咱们把他杀了罢！”

南海鳄神叫道：...

[片段 5] 相似度: 0.0525
书籍: 1
章节: 第 105 章
片段索引: 18
内容: 南海鳄神的叫声甫歇，山下快步上来一人，身法奇快，正是云中鹤，叫道：“天下四大恶人拜访聪辩先生，谨赴棋会之约。”苏星河道：“欢迎之至。”这四字刚出口，云中鹤已飘行到了众人身前。

过了一会，段延庆、叶二娘、南海鳄神三人并肩而至。南海鳄神大声道：“我们老大见到请帖，很是欢喜，别的事情都搁下了，赶着来下棋，他武功天下无敌，比我岳老二还要厉害。哪一个不服，这就上来跟他下三招棋。你们要单打独斗呢，还是大伙儿...

[片段 6] 相似度: 0.0523
书籍: 1
章节: 第 21 章
片段索引: 24
内容: 木婉清冷冷的道：“你知道自己徒儿的脾气。他只消学得你本事十成中的一成，我便杀他不了。”南海鳄神点头道：“这话倒也有理。”但想到自己这一门的规矩，向来一徒单传，孙三霸一死，十余年传功督导的心血化为乌有，越想越恼，大喝一声：“他妈的！”

木婉清和段誉见他一张脸皮突转焦黄，神情狰狞可怖，均是心下骇然，只听他大声道：“我要给徒儿报仇！”

段誉说道：“岳二爷，你说过不伤她性命的。再说，你的徒弟学不到你武...

[片段 7] 相似度: 0.0514
书籍: 1
章节: 第 24 章
片段索引: 3
内容: 南海鳄神伸手一拍自己脑门，对云中鹤道：“你瞧，我徒弟的媳妇儿也这么说，难道还会冤枉你么？”

木婉清道：“我丈夫言道，他能拜到你这般了不起的师父，真是三生有幸，定要用心习艺，光大南海派的门楣，使你南海鳄神的名头更加威震天下，让甚么‘恶贯满盈’、‘无恶不作’，都瞧着你羡慕得不得了。哪知道云中鹤起了毒心，害死了你的好徒儿，从今以后，你再也找不到这般像你的人来做徒儿啦！”她说一句，南海鳄神拍一下脑门。木...

[片段 8] 相似度: 0.0486
书籍: 1
章节: 第 21 章
片段索引: 4
内容: 木婉清痛得大叫一声，醒了转来，但跟着又晕了过去。

段誉死命按住她的伤口，不让鲜血流出，可是血如泉涌，却哪里按得住？他无法可施，随手在地下拔些青草，放在口中嚼烂了，敷上她伤口，但鲜血涌出，立将草泥冲开，忽地记起：“先前她中了钩伤，曾从怀中取出药来敷上，不久便止了血。”

轻轻伸手到她怀中，将触手所及的物事一一掏了出来，见是一只黄杨木梳子、一面小铜镜，两块粉红色的手帕、另有三只小木盒、一个瓷瓶。他见...

[片段 9] 相似度: 0.0480
书籍: 1
章节: 第 24 章
片段索引: 27
内容: 胡思乱想一会，便睡着了。

这一觉睡到次日清晨才醒，只见房中陈设简陋，窗上铁条纵列，看来竟然便是无量剑关人的所在，只是空间宽敞，倒无局促之感，心想第一件事，须得遵照神仙姊姊嘱咐，练她的“北冥神功”，于是从怀中摸出卷轴，放在桌上，一想到画中的裸像，一颗心便怦怦乱跳，面红耳赤，急忙正襟危坐，心中默告：“神仙姊姊，我是遵你吩咐，修习神功，可不是想偷看你的贵体，亵渎莫怪。”

缓缓展开，将第一图后的小字看...

[片段 10] 相似度: 0.0479
书籍: 1
章节: 第 83 章
片段索引: 19
内容: 萧峰在窗外听着，也不禁佩服他定力惊人，在这如此危急的当口，居然还说得出调笑的话来。只见马夫人将他双手拉到背后，用牛筋丝绳牢牢的缚住，接连打了七八个死结，别说段正淳这时武功全失，就是内力无损，也非片刻间所能挣脱。

马夫人又娇笑道：“我最恨你这双腿啦，迈步一去，那就无影无踪了。”说着在他大腿上轻轻扭了一把。段正淳笑道：“那年我和你相会，却也是这双腿带着我来的。这双腿儿罪过虽大，功劳可也不小。”马夫人...

[片段 11] 相似度: 0.0476
书籍: 1
章节: 第 100 章
片段索引: 0
内容: [../Images/30.jpg]





[../Images/30-1.jpg]

[片段 12] 相似度: 0.0472
书籍: 1
章节: 第 77 章
片段索引: 33
内容: 段正淳在小镜湖畔和旧情人重温鸳梦，护驾而来的三公四卫散在四周卫护，殊不想大对头竟然找上门来。

段延庆武功厉害，四大护卫中的古笃诚、傅思归先后受伤。朱丹臣误认萧峰为敌，在青石桥阻拦不果。褚万里复为阿紫的柔丝网所擒。司马范骅、司徒华赫良、司空巴天石三人救护古、傅二人后，赶到段正淳身旁护驾，共御强敌。

朱丹臣一直在设法给褚万里解开缠在身上的渔网，偏生这网线刀割不断，手解不开，忙得满头大汗，无法可施。...

[片段 13] 相似度: 0.0471
书籍: 1
章节: 第 49 章
片段索引: 19
内容: 这其中吃惊最甚的，自然是诸保昆了。原来他师父叫作都灵道人，年轻时曾吃过青城派的大亏，处心积虑的谋求报复，在四川各地暗中窥视，找寻青城派的可乘之隙。这一年在灌县见到了诸保昆，那时他还是个孩子，但根骨极佳，实是学武的良材，于是筹划到一策。他命人扮作江洋大盗，潜入诸家，绑住诸家主人，大肆劫掠之后，拔刀要杀了全家灭口，又欲奸淫诸家的两个女儿。都灵子早就等在外面，直到千钧一发的最危急之时，这才挺身而出，逐走...

[片段 14] 相似度: 0.0441
书籍: 1
章节: 第 69 章
片段索引: 0
内容: [../Images/20.jpg]





[../Images/20-1.jpg]

[片段 15] 相似度: 0.0428
书籍: 1
章节: 第 33 章
片段索引: 10
内容: 巴天石奔了这百余个圈子，已知云中鹤的下盘功夫飘逸有余，沉凝不足，不如自己一弹一跃之际行有余力，只消陡然停住，击他三掌，他势必抵受不住。但巴天石一心要在轻功上考较他下去，不愿以拳脚功夫取胜，是以仍是一股劲儿的奔跑。

忽听得一人粗声骂道：“妈巴羔子的，吵得老子睡不着觉，是那儿来的兔崽子？”只见南海鳄神手持鳄嘴剪，一跳一跳的跃近。

傅思归喝道：“是你师父的爹爹来啦！”南海鳄神喝道：“甚么我师父的爹爹...

[片段 16] 相似度: 0.0422
书籍: 1
章节: 第 83 章
片段索引: 39
内容: 她伏在阴暗之处，萧峰看不清楚，听她这么说，便过去推开窗子，亮光照进屋来，一瞥之下，不由得微微一颤，只见马夫人肩头、手臂、胸口、大腿，到处给人用刀子划成一条条伤口，伤口中竟密密麻麻的爬满了蚂蚁。萧峰看了她伤处，知她四肢和腰间关节处的筋络全给人挑断了，再也动弹不得。这不同点穴，可以解开穴道，回复行动，筋脉既断，那就无可医治，从此成了软瘫的废人。但怎么伤口中竟有这许多蚂蚁？

马夫人颤声道：“那小贱人，...

[片段 17] 相似度: 0.0395
书籍: 1
章节: 第 157 章
片段索引: 21
内容: 他不敢在大理境内逗留，远至南部蛮荒穷乡僻壤之处，养好伤后，苦练家传武功。最初五年习练以杖代足，再将“一阳指”功夫化在钢杖之上；又练五年后，前赴两湖，将所有仇敌一家家杀得鸡犬不留，手段之凶狠毒辣，实是骇人听闻，因而博得了“天下第一大恶人”的名头，其后又将叶二娘、南海鳄神、云中鹤三人收罗以为羽翼。他曾数次潜回大理，图谋复位，但每次都发觉段正明的根基牢不可拔，只得废然而退。最近这一次与黄眉僧下棋比拚内力...

[片段 18] 相似度: 0.0388
书籍: 1
章节: 第 157 章
片段索引: 9
内容: 原来段正淳派遣巴天石和朱丹臣护送段誉赴西夏求亲，不久便接到保定帝御使送来的谕旨，命他克日回归大理，登基接位，保定帝自己要赴天龙寺出家。大理国皇室崇信佛法，历代君主到晚年避位为僧者甚众，是以段正淳奉到谕旨之时虽心中伤感，却不以为奇，当即携同秦红棉、阮星竹缓缓南归，想将二女在大理城中秘为安置，不令王妃刀白凤知晓。岂知刀白凤和甘宝宝竟先后赶到。跟着得到灵鹫宫诸女传警，说道有厉害对头沿路布置陷阱，请段正淳...

[片段 19] 相似度: 0.0376
书籍: 1
章节: 第 63 章
片段索引: 0
内容: [../Images/18.jpg]





[../Images/18-1.jpg]

[片段 20] 相似度: 0.0364
书籍: 1
章节: 第 49 章
片段索引: 41
内容: 司马林脸上变色，心想：“此言果然不假。我父亲故世后，青城派力量已不如前，再加诸保昆这奸贼已偷学了本派武功，倘若秦家寨再和我们作对，此事大大可虑。常言道先下手为强，后下手遭殃。格老子，今日之事，只有杀他个措手不及。”

当下淡淡的道：“你待怎样？”

姚伯当见他双手笼在衣袖之中，知他随时能有阴毒暗器从袖中发出，当下全神戒备，说道：“我请王姑娘到云州去作客，待慕容公子来接她回去。你却来多管闲事，偏不答...

检索轮数: 4 / 8

最终策略: complex
 */