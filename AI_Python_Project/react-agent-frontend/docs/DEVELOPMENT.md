# React 前端开发环境

> **状态：环境已搭建并验证，业务功能尚未开始。** 本文记录可重复的本地工具链与验收命令，不定义产品行为。

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
- Oxlint。

当前机器的 Node `24.14.0` 不满足 jsdom 30 要求的 `24.15.0`，因此 lockfile 使用兼容的 jsdom 29。升级 jsdom 前必须先核对项目 Node runtime，不得只改版本号。

## 3. 首次安装

```powershell
pnpm install --frozen-lockfile
```

MSW 是明确允许执行安装脚本的唯一依赖，记录在 `pnpm-workspace.yaml`。新增需要 build script 的依赖时必须单独审查，不能批量放行。

本地配置从 `.env.example` 复制为 `.env.local`；真实环境值不提交 Git。当前示例只包含非秘密的后端 base URL。

## 4. 开发服务器

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

## 5. 质量检查

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

`pnpm check` 按 lint、类型检查、测试、生产构建顺序执行。任何一项失败都不能宣称环境或功能可交付。

## 6. 测试基础设施

- Vitest 使用 jsdom。
- `src/test/setup.ts` 启动 MSW Node server 并加载 jest-dom matcher。
- 未被 handler 声明的网络请求在测试中直接报错，防止测试意外访问真实后端。
- 初始 `App.test.tsx` 只证明 React、Provider、jsdom、Testing Library、MSW setup 与路径别名能一起运行。

业务测试应把 handler 和 fixture 放在对应 feature 或共享测试目录，不修改环境检查页承载业务断言。

## 7. 当前已验证结果

- `pnpm install --frozen-lockfile`：通过。
- `pnpm check`：通过。
- Vitest：1 个测试文件、1 个测试通过。
- Vite production build：通过。
- `pnpm audit --audit-level high`：0 个已知漏洞。
- Vite dev server：220 ms 启动，首页 HTTP 200，验证后已停止。
- 本地浏览器：React 根节点成功挂载，环境标题与边界提示可见，console 无 warning/error，验证标签页已关闭。

## 8. 当前边界

`src/app/App.tsx` 只是环境检查页。当前没有登录、HTTP client、SSE parser、路由页面、会话、文档、TaskPlan、用户管理、NL2SQL 或 Web Search 业务实现。

开始业务模块前，必须遵守 `AGENTS.md` 的文档门禁，并读取对应 feature 规范。
