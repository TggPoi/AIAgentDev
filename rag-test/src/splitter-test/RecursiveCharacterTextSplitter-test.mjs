import "dotenv/config";
import"cheerio";
import { RecursiveCharacterTextSplitter } from"@langchain/textsplitters";
import { Document } from"@langchain/core/documents";
import { getEncoding } from"js-tiktoken"; 

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

//一段日志文本，按照换行符来分割，每个块 150 字符，重叠 20 字符，分割优先级依次是换行符、句号、逗号
// const logTextSplitter = new RecursiveCharacterTextSplitter({
//     chunkSize: 150,
//     chunkOverlap: 20,
//     separators: ['\n', '。', '，']
// });

const enc = getEncoding("cl100k_base");

//重写 lengthFunction，按照 token 数量来计算文本长度，而不是字符数量。这样就能更准确地控制每个 chunk 的 token 数量了。
const logTextSplitter = new RecursiveCharacterTextSplitter({
    chunkSize: 150, //此时这里的150就是按照Token数量来计算的了，而不是字符数量了。
    chunkOverlap: 20,
    separators: ['\n', '。', '，'],
    //按照 token 数量来计算文本长度，而不是字符数量。这样就能更准确地控制每个 chunk 的 token 数量了。
    lengthFunction: (text) => enc.encode(text).length,
});

const splitDocuments = await logTextSplitter.splitDocuments([logDocument]);

// console.log(splitDocuments);

//const enc = getEncoding("cl100k_base");
splitDocuments.forEach(document => {
    console.log(document);
    console.log('charater length:',document.pageContent.length);
    console.log('token length:',enc.encode(document.pageContent).length);
});

/** 测试结果：按照换行符分割后下面的文本超过 chunk size，就会尝试按照句号逗号分割，然后加上 overlap：
 * 相比 CharacterTextSplitter，RecursiveCharacterTextSplitter 就聪明多了，它会优先按照换行符分割，如果分割后的文本超过 chunk size，就会继续按照句号分割，如果还是超过，就会继续按照逗号分割，直到分割后的文本不超过 chunk size 为止。这样就能保证每个 chunk 的语义完整性，同时又不会超过 chunk size。
 * 
 * PS D:\AI_Agent_Project\rag-test> node .\src\RecursiveCharacterTextSplitter-test.mjs
Document {
  pageContent: '[2024-01-15 10:00:00] INFO: Application started\n' +
    '[2024-01-15 10:00:05] DEBUG: Loading configuration file',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 103
token length: 38
Document {
  pageContent: '[2024-01-15 10:00:10] INFO: Database connection established\n' +
    '[2024-01-15 10:00:15] WARNING: Rate limit approaching',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 113
token length: 39
Document {
  pageContent: '[2024-01-15 10:00:20] ERROR: Failed to process request\n' +
    '[2024-01-15 10:00:25] INFO: Retrying operation',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 101
token length: 40
Document {
  pageContent: '[2024-01-15 10:00:30] SUCCESS: Operation completed',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 50
token length: 18
Document {
  pageContent: '[2026-01-10 14:30:00] INFO: 系统开始执行大规模数据迁移任务，本次迁移涉及核心业务数据库中的用户表、订单表、商品库存表、物流信息表、支付记录表、评论数据表等共计十二个关键业务表，预计处理数
据量约500万条记录，数据总大小预估为280GB',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 131
token length: 100
Document {
  pageContent: '，数据总大小预估为280GB，迁移过程将采用分批次增量更新策略以减少对生产环境的影响，同时启用双写机制确保数据一致性，任务预计总耗时约3小时15分钟，迁移完成后将自动触发全面的数据一致性校验流程
以及性能基准测试，请相关运维人员和DBA团队密切关注系统资源使用情况、网络带宽占用率以及任务执行进度',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 147
token length: 147
Document {
  pageContent: '，如遇异常情况请立即启动应急预案并通知技术负责人',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 24
token length: 28
 */



/** 重写 lengthFunction 后的测试结果：每个 chunk 的 token 数量都没有超过 150，因为我们重写了 lengthFunction 来按照 token 数量来计算文本长度了，这样就能更准确地控制每个 chunk 的 token 数量了。
 * 
 * PS D:\AI_Agent_Project\rag-test> node .\src\RecursiveCharacterTextSplitter-test.mjs
Document {
  pageContent: '[2024-01-15 10:00:00] INFO: Application started\n' +
    '[2024-01-15 10:00:05] DEBUG: Loading configuration file\n' +
    '[2024-01-15 10:00:10] INFO: Database connection established\n' +
    '[2024-01-15 10:00:15] WARNING: Rate limit approaching\n' +
    '[2024-01-15 10:00:20] ERROR: Failed to process request\n' +
    '[2024-01-15 10:00:25] INFO: Retrying operation\n' +
    '[2024-01-15 10:00:30] SUCCESS: Operation completed',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 370
token length: 138
Document {
  pageContent: '[2026-01-10 14:30:00] INFO: 系统开始执行大规模数据迁移任务，本次迁移涉及核心业务数据库中的用户表、订单表、商品库存表、物流信息表、支付记录表、评论数据表等共计十二个关键业务表，预计处理数
据量约500万条记录，数据总大小预估为280GB，迁移过程将采用分批次增量更新策略以减少对生产环境的影响',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 159
token length: 135
Document {
  pageContent: '，同时启用双写机制确保数据一致性，任务预计总耗时约3小时15分钟，迁移完成后将自动触发全面的数据一致性校验流程以及性能基准测试，请相关运维人员和DBA团队密切关注系统资源使用情况、网络带宽占用
率以及任务执行进度，如遇异常情况请立即启动应急预案并通知技术负责人',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 129
token length: 130
 */