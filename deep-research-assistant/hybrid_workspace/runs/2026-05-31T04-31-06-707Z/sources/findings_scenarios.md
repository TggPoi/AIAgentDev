# Node.js 内置测试运行器 node:test 在小型 JavaScript CLI 项目中的适用场景

## 场景 1：快速原型验证
在 CLI 工具开发初期，node:test 无需安装任何依赖即可编写和运行单元测试，适合快速验证核心功能逻辑是否正确。

## 场景 2：零依赖轻量项目
对于追求极简依赖的小型 CLI 项目，node:test 作为 Node.js 内置模块可避免引入 Jest、Mocha 等第三方测试框架，减少 node_modules 体积和安装时间。

## 场景 3：CI/CD 简化配置
在持续集成环境中，node:test 可直接通过 `node --test` 命令运行，无需额外配置测试脚本或安装依赖，简化 CI 流程并提高执行效率。
