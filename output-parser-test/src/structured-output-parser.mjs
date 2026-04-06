import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { StructuredOutputParser } from '@langchain/core/output_parsers';

// 初始化模型
const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

// 定义输出结构 StructuredOutputParser，它可以指定具体的 json 结构，并且在解析时会自动提取出相关字段的值
const parser = StructuredOutputParser.fromNamesAndDescriptions({
    name: "姓名",
    birth_year: "出生年份",
    nationality: "国籍",
    major_achievements: "主要成就，用逗号分隔的字符串",
    famous_theory: "著名理论"
});

const question = `请介绍一下爱因斯坦的信息。

${parser.getFormatInstructions()}`;

console.log('question:', question)

try {
    console.log("🤔 正在调用大模型（使用 StructuredOutputParser）...\n");

    const response = await model.invoke(question);

    console.log("📤 模型原始响应:\n");
    console.log(response.content);

    const result = await parser.parse(response.content);

    console.log("\n✅ StructuredOutputParser 自动解析的结果:\n");
    console.log(result);
    console.log(`姓名: ${result.name}`);
    console.log(`出生年份: ${result.birth_year}`);
    console.log(`国籍: ${result.nationality}`);
    console.log(`著名理论: ${result.famous_theory}`);
    console.log(`主要成就: ${result.major_achievements}`);

} catch (error) {
    console.error("❌ 错误:", error.message);
}


/** 可以看到多了一堆提示词
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\structured-output-parser.mjs
question: 请介绍一下爱因斯坦的信息。

You must format your output as a JSON value that adheres to a given "JSON Schema" instance.

"JSON Schema" is a declarative language that allows you to annotate and validate JSON documents.

For example, the example "JSON Schema" instance {{"properties": {{"foo": {{"description": "a list of test words", "type": "array", "items": {{"type": "string"}}}}}}, "required": ["foo"]}}
would match an object with one required property, "foo". The "type" property specifies "foo" must be an "array", and the "description" property semantically describes it as "a list of test words". The items within "foo" must be strings.
Thus, the object {{"foo": ["bar", "baz"]}} is a well-formatted instance of this example "JSON Schema". The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not well-formatted.

Your output will be parsed and type-checked according to the provided schema instance, so make sure all fields in your output match the schema exactly and there are no trailing commas!

Here is the JSON Schema instance your output must adhere to. Include the enclosing markdown codeblock:
```json
{"type":"object","properties":{"name":{"type":"string","description":"姓名"},"birth_year":{"type":"string","description":"出生年份"},"nationality":{"type":"string","description":"国籍"},"major_achievements":{"type":"string","description":"主要成就，用逗号分隔的字符串"},"famous_theory":{"type":"string","description":"著名理论"}},"required":["name","birth_year","nationality","major_achievements","famous_theory"],"additionalProperties":false,"$schema":"http://json-schema.org/draft-07/schema#"}
```

🤔 正在调用大模型（使用 StructuredOutputParser）...

📤 模型原始响应:

```json
{
  "name": "阿尔伯特·爱因斯坦",
  "birth_year": "1879",
  "nationality": "德国/瑞士/美国",
  "major_achievements": "提出光量子假说，解释光电效应，发现布朗运动，质能等价公式",
  "famous_theory": "相对论"
}
```

✅ StructuredOutputParser 自动解析的结果:

{
  name: '阿尔伯特·爱因斯坦',
  birth_year: '1879',
  nationality: '德国/瑞士/美国',
  major_achievements: '提出光量子假说，解释光电效应，发现布朗运动，质能等价公式',
  famous_theory: '相对论'
}
姓名: 阿尔伯特·爱因斯坦
出生年份: 1879
国籍: 德国/瑞士/美国
著名理论: 相对论
主要成就: 提出光量子假说，解释光电效应，发现布朗运动，质能等价公式
 */