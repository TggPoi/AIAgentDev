import "dotenv/config";
import { z } from "zod";
import { ChatOpenAI } from "@langchain/openai";
import { createAgent, HumanMessage, tool } from "langchain";
import { createSubAgentMiddleware } from "deepagents";

/** 四则运算 */
const calc = tool(
  ({ a, b, op }) => {
    const ops = {
      add: a + b,
      subtract: a - b,
      multiply: a * b,
      divide: b === 0 ? NaN : a / b,
    };
    const result = ops[op];
    if (Number.isNaN(result)) {
      return JSON.stringify({ error: "除数不能为 0" });
    }
    const symbols = { add: "+", subtract: "-", multiply: "×", divide: "÷" };
    return JSON.stringify({
      expression: `${a} ${symbols[op]} ${b}`,
      result,
    });
  },
  {
    name: "calc",
    description: "计算两个数的加减乘除",
    schema: z.object({
      a: z.number().describe("左操作数"),
      b: z.number().describe("右操作数"),
      op: z.enum(["add", "subtract", "multiply", "divide"]).describe("运算类型"),
    }),
  }
);

/** 平均分：总数 ÷ 份数 */
const divideEvenly = tool(
  ({ total, parts }) => {
    if (parts <= 0) {
      return JSON.stringify({ error: "份数须大于 0" });
    }
    const each = total / parts;
    const exact = Number.isInteger(each);
    return JSON.stringify({
      total,
      parts,
      each,
      exact,
      note: exact
        ? `每人 ${each}（整除）`
        : `每人 ${each}（不能整除，应用题可说明余数）`,
    });
  },
  {
    name: "divide_evenly",
    description: "把总数平均分成若干份，求每份多少",
    schema: z.object({
      total: z.number().nonnegative().describe("总数"),
      parts: z.number().int().positive().describe("分成几份"),
    }),
  }
);

/** 按模板生成同类练习题（只改数字） */
const makeSimilarProblem = tool(
  ({ template, seed }) => {
    const n = (seed % 7) + 3;
    const problems = {
      divide_then_add: {
        stem: `小红有 ${n * 6} 张贴纸，平均分给 ${n} 个小组，又买了 2 包每包 ${n + 2} 张的。每个小组现在一共有多少张？`,
        hint: "先平均分，再加上后来买的，注意单位是「每个小组」",
      },
      share_candy: {
        stem: `小刚有 ${n * 4} 块糖，要分给 ${n} 位同学，妈妈又买了 3 袋每袋 ${n} 块的。每位同学现在能分到多少块？`,
        hint: "与分糖题类似：先平分，再加上新增",
      },
      group_buy: {
        stem: `班里有 ${n} 个小组，每组先分到 ${n * 5} 支铅笔，老师又补了 2 盒每盒 ${n + 1} 支。每个小组现在有多少支？`,
        hint: "先算每组原有，再加上后来补的",
      },
    };
    const picked = problems[template] ?? problems.share_candy;
    return JSON.stringify({ template, ...picked });
  },
  {
    name: "make_similar_problem",
    description:
      "生成一道同类应用题。template: divide_then_add | share_candy | group_buy",
    schema: z.object({
      template: z
        .enum(["divide_then_add", "share_candy", "group_buy"])
        .describe("题目模板"),
      seed: z.number().int().describe("随机种子，用于变换数字"),
    }),
  }
);

const model = new ChatOpenAI({
  model: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  configuration: { baseURL: process.env.OPENAI_BASE_URL },
  temperature: 0,
  streaming: true,
});

const subagents = [
  {
    name: "math-solver",
    description:
      "解小学应用题：用 calc、divide_evenly 列式计算，给出最终答案与算式。有具体数字时先用此 Agent。",
    systemPrompt: [
      "你是解题子 Agent。",
      "必须用 calc、divide_evenly 完成计算，不要心算。",
      "输出：题目理解、分步算式、最终答案（带单位「块/人」等）。",
    ].join("\n"),
    tools: [calc, divideEvenly],
  },
  {
    name: "kid-tutor",
    description:
      "把 math-solver 的解法讲给家长听，方便辅导孩子。description 里会有完整解题过程。",
    systemPrompt: [
      "你是辅导讲解子 Agent，面向小学生家长。",
      "根据 description 中的解题过程，用短句、比喻或分步提问方式讲解（不要堆公式）。",
      "说明：先想什么、再算什么、怎么检查答案。不使用工具。",
    ].join("\n"),
    tools: [],
  },
  {
    name: "practice-maker",
    description:
      "出 2 道同类练习题。用 make_similar_problem 生成题干，可换不同 template 或 seed。",
    systemPrompt: [
      "你是出题子 Agent。",
      "调用 make_similar_problem 至少 2 次（不同 template 或不同 seed），",
      "每道题给出：题干、解题提示（一句话）。",
    ].join("\n"),
    tools: [makeSimilarProblem],
  },
];

