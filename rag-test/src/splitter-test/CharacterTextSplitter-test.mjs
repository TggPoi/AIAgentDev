import "dotenv/config";
import"cheerio";
import { CharacterTextSplitter } from"@langchain/textsplitters";
import { Document } from"@langchain/core/documents";
import { getEncoding } from"js-tiktoken"; 

//短文本测试
// const logDocument = new Document({
//     pageContent: `[2024-01-15 10:00:00] INFO: Application started
// [2024-01-15 10:00:05] DEBUG: Loading configuration file
// [2024-01-15 10:00:10] INFO: Database connection established
// [2024-01-15 10:00:15] WARNING: Rate limit approaching
// [2024-01-15 10:00:20] ERROR: Failed to process request
// [2024-01-15 10:00:25] INFO: Retrying operation
// [2024-01-15 10:00:30] SUCCESS: Operation completed`
// });

//长文本测试
const logDocument = new Document({
    pageContent: `[2024-01-15 10:00:00] INFO: Application started
[2024-01-15 10:00:05] DEBUG: Loading configuration file
[2024-01-15 10:00:10] INFO: Database connection established
[2024-01-15 10:00:15] WARNING: Rate limit approaching
[2024-01-15 10:00:20] ERROR: Failed to process request
[2024-01-15 10:00:25] INFO: Retrying operation
[2024-01-15 10:00:30] SUCCESS: Operation completed
[2026-01-10 14:30:00] INFO: 系统开始执行大规模数据迁移任务，本次迁移涉及核心业务数据库中的用户表、订单表、商品库存表、物流信息表、支付记录表、评论数据表等共计十二个关键业务表，预计处理数据量约500万条记录，数据总大小预估为280GB，迁移过程将采用分批次增量更新策略以减少对生产环境的影响，同时启用双写机制确保数据一致性，任务预计总耗时约3小时15分钟，迁移完成后将自动触发全面的数据一致性校验流程以及性能基准测试，请相关运维人员和DBA团队密切关注系统资源使用情况、网络带宽占用率以及任务执行进度，如遇异常情况请立即启动应急预案并通知技术负责人
`
});

//一段日志文本，按照换行符来分割，每个块 200 字符，重叠 20 字符
const logTextSplitter = new CharacterTextSplitter({
    separator: '\n',
    chunkSize: 200,
    chunkOverlap: 20
});

const splitDocuments = await logTextSplitter.splitDocuments([logDocument]);

// console.log(splitDocuments);

const enc = getEncoding("cl100k_base");
splitDocuments.forEach(document => {
    console.log(document);
    console.log('charater length:',document.pageContent.length);
    console.log('token length:',enc.encode(document.pageContent).length);
});

/** 短文本测试结果：chunk 的大小也没有到 200，为什么会分为3块？
 * 因为 splitter 会优先保证语义完整，宁愿 chunk 小一点，也不愿意在一个日志条目中间切断。比如第一个 chunk 包含了前3条日志，第二个 chunk 包含了第4-6条日志，第三个 chunk 包含了最后一条日志。每个 chunk 的字符数都没有超过 200，因为 splitter 在分割时会尽量保持每条日志的完整性，而不是简单地按照字符数来切割。
 * 
 * PS D:\AI_Agent_Project\rag-test> node .\src\CharacterTextSplitter-test.mjs
Document {
  pageContent: '[2024-01-15 10:00:00] INFO: Application started\n' +
    '[2024-01-15 10:00:05] DEBUG: Loading configuration file\n' +
    '[2024-01-15 10:00:10] INFO: Database connection established',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 163     这里到了 160 左右字符的时候，发现加上下一个文本就超过 200 了，所以会放到下一个块。
token length: 58
Document {
  pageContent: '[2024-01-15 10:00:15] WARNING: Rate limit approaching\n' +
    '[2024-01-15 10:00:20] ERROR: Failed to process request\n' +
    '[2024-01-15 10:00:25] INFO: Retrying operation',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 155
token length: 60
Document {
  pageContent: '[2024-01-15 10:00:30] SUCCESS: Operation completed',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 50
token length: 18
 */

//这里因为没有被断开的文本，所以就没有需要加 overlap 重复的，只有被断开的文本才有 overlap，比如如果我们把 chunkSize 调小到 100，那么就会在每条日志中间切断，这时候就会有 overlap 的文本了。



/** 长文本测试结果
 * CharacterTextSplitter 非常死板，你告诉它按照换行符分割，它就会严格按照这个，就算超过了 chunk size 也不拆分。所以一般还是用 RecursiveCharacterTextSplitter
 * 
 * PS D:\AI_Agent_Project\rag-test> node .\src\CharacterTextSplitter-test.mjs
Document {
  pageContent: '[2024-01-15 10:00:00] INFO: Application started\n' +
    '[2024-01-15 10:00:05] DEBUG: Loading configuration file\n' +
    '[2024-01-15 10:00:10] INFO: Database connection established',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 163
token length: 58
Document {
  pageContent: '[2024-01-15 10:00:15] WARNING: Rate limit approaching\n' +
    '[2024-01-15 10:00:20] ERROR: Failed to process request\n' +
    '[2024-01-15 10:00:25] INFO: Retrying operation',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 155
token length: 60
Document {
  pageContent: '[2024-01-15 10:00:30] SUCCESS: Operation completed',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 50
token length: 18
Document {
  pageContent: '[2026-01-10 14:30:00] INFO: 系统开始执行大规模数据迁移任务，本次迁移涉及核心业务数据库中的用户表、订单表、商品库存表、物流信息表、支付记录表、评论数据表等共计十二个关键业务表，预计处理数
据量约500万条记录，数据总大小预估为280GB，迁移过程将采用分批次增量更新策略以减少对生产环境的影响，同时启用双写机制确保数据一致性，任务预计总耗时约3小时15分钟，迁移完成后将自动触发全面的数据一致性校验流 
程以及性能基准测试，请相关运维人员和DBA团队密切关注系统资源使用情况、网络带宽占用率以及任务执行进度，如遇异常情况请立即启动应急预案并通知技术负责人',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 288
token length: 265
 */