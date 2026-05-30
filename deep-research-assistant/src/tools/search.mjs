// tool：将普通异步函数包装为 Agent 可调用工具。
import { tool } from "langchain";
// z：定义并校验搜索工具的输入结构。
import { z } from "zod";

// BOCHA_API_URL：Bocha 联网搜索接口地址。
const BOCHA_API_URL = "https://api.bochaai.com/v1/web-search";

// formatWebPages：将 Bocha 返回的网页数组整理为适合 Agent 阅读的文本。
// 参数 webpages：Bocha 返回的网页结果数组。
// 调用位置：bochaWebSearch()。
function formatWebPages(webpages) {
  return webpages
    // map 回调函数：把单个网页结果转换为文本；由 formatWebPages() 中的 webpages.map() 调用。
    // 参数 page：当前网页结果；idx：当前结果在数组中的索引。
    .map(
      (page, idx) =>
        `引用: ${idx + 1}
标题: ${page.name ?? ""}
URL: ${page.url ?? ""}
摘要: ${page.summary ?? ""}
网站名称: ${page.siteName ?? ""}
网站图标: ${page.siteIcon ?? ""}
发布时间: ${page.dateLastCrawled ?? ""}`,
    )
    .join("\n\n");
}

// bochaWebSearch：调用 Bocha API 搜索网页并返回格式化结果或错误信息。
// 参数 query：搜索关键词；count：期望返回的网页数量。
// 调用位置：webSearch 工具的执行函数。
async function bochaWebSearch(query, count) {
  // apiKey：Bocha API 密钥，从环境变量中读取。
  const apiKey = process.env.BOCHA_API_KEY?.trim();
  if (!apiKey) {
    return "Bocha 联网搜索的 API Key 未配置（环境变量 BOCHA_API_KEY），请先在 .env 中配置后再重试。";
  }

  // response：Bocha API 返回的 HTTP 响应。
  const response = await fetch(BOCHA_API_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      freshness: "noLimit",
      summary: true,
      count,
    }),
  });

  if (!response.ok) {
    // errorText：接口返回的原始错误正文，用于辅助定位请求失败原因。
    const errorText = await response.text();
    return `搜索 API 请求失败，状态码: ${response.status}，错误信息: ${errorText}`;
  }

  // json：解析后的 Bocha API JSON 响应。
  let json;
  try {
    json = await response.json();
  } catch (e) {
    // e：JSON 解析阶段抛出的异常。
    return `搜索 API 请求失败，原因是：搜索结果解析失败 ${e.message}`;
  }

  try {
    if (json.code !== 200 || !json.data) {
      return `搜索 API 请求失败，原因是: ${json.msg ?? "未知错误"}`;
    }

    // webpages：响应中的网页结果数组；接口未返回结果时使用空数组。
    const webpages = json.data.webPages?.value ?? [];
    if (!webpages.length) {
      return `未找到与「${query}」相关的结果。`;
    }

    return formatWebPages(webpages);
    
  } catch (e) {
    // e：读取响应字段或格式化网页结果时抛出的异常。
    return `搜索 API 请求失败，原因是：搜索结果解析失败 ${e.message}`;
  }
}

// webSearch：暴露给研究员子 Agent 的联网搜索工具。
// 调用位置：src/agent.mjs 的 researcherSubAgent.tools，由 Agent 在调研过程中调用。
export const webSearch = tool(
  // 工具执行回调函数：执行一次搜索；Agent 调用 webSearch 时由 tool() 间接调用。
  // 参数 input：通过 schema 校验后的工具参数，包含 query 和可选 count。
  async (input) => {
    // count：本次搜索返回的结果数量；调用方未传值时默认为 10。
    const count = input.count ?? 10;
    console.log(`  🔎 搜索: ${input.query}（${count} 条）`);
    return bochaWebSearch(input.query, count);
  },
  {
    name: "web_search",
    description:
      "使用 Bocha 联网搜索 API 检索互联网网页。输入中文或中英结合的搜索关键词，可选 count 指定结果数量。返回标题、URL、摘要、网站名称、图标和发布时间。",
    schema: z.object({
      query: z
        .string()
        .min(1)
        .describe("搜索关键词，优先使用中文，例如：2026年 AI Agent 框架对比、LangGraph 最新动态"),
      count: z
        .number()
        .int()
        .min(1)
        .max(20)
        .optional()
        .describe("返回的搜索结果数量，默认 10 条"),
    }),
  },
);
