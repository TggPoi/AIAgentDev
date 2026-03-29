import "dotenv/config";
import "cheerio";
import { CheerioWebBaseLoader } from"@langchain/community/document_loaders/web/cheerio";
import { RecursiveCharacterTextSplitter } from "@langchain/textsplitters";

// 这个示例展示了如何使用 CheerioWebBaseLoader 从一个网页加载内容，并将其转换为文档对象。我们指定了一个 CSS 选择器来提取网页中的特定部分（在这个例子中是 '.main-area p'，即主区域内的段落）。加载完成后，我们将得到一个包含提取内容的文档数组，可以用于后续的处理，如文本分析、向量化等。
const cheerioLoader = new CheerioWebBaseLoader(
"https://juejin.cn/post/7233327509919547452",
  {
    selector: '.main-area p' //提取页面元素 .main-area 下所有 p 标签的内容
  }
);

const documents = await cheerioLoader.load();

console.log(documents);

const textSplitter = new RecursiveCharacterTextSplitter({
    chunkSize: 400,  // 每个分块的字符数
    chunkOverlap: 50,  // 分块之间的重叠字符数
    separators: ["。","！","？"],  // 分割符，优先使用段落分隔 分割符是优先 。 其次 ！？
});

const splitDocuments = await textSplitter.splitDocuments(documents);

// console.log(documents);
console.log(splitDocuments);