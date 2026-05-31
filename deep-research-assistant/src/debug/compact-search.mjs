import { tool } from "langchain";
import { z } from "zod";

const BOCHA_API_URL = "https://api.bochaai.com/v1/web-search";

//总搜索次数
export const DEFAULT_MAX_SEARCH_CALLS = 2;
//单次搜索结果数量
export const DEFAULT_MAX_RESULTS = 3;
//单条摘要长度
export const DEFAULT_MAX_SUMMARY_CHARS = 280;

/**
 * 将调用方请求的搜索结果数量限制在合法范围内。
 * @param {number | undefined} count 调用方请求的结果数量；缺失或不是整数时使用 maxResults。
 * @param {number} maxResults 单次搜索允许返回的最大结果数量。
 * @returns {number} 位于 1 到 maxResults 之间的整数。
 */
export function clampSearchCount(count, maxResults = DEFAULT_MAX_RESULTS) {
  const numericCount = Number.isInteger(count) ? count : maxResults;
  return Math.min(Math.max(numericCount, 1), maxResults);
}

/**
 * 将任意值转换为单行文本，并在超过指定长度时截断。
 * @param {unknown} text 需要规范化的原始内容。
 * @param {number} maxChars 输出允许包含的最大字符数。
 * @returns {string} 已折叠空白并按需截断的文本。
 */
function truncate(text, maxChars) {
  const normalized = String(text ?? "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) return normalized;
  return `${normalized.slice(0, maxChars - 1)}…`;
}

/**
 * 将搜索接口返回的网页数组格式化为适合 Agent 阅读的精简文本。
 * @param {Array<{name?: string, url?: string, summary?: string, siteName?: string}>} webpages
 * 搜索接口返回的网页记录。
 * @param {{maxResults?: number, maxSummaryChars?: number}} options 格式化限制。
 * @returns {string} 由标题、URL、摘要和站点组成的多段文本。
 */
export function formatCompactPages(
  webpages,
  {
    maxResults = DEFAULT_MAX_RESULTS,
    maxSummaryChars = DEFAULT_MAX_SUMMARY_CHARS,
  } = {},
) {
  return webpages
    .slice(0, maxResults)
    .map(
      (page, index) =>
        [
          `结果 ${index + 1}`,
          `标题: ${truncate(page.name, 100)}`,
          `URL: ${page.url ?? ""}`,
          `摘要: ${truncate(page.summary, maxSummaryChars)}`,
          `站点: ${truncate(page.siteName, 60)}`,
        ].join("\n"),
    )
    .join("\n\n");
}

/**
 * 创建一个带独立调用次数计数器的受限联网搜索工具。
 * @param {{maxCalls?: number, maxResults?: number, maxSummaryChars?: number}} options
 * 搜索次数、单次结果数量和单条摘要长度限制。
 * @returns {import("langchain").StructuredTool} 可注册到 Agent 的 compact_web_search 工具。
 */
export function createCompactWebSearch({
  maxCalls = DEFAULT_MAX_SEARCH_CALLS,
  maxResults = DEFAULT_MAX_RESULTS,
  maxSummaryChars = DEFAULT_MAX_SUMMARY_CHARS,
} = {}) {
  let completedCalls = 0;

  return tool(
    /**
     * 调用 Bocha 搜索接口，并将结果压缩为适合 Agent 使用的文本。
     * @param {{query: string, count?: number}} input 搜索关键词和可选结果数量。
     * @returns {Promise<string>} 搜索摘要，或可直接交给 Agent 处理的错误说明。
     */
    async ({ query, count }) => {
      if (completedCalls >= maxCalls) {
        return `已达到搜索次数上限：最多 ${maxCalls} 次。请使用已有结果完成调研。`;
      }
      completedCalls += 1;

      const apiKey = process.env.BOCHA_API_KEY?.trim();
      if (!apiKey) {
        return "未配置 BOCHA_API_KEY。请根据已有知识完成简短说明，并明确标注缺少联网检索。";
      }

      const limitedCount = clampSearchCount(count, maxResults);
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
          count: limitedCount,
        }),
      });

      if (!response.ok) {
        const errorText = truncate(await response.text(), 300);
        return `搜索请求失败，状态码 ${response.status}：${errorText}`;
      }

      let json;
      try {
        json = await response.json();
      } catch (error) {
        return `搜索结果 JSON 解析失败：${error.message}`;
      }

      if (json.code !== 200 || !json.data) {
        return `搜索接口返回错误：${truncate(json.msg ?? "未知错误", 300)}`;
      }

      const webpages = json.data.webPages?.value ?? [];
      if (!webpages.length) {
        return `未找到与“${query}”相关的结果。`;
      }

      return formatCompactPages(webpages, { maxResults, maxSummaryChars });
    },
    {
      name: "compact_web_search",
      description:
        "执行受限联网搜索。仅用于当前简短调研任务；最多调用两次，每次最多返回三个经过截断的网页摘要。",
      schema: z.object({
        query: z.string().min(1).describe("简洁、聚焦的搜索关键词"),
        count: z
          .number()
          .int()
          .min(1)
          .max(maxResults)
          .optional()
          .describe(`返回结果数量，最多 ${maxResults} 条`),
      }),
    },
  );
}
