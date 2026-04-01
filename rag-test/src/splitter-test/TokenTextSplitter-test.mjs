import "dotenv/config";
import"cheerio";
import { TokenTextSplitter } from"@langchain/textsplitters";
import { Document } from"@langchain/core/documents";
import { getEncoding } from"js-tiktoken"; 

const logDocument = new Document({
    pageContent: `[2024-01-15 10:00:00] INFO: Application started
[2024-01-15 10:00:05] DEBUG: Loading configuration file
[2024-01-15 10:00:10] INFO: Database connection established
[2024-01-15 10:00:15] WARNING: Rate limit approaching
[2024-01-15 10:00:20] ERROR: Failed to process request
[2024-01-15 10:00:25] INFO: Retrying operation
[2024-01-15 10:00:30] SUCCESS: Operation completed`
});

const logTextSplitter = new TokenTextSplitter({
    chunkSize: 50,        // 每个块最多 50 个 Token
    chunkOverlap: 10,    // 块之间重叠 10 个 Token
    encodingName: 'cl100k_base',  // OpenAI 使用的编码方式
  });



const splitDocuments = await logTextSplitter.splitDocuments([logDocument]);

// console.log(splitDocuments);

const enc = getEncoding("cl100k_base");
splitDocuments.forEach(document => {
    console.log(document);
    console.log('charater length:',document.pageContent.length);
    console.log('token length:',enc.encode(document.pageContent).length);
});

/** 测试结果：优先保证 token 正好是 50，为了这个不惜强行打断文本。当然，打断后也加了 overlap：
 * 
 * 
 * PS D:\AI_Agent_Project\rag-test> node .\src\TokenTextSplitter-test.mjs    
Document {
  pageContent: '[2024-01-15 10:00:00] INFO: Application started\n' +
    '[2024-01-15 10:00:05] DEBUG: Loading configuration file\n' +   
    '[2024-01-15 10:00',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 121
token length: 50
Document {
  pageContent: '2024-01-15 10:00:10] INFO: Database connection established\n' +
    '[2024-01-15 10:00:15] WARNING: Rate limit approaching\n' +
    '[2024-01-15 10:00',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 130
token length: 50
Document {
  pageContent: '2024-01-15 10:00:20] ERROR: Failed to process request\n' +
    '[2024-01-15 10:00:25] INFO: Retrying operation\n' +
    '[2024-01-15 10:',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 116
token length: 50
Document {
  pageContent: '[2024-01-15 10:00:30] SUCCESS: Operation completed',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 50
token length: 18
 */