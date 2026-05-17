/**
 * RAG 评测入口：dataset（问题+标准答案） + evaluate
 */
import "dotenv/config";
import { Client } from "langsmith";
import { evaluate } from "langsmith/evaluation";
import { ask } from "../rag_agent.mjs";
import { ragEvaluators } from "./evaluators.mjs";

const DATASET_NAME = "rag-eval-v1";
const client = new Client({ apiKey: process.env.LANGCHAIN_API_KEY });

/** 被评测的 RAG Agent */
async function runRagAgent(inputs) {
    //传入用户提问，返回answer--模型回答和 context--milvus的检索结果（上下文）
  const { answer, context } = await ask(inputs.question);

  return {
    answer,
    context: context.map((d) => d.pageContent),
  };
}

async function main() {
    // 评测 runRagAgent，使用 ragEvaluators 中的评测指标，评测数据集为 rag-eval-v1
  const result = await evaluate(runRagAgent, {
    data: DATASET_NAME,
    evaluators: ragEvaluators,
    client,
    experimentPrefix: `rag-openevals-${process.env.MODEL_NAME ?? "qwen"}`,
    maxConcurrency: 2,
  });

  // 等待全部样例跑完
  for await (const _row of result) {
    /* drain */
  }

  const project = process.env.LANGCHAIN_PROJECT ?? "default";
  console.log("✅ 评测完成");
  console.log("实验名:", result.experimentName);
  console.log(
    "指标: rag_groundedness | rag_helpfulness | rag_retrieval_relevance",
  );
  //执行完之后会拿到评估结果的链接
  console.log(
    `报告: https://smith.langchain.com/o/default/projects/p/${encodeURIComponent(project)}`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

/**
 * PS D:\AI_Agent_Project\langsmith-test> node .\src\eval\run_eval.mjs     
Starting evaluation of experiment: rag-openevals-qwen-plus-87dab82b
View results at https://smith.langchain.com/o/1838ade1-fedf-406d-9a89-2adc2a97d752/datasets/f44411f7-c57c-4bb4-8f8f-616e4639d491/compare?selectedSessions=561936a2-eec0-4c4a-af14-dcbad34d06f4
✅ 评测完成
实验名: rag-openevals-qwen-plus-87dab82b
指标: rag_groundedness | rag_helpfulness | rag_retrieval_relevance
报告: https://smith.langchain.com/o/default/projects/p/langsmith-test
 */