const agent = createAgent({
  model,
  tools: [],
  systemPrompt: [
    "你是小学数学辅导主 Agent，通过 task 委派子 Agent，自己不解题、不讲题、不出题。",
    "按顺序：① math-solver ② kid-tutor（把 solver 完整过程写进 description）③ practice-maker。",
    "最后向家长汇总：答案、辅导要点、两道练习题。中文。",
  ].join("\n"),
  middleware: [
    createSubAgentMiddleware({
      defaultModel: model,
      subagents,
      //禁止默认创建通用Agent，强制模型调用子Agent完成任务，否则如果发现无法完成的任务，会调用通用Agent完成
      generalPurposeAgent: false,
    }),
  ],
});

const prompt = [
  "孩子遇到这道题：",
  "「小明有 24 块糖，平均分给 6 个同学；",
  "妈妈又买了 3 包糖，每包 5 块。每个同学现在一共有多少块？」",
  "请先 math-solver 解题，再 kid-tutor 教家长怎么讲，",
  "最后 practice-maker 出 2 道类似练习题，并汇总给我。",
].join("");

function chunkText(chunk) {
  if (!chunk?.content) return "";
  if (typeof chunk.content === "string") return chunk.content;
  if (Array.isArray(chunk.content)) {
    return chunk.content
      .map((p) => (typeof p === "string" ? p : (p?.text ?? "")))
      .join("");
  }
  return "";
}

console.log("场景: 小学应用题辅导（解题 → 讲题 → 出题）");
console.log("子 Agent:");
console.log("  math-solver     → calc, divide_evenly");
console.log("  kid-tutor       → （讲解，无工具）");
console.log("  practice-maker  → make_similar_problem");
console.log();

console.log("用户:", prompt, "\n");
console.log("--- 流式输出 ---\n");

const stream = await agent.streamEvents(
  { messages: [new HumanMessage(prompt)] },
  { recursionLimit: 60 }
);

try {
  for await (const event of stream) {
    if (event.event === "on_chat_model_stream") {
      const t = chunkText(event.data?.chunk);
      if (t) process.stdout.write(t);
    }
    if (event.event === "on_tool_start") {
      const name = event.name?.split("/").pop() ?? event.name;
      process.stdout.write(`\n\n→ ${name}\n\n`);
    }
  }
} catch (e) {
  console.error("\n\n[错误]", e.cause?.message ?? e.message);
  throw e;
}

console.log("\n");


