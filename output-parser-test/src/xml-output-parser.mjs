import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { XMLOutputParser } from '@langchain/core/output_parsers';

// 初始化模型
const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

const parser = new XMLOutputParser();

const question = `请提取以下文本中的人物信息：阿尔伯特·爱因斯坦出生于 1879 年，是一位伟大的物理学家。

${parser.getFormatInstructions()}`;

console.log('question:', question);

try {
    console.log("🤔 正在调用大模型（使用 XMLOutputParser）...\n");

    const response = await model.invoke(question);

    console.log("📤 模型原始响应:\n");
    console.log(response.content);

    const result = await parser.parse(response.content);

    console.log("\n✅ XMLOutputParser 自动解析的结果:\n");
    console.log(result);

} catch (error) {
    console.error("❌ 错误:", error.message);
}


/**
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\xml-output-parser.mjs
question: 请提取以下文本中的人物信息：阿尔伯特·爱因斯坦出生于 1879 年，是一位伟大的物理学家。

The output should be formatted as a XML file.
1. Output should conform to the tags below.
2. If tags are not given, make them on your own.
3. Remember to always open and close all the tags.

As an example, for the tags ["foo", "bar", "baz"]:
1. String "<foo>
   <bar>
      <baz></baz>
   </bar>
</foo>" is a well-formatted instance of the schema.
2. String "<foo>
   <bar>
   </foo>" is a badly-formatted instance.
3. String "<foo>
   <tag>
   </tag>
</foo>" is a badly-formatted instance.

Here are the output tags:
```
{tags}
```
🤔 正在调用大模型（使用 XMLOutputParser）...

📤 模型原始响应:

```xml
<person>
   <name>阿尔伯特·爱因斯坦</name>
   <birth_year>1879</birth_year>
   <profession>物理学家</profession>
</person>
```

✅ XMLOutputParser 自动解析的结果:

{
  person: [
    { name: '阿尔伯特·爱因斯坦' },
    { birth_year: '1879' },
    { profession: '物理学家' }
  ]
}
 */