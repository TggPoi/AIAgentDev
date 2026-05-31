# Node.js 内置测试运行器 node:test 调研简报

## 结论

`node:test` 是 Node.js 自 v18.0.0 引入、v20.0.0 稳定的内置测试模块，适合小型 JavaScript CLI 项目的基础测试需求，可零依赖运行。

## 适用场景

1. **零依赖小型 CLI 项目**：项目仅需基础测试功能，避免引入 Jest/Mocha 等外部依赖，减少 `node_modules` 体积和安装时间。

2. **快速原型验证**：开发初期需要快速搭建测试框架，`node:test` 提供 `test`、`describe`、`it` 等简洁 API，配合 `node --test` 命令即可运行。

3. **CI/CD 简化配置**：Node.js 18+ 环境可直接使用 `node --test` 运行测试，无需配置额外的测试命令或安装步骤。

## 限制

1. **功能相对基础**：缺少内置断言库（需配合 `node:assert` 使用）、代码覆盖率统计、快照测试等高级功能，复杂测试场景需额外工具补充。

2. **生态兼容性有限**：部分第三方测试工具（如 sinon mocking 库、测试报告生成器）对 `node:test` 的支持不如 Jest/Mocha 成熟。

## 建议

**推荐使用**：若项目为小型 CLI 工具（<1000 行代码），测试需求简单（单元测试为主），且团队使用 Node.js 18+ 版本，`node:test` 是轻量、低维护成本的选择。

**谨慎使用**：若项目需要复杂 mocking、快照测试、并行测试或丰富的断言匹配器，建议仍采用 Jest 等成熟框架。

## 来源

Node.js 官方文档 (nodejs.org/api/test.html)
