import { Inject,Injectable } from'@nestjs/common';
import { ChatOpenAI } from'@langchain/openai';
import { PromptTemplate } from'@langchain/core/prompts';
import type { Runnable } from'@langchain/core/runnables';
import { StringOutputParser } from'@langchain/core/output_parsers';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class AiService {
  private readonly chain: Runnable;

/* 未引入Config包时的做法
constructor() {
    const prompt = PromptTemplate.fromTemplate(
      '请回答以下问题：\n\n{query}',
    );
    const model = new ChatOpenAI({
      temperature: 0.7,
      modelName: 'qwen-plus',
      apiKey: 'sk-d48c6130bd384f358b86a18ec9522570',
      configuration: {
        baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
      },
    });
    this.chain = prompt.pipe(model).pipe(new StringOutputParser());
  }
*/

/* 未使用工厂模式注入模型时的做法
constructor(@Inject(ConfigService) configService: ConfigService,) {
    const prompt = PromptTemplate.fromTemplate(
      '请回答以下问题：\n\n{query}',
    );
    const model = new ChatOpenAI({
      temperature: 0.7,
      model: configService.get('MODEL_NAME'),
      apiKey: configService.get('OPENAI_API_KEY'),
      configuration: {
        baseURL: configService.get('OPENAI_BASE_URL')
      },
    });
    this.chain = prompt.pipe(model).pipe(new StringOutputParser());
  }
*/

//使用工厂模式注入模型的做法，这样就把模型的配置和创建逻辑都放在 module 里了，service 只负责使用模型来处理输入输出，职责更单一清晰
//这里的ChatOpenAI是参数类型标注，如果忽略这个参数类型，TypeScript 可能无法正确推断出 model 的类型，此时model就是any类型，
// 从而导致在使用 model 时缺乏类型提示和检查，增加了出错的风险。通过明确标注参数类型，可以让 TypeScript 更好地理解代码结构，提高开发效率和代码质量。
  constructor(@Inject('CHAT_MODEL') model: ChatOpenAI) {
    const prompt = PromptTemplate.fromTemplate(
      '请回答以下问题：\n\n{query}',
    );
    // const model = new ChatOpenAI({
    //   temperature: 0.7,
    //   model: configService.get('MODEL_NAME'),
    //   apiKey: configService.get('OPENAI_API_KEY'),
    //   configuration: {
    //     baseURL: configService.get('OPENAI_BASE_URL')
    //   },
    // });
    this.chain = prompt.pipe(model).pipe(new StringOutputParser());
  }

async runChain(query: string): Promise<string> {
    return this.chain.invoke({ query });
  }

async *streamChain(query: string): AsyncGenerator<string> {
  const stream = await this.chain.stream({ query });
  for await (const chunk of stream) {
    yield chunk;
  }
}
}