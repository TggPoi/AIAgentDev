import "dotenv/config";
import { BaseDocumentCompressor } from "@langchain/core/retrievers/document_compressors";

//langchain 提供了 rerank 模型的基类 BaseDocumentCompressor，但是没有 qwen 重排模型对应的封装，需要自己封装
export class DashScopeRerank extends BaseDocumentCompressor {

  constructor({ apiKey, model = "qwen3-rerank", topN = 3, baseUrl } = {}) {
    super();
    this.apiKey = apiKey;
    this.model = model;
    this.topN = topN;
    this.baseUrl = baseUrl ?? process.env.RERANK_URL;
  }

  async compressDocuments(documents, query, _callbacks) {

    //直接通过http的方式请求模型，调用接口，传入 query 和 documents，拿到重排序后的文档
    const res = await fetch(this.baseUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: this.model,
        input: {
          query,
          documents: documents.map((d) => d.pageContent),
        },
        parameters: {
          return_documents: false,
          top_n: this.topN,
        },
      }),
    });

    const json = await res.json();
    if (!res.ok) {
      throw new Error(
        `DashScope rerank ${res.status}: ${JSON.stringify(json)}`,
      );
    }

    const results = json?.output?.results;
    if (!Array.isArray(results)) {
      throw new Error(`unexpected rerank response: ${JSON.stringify(json)}`);
    }

    return results.map((item) => documents[item.index]);
  }
}