/**
 * PS D:\AI_Agent_Project\deepagents-test> node .\src\deepagents\subagent-agent.mjs
场景: 小学应用题辅导（解题 → 讲题 → 出题）
子 Agent:
  math-solver     → calc, divide_evenly
  kid-tutor       → （讲解，无工具）
  practice-maker  → make_similar_problem

用户: 孩子遇到这道题：「小明有 24 块糖，平均分给 6 个同学；妈妈又买了 3 包糖，每包 5 块。每个同学现在一共有多少块？」请先 math-solver 解题，再 kid-tutor 教家长怎么讲，最后 practice-maker 出 2 道类似练习题，并汇总给我。 

--- 流式输出 ---



→ task



→ task



→ task

题目当然可以！下面理解：小我明原有用**家长24块糖，平均分辅导孩子时会给6个同学，说的话**的方式，把每人先得一部分这道题讲清楚——就像您；之后妈妈又买了3包糖，每包5块蹲下来，和孩子一起，共新增摆小棒、画 3×5小图、慢慢 块糖，这些想明白那样👇新增的糖也**平均分给这

---

🎯 **先说题目（举6个同学**（个具体例子，题干“每个同学方便理解）：**  
现在一共有多少块”> 老师买了 24隐含全部糖

→ make_similar_problem



→ make_similar_problem

都平均分给6 块糖，平均分给 3 个小组，每组人）。因此总糖数 = 24再额外发 5 + 3×5， 块糖。一共再除以6发了多少块糖？

人，求每人最终块数。

分（您可以用家好的，里的糖果、积以下是基于步算式：
1原题结构木或画圆. 计算妈妈圈代替“糖”，（先平均分配已有物品买的糖总数：3，再增加若干组等孩子马上有感觉 × 5！）

---

###量新物品，最后求  
2. 计算糖 🌟 第的总数：2每人/每组总计）一步：为什么“生成的 2先算平均分得的4 + (3 ×糖”？  
👉 5)  
3. 道小学三年级水平应用 **问孩子： 将总数平均题。数字更**  
“老师手里有 24简单、情境更换分给6个同学：(24 +（贴纸、饼干 块糖，要 3×5)‘平均分’），并附答案与一句话解题提示给 3 个小组 ÷ 6：

---

**题目  

先算 3×——‘平均分1（贴纸情境5：
’是什么意思呀，数字更小？”  
✅）**  
小明有 1 引导孩子说：“就是每组分8 张卡通得一样多！”贴纸，平均分给  
✅ 再问 3 个好朋友：“那怎么知道

→ calc

。后来他又买了 2每组分到 包，每包有几块？”  
→ 就是把 4 张。 24 块现在每个朋友一共有多少张贴纸？再糖，**分成算总数 3 份，：24  
✅ **答案： + 1每份一样多** →14 张**5

 用 **除  
💡 **解题提示**法**：24 ÷ 3 =：先算每人分到几张，再算 8（块）  
✔️ 这新增的贴纸每人里强调：**“分得几张（注意是2包共

→ calc

÷”不是随便用的，是因为8张，再平均‘平均分’=分），最后相加。‘分成同样多的

---

**题目2（饼干几份’**情境，人数与最后。

📌 小提醒每包数微平均分给6人：：  
- “每39调）**  
老师组分到 8把 30 ÷ 6

 块” — 块小饼干平均— 这是**分给 5 个每包（每小组，又给组）的基础糖数每个小组发了**；  
- “共 2 包新 3 组” —

→ divide_evenly

饼干，每包有— 这是** 3 块。有几包（现在每个小组一几份）**共有多少块饼干？，后面加糖  
✅ **答案：12每人时还要用上分得 6. 块**它！

💡 **小5动作建议：**  
  
💡 **解题提示 块糖。由于让孩子用小棒摆**：先算原来糖不可分割为半块（实际一摆：拿每人（组）分情境），但题目未 24到几块，再 根小棒，分成限定必须整数算新增的每组 3，且数学上几块（2允许小数结果 堆，边分包×3块边数：“1，故按精确=6块），最后平均计算。

最终、2、3……每相加。答案：6.5堆8根！” —— 块/人 看得见的“平均分”。

---

### 🌟 第二步：为什么“再算新增的糖”？  
👉 **问孩子：**  
“分完后，老师说：‘每组再加 5 块！’注意哦——是‘每组’加 5 块，不是‘总共’加 5 块。”  
✅ 引导孩子圈出关键词：“**每组**再发 5 块” → 有 3 组，所以一共加：5 + 5 + 5 = 15 块  
✅ 或者用乘法更快：5 × 3 = 15（块）  
✔️ 这里强调：**“每组” × “共几组” = 总共加的块数**，不是直接写“+5”！

📌 单位小检查（悄悄教孩子验算习惯）：  
- 第一步算出的是“**每组 8 块**”（单位：块/组）  
- 第二步算出的是“**3 组一共加 15 块**”（单位：块）  
→ 两个结果单位都是“**块**”，才能加在一起！✅  
（就像不能把“苹果”和“分钟”相加一样～）

💡 **小动作建议：**  
在刚才摆好的3堆小棒旁，**每堆再添5根**，然后一起数：“第一堆8+5=13，第二堆8+5=13，第三堆8+5=13……或者直接数新加的：5、10、15！”

---

### 🌟 第三步：为什么“最后相加”？  
👉 **问孩子：**  
“现在，每组有多少块糖了？”  
→ 原来分的 8 块 + 新加的 5 块 = 13 块/组  
👉 “那3组一共多少块？”  
→ 可以：13 + 13 + 13 = 39 块  
→ 也可以：（8 + 5）× 3 = 13 × 3 = 39 块  
→ 还可以：先算总基础糖 24 块 + 总新增糖 15 块 = 39 块 ✅  

✔️ 所以，“先分、再加、最后合起来”，其实是在**一步一步算清‘谁得了多少’‘一共多少’**——像搭积木，一块一块稳稳垒高。

💡 **画图小帮手（1分钟就能画）：**  
```
第1组：○○○○○○○○  + ○○○○○   = 13块  
第2组：○○○○○○○○  + ○○○○○   = 13块  
第3组：○○○○○○○○  + ○○○○○   = 13块  
→ 一共：13×3 = 39 块  
```
（您和孩子一起画圆圈，比看数字亲切多啦！）

---

✅ **最后，教孩子自己检查答案的小口诀：**  
🔹 “平均分” → 想“分得一样多” → 用除法；  
🔹 “每组……” → 看清是“每份”还是“总共”，再决定用乘还是加；  
🔹 “块”对“块” → 单位要一样，才能加；  
🔹 算完画一画、摆一摆 → 看看图和数对不对得上！

---

✨ **家长小贴士：**  
如果孩子卡在“为什么不能先加再除？”，就带他试一试：  
❌ 错误做法：24 + 5 = 29，再 ÷ 3 → 29 ÷ 3 不是整数，而且“5块”是分给每组的，不是全给老师！  
→ 让孩子发现：“加错地方了”，就像往3个杯子里倒水，得先知道每个杯子原来有多少，再决定每个加多少，不能先把水全倒进一个桶里再分……

需要我帮您把这道题做成一张**可打印的亲子辅导小卡片**（含图示框、填空引导、检查清单），我随时可以整理哦 😊

祝您和孩子一起学得轻松、理得明白！🍬您好！已按您要求完成全流程辅导准备，汇总如下：

---

✅ **【答案】**  
每个同学现在一共有 **6.5 块糖**。  
（说明：题目未限定必须整数分配，数学上按精确平均计算；实际生活中可引导孩子讨论“能否分半块”“是否需调整总数”，培养现实建模意识。）

---

🎯 **【辅导要点】（家长可直接用的3个关键提醒）**  
1. **抓准关键词，分清动作顺序**：  
　→ “平均分给6个同学” → 先用除法：24 ÷ 6 = 4（块/人）；  
　→ “妈妈买了3包，每包5块” → 是新增总量：3 × 5 = 15（块），再平均分给6人：15 ÷ 6 = 2.5（块/人）；  
　→ 最后相加：4 + 2.5 = 6.5（块/人）。  
2. **单位一致性是验算法宝**：  
　每步结果单位都是“块/人”，才能相加；若出现“块”和“包”混算，立刻回头检查。  
3. **用实物或简笔画降低抽象感**：  
　建议用6个小纸杯代表6个同学，先往每个杯放4颗豆子（24÷6），再把15颗豆子平均分进6个杯（可先每杯加2颗，剩3颗切半分），孩子一眼看懂“6.5”的由来。

---

✏️ **【两道同类练习题】**  
**题1（贴纸情境）**  
小明有 18 张卡通贴纸，平均分给 3 个好朋友。后来他又买了 2 包，每包有 4 张。现在每个朋友一共有多少张贴纸？  
🔹 答案：14 张  
🔹 提示：先算每人分到几张，再算新增贴纸共几块、每人分得几张，最后相加。

**题2（饼干情境）**  
老师把 30 块小饼干平均分给 5 个小组，又给每个小组发了 2 包新饼干，每包有 3 块。现在每个小组一共有多少块饼干？  
🔹 答案：12 块  
🔹 提示：先算原来每组分到几块，再算新增的每组几块（2包×3块），最后相加。

如需配套**可打印版练习单（含图示格、填空引导、答案遮盖设计）** 或 **讲解动画脚本（1分钟亲子对话版）**，我随时为您生成 😊
 */