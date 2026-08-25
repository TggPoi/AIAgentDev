# React 前端开发环境

> **状态：环境与前端认证生命周期已搭建并验证。** 本文记录可重复的本地工具链与验收命令，不定义产品行为。

## 1. 已验证运行时

2026-08-24 在以下环境完成验证：

- Node.js `24.14.0`。
- pnpm `10.32.1`。
- Windows PowerShell。

`package.json` 使用 engines 和 packageManager 固定最低运行条件，`pnpm-lock.yaml` 固定实际依赖解析。不要混用 npm、yarn 或额外 lockfile。

## 2. 基础技术栈

运行依赖：

- React 19。
- React DOM 19。
- React Router 7。
- TanStack Query 5。

开发与验证依赖：

- Vite 8 与 React plugin。
- TypeScript 6。
- Vitest 4、jsdom 29、Testing Library 和 MSW 2。
- `openapi-typescript` `7.13.0`，用于从已提交的后端 OpenAPI snapshot 生成 HTTP Transport Type。
- Oxlint。

当前没有 Tailwind、UI Component Library、Playwright 或 Cypress。

2026-08-25 从 npm registry 核对并精确锁定 `openapi-typescript` `7.13.0`。该版本及其运行依赖在 Node `24.14.0` 下实际完成安装、CLI 生成与 drift check；其 package manifest 没有更高的 Node 限制，但仍只声明 TypeScript peer `^5.x`，而本项目为 TypeScript `6.0.3`。当前生成结果已通过 TypeScript 6 typecheck、全量测试和 production build；这是显式记录的 upstream peer-range 风险，不使用配置静默隐藏。后续升级生成器时必须先重新核对该 peer 声明。

当前机器的 Node `24.14.0` 不满足 jsdom 30 要求的 `24.15.0`，因此 lockfile 使用兼容的 jsdom 29。升级 jsdom 前必须先核对项目 Node runtime，不得只改版本号。

## 3. 首次安装

```powershell
pnpm install --frozen-lockfile
```

MSW 是明确允许执行安装脚本的唯一依赖，记录在 `pnpm-workspace.yaml`。新增需要 build script 的依赖时必须单独审查，不能批量放行。

本地配置从 `.env.example` 复制为 `.env.local`；真实环境值不提交 Git。当前示例只包含非秘密的后端 base URL。

## 4. 后端 Contract Snapshot 与类型生成

当前 snapshot 从相邻的 `python-agent-study` 真实 FastAPI app 导出。2026-08-25 的最新导出证据：monorepo/backend contract HEAD `313d634`，OpenAPI `3.1.0` 包含 58 paths 和 88 schemas；后端 `scripts/tests/document_security/test_auth_validation_contract.py`、既有 Auth focused regressions 与 `scripts/tests/agent_research/test_rag_stream_contract.py` 通过。三个受影响 Auth route 的 `422` 已统一引用安全的 `RequestValidationErrorResponse`。

从前端目录执行以下 PowerShell 命令可重复导出当前后端 OpenAPI：

```powershell
Push-Location ..\python-agent-study
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -B -c "import json; from pathlib import Path; from fast_app.main import app; target=Path('../react-agent-frontend/contracts/backend-openapi.json'); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')"
Pop-Location
```

生成并检查 TypeScript Transport Type：

```powershell
pnpm contracts:generate
pnpm contracts:check
```

`contracts:check` 在临时目录重新调用同一 CLI 并逐字节比较提交的 `src/api/generated/backend-schema.ts`，不会改写工作树。Snapshot 和 generated file 都是完整后端契约事实，因此会包含后端存在但 Initial React 禁止调用的兼容/开发 endpoint；能生成类型不代表前端获准调用它们。

## 5. 开发服务器

```powershell
pnpm dev
```

开发服务器固定监听 `http://127.0.0.1:5173` 并启用 strict port。端口被占用时会明确失败，不会静默切换，便于代理、测试和文档保持一致。

生产构建预览：

```powershell
pnpm build
pnpm preview
```

预览服务器固定监听 `http://127.0.0.1:4173`。

## 6. 质量检查

单项命令：

```powershell
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

提交前统一运行：

```powershell
pnpm check
pnpm audit --audit-level high
```

`pnpm check` 按 generated contract drift、lint、类型检查、测试、生产构建顺序执行。任何一项失败都不能宣称环境或功能可交付。

## 7. 测试基础设施

- Vitest 使用 jsdom。
- `src/test/setup.ts` 启动 MSW Node server 并加载 jest-dom matcher。
- 未被 handler 声明的网络请求在测试中直接报错，防止测试意外访问真实后端。
- `App.test.tsx` 当前验证认证 bootstrap、受保护路由重定向和安全 return path；Feature 级网络行为由对应 MSW tests 覆盖。

业务测试应把 handler 和 fixture 放在对应 feature 或共享测试目录，不修改环境检查页承载业务断言。

## 8. 当前已验证结果

- `pnpm install --frozen-lockfile`：通过。
- `pnpm check`：通过。
- Generated contract drift check：通过。
- Vitest：10 个测试文件、47 个测试通过。
- Vite production build：通过。
- `pnpm audit --audit-level high`：0 个已知漏洞。
- Vite dev server：220 ms 启动，首页 HTTP 200，验证后已停止。
- 本地浏览器：通过人工 smoke verification 确认登录页在桌面与 360px 窄屏正确渲染、无横向溢出、表单语义和焦点样式可用，console 无 warning/error，验证标签页已关闭。

## 9. 当前边界

当前已经建立 generated HTTP Transport Type、共享 HTTP/error seam、SSE framing、Public Event protocol module，以及唯一 AuthProvider 所有权下的 token、refresh、身份/能力快照、登录、注销、修改密码和安全 return path。`src/app/App.tsx` 只装配认证所需的最小路由；完整 Application Shell、会话、Chat reducer、文档、TaskPlan reducer、用户管理、NL2SQL 和 Web Search 仍未实现。

开始业务模块前，必须遵守 `AGENTS.md` 的文档门禁，并读取对应 feature 规范。

关键 browser flow 当前同样采用人工 smoke verification；Vitest、jsdom、React Testing Library 和 MSW 不等价于自动 E2E。未经明确架构与依赖批准，不得自行安装 Playwright 或 Cypress。
