import { tool } from "langchain";
import { z } from "zod";

const BOCHA_API_URL = "https://api.bochaai.com/v1/web-search";

export const DEFAULT_MAX_SEARCH_CALLS = 2;
export const DEFAULT_MAX_RESULTS = 3;
export const DEFAULT_MAX_SUMMARY_CHARS = 280;

export function clampSearchCount(count, maxResults = DEFAULT_MAX_RESULTS) {
  const numericCount = Number.isInteger(count) ? count : maxResults;
  return Math.min(Math.max(numericCount, 1), maxResults);
}

function truncate(text, maxChars) {
  const normalized = String(text ?? "").replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) return normalized;
  return `${normalized.slice(0, maxChars - 1)}…`;
}

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

export function createCompactWebSearch({
  maxCalls = DEFAULT_MAX_SEARCH_CALLS,
  maxResults = DEFAULT_MAX_RESULTS,
  maxSummaryChars = DEFAULT_MAX_SUMMARY_CHARS,
} = {}) {
  let completedCalls = 0;

  return tool(
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
