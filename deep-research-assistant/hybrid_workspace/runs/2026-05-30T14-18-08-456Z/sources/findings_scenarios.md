## 适用场景

1. **场景一：快速原型验证**
   在开发小型 CLI 工具的初期阶段，开发者需要快速验证核心功能逻辑。node:test 作为 Node.js 内置模块，无需安装任何依赖即可使用，通过 `require('node:test')` 或 `import test from 'node:test'` 直接引入。配合 `node --test` 命令可直接运行测试，非常适合快速迭代和验证 CLI 命令的输入输出行为。

2. **场景二：轻量级 CI/CD 集成**
   小型 CLI 项目通常追求极简的依赖结构。node:test 内置于 Node.js 18+ 版本，无需额外配置测试框架（如 Jest、Mocha），减少了 package.json 的依赖项。在 CI 环境中只需确保 Node.js 版本兼容即可运行测试，降低了环境配置复杂度，适合 GitHub Actions 等轻量级持续集成场景。

3. **场景三：命令行参数解析测试**
   CLI 项目的核心是命令行参数解析和用户交互逻辑。node:test 支持异步测试和子进程测试，可以方便地测试 `process.argv` 解析、命令选项验证、错误处理等场景。通过 `test()` 的异步支持和 `assert` 模块配合，能够简洁地验证 CLI 工具在不同输入参数下的行为是否符合预期。
