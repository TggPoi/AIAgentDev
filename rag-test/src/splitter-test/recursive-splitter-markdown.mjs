import "dotenv/config";
import "cheerio";
import { Document } from "@langchain/core/documents";
import { MarkdownTextSplitter } from "@langchain/textsplitters";

const readmeText = `# Project Name

> A brief description of your project

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

## Features

- ✨ Feature 1
- 🚀 Feature 2
- 💡 Feature 3

## Installation

\`\`\`bash
npm install project-name
\`\`\`

## Usage

### Basic Usage

\`\`\`javascript
import { Project } from 'project-name';

const project = new Project();
project.init();
\`\`\`

### Advanced Usage

\`\`\`javascript
const project = new Project({
  config: {
    apiKey: 'your-api-key',
    timeout: 5000,
  }
});

await project.run();
\`\`\`

## API Reference

### \`Project\`

Main class for the project.

#### Methods

- \`init()\`: Initialize the project
- \`run()\`: Run the project
- \`stop()\`: Stop the project

## Contributing

Contributions are welcome! Please read our [contributing guide](CONTRIBUTING.md).

## License

MIT License`;

const readmeDoc = new Document({
    pageContent: readmeText
});

/*
一段 Markdown 文本，按照标题、换行符、代码块等来分割，每个块 400 字符，重叠 80 字符
markdown 是按照 #、##、### 的子标题来递归分割，因此不用指定分割符，内置了默认的分割符。分割优先级是标题 > 换行符 > 代码块 > 其他文本。
*/
const markdownTextSplitter = new MarkdownTextSplitter({
    chunkSize: 400,
    chunkOverlap: 80
});

const splitDocuments = await markdownTextSplitter.splitDocuments([readmeDoc]);

// console.log(splitDocuments);

splitDocuments.forEach(document => {
    console.log(document);
    console.log('charater length:',document.pageContent.length);
});



/** 测试结果
 * 
 * PS D:\AI_Agent_Project\rag-test> node .\src\splitter-test\recursive-splitter-markdown.mjs        
Document {
  pageContent: '# Project Name\n' +
    '\n' +
    '> A brief description of your project\n' +
    '\n' +
    '[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)\n' +
    '\n' +
    '## Features\n' +
    '\n' +
    '- ✨ Feature 1\n' +
    '- 🚀 Feature 2\n' +
    '- 💡 Feature 3\n' +
    '\n' +
    '## Installation\n' +
    '\n' +
    '```bash\n' +
    'npm install project-name\n' +
    '```',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 240
Document {
  pageContent: '## Installation\n' +
    '\n' +
    '```bash\n' +
    'npm install project-name\n' +
    '```\n' +
    '\n' +
    '## Usage\n' +
    '\n' +
    '### Basic Usage\n' +
    '\n' +
    '```javascript\n' +
    "import { Project } from 'project-name';\n" +
    '\n' +
    'const project = new Project();\n' +
    'project.init();\n' +
    '```\n' +
    '\n' +
    '### Advanced Usage\n' +
    '\n' +
    '```javascript\n' +
    'const project = new Project({\n' +
    '  config: {\n' +
    "    apiKey: 'your-api-key',\n" +
    '    timeout: 5000,\n' +
    '  }\n' +
    '});\n' +
    '\n' +
    'await project.run();\n' +
    '```',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 345
Document {
  pageContent: '## API Reference\n' +
    '\n' +
    '### `Project`\n' +
    '\n' +
    'Main class for the project.\n' +
    '\n' +
    '#### Methods\n' +
    '\n' +
    '- `init()`: Initialize the project\n' +
    '- `run()`: Run the project\n' +
    '- `stop()`: Stop the project\n' +
    '\n' +
    '## Contributing\n' +
    '\n' +
    'Contributions are welcome! Please read our [contributing guide](CONTRIBUTING.md).\n' +
    '\n' +
    '## License\n' +
    '\n' +
    'MIT License',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 291
 */