# React Agent Frontend

本目录是 `python-agent-study` 后端的 React 工作台。当前只完成开发环境装配，业务功能尚未开始实现。

详细的已验证版本、命令和故障边界见 `docs/DEVELOPMENT.md`。

## 环境要求

- Node.js 24 或更高版本。
- pnpm 10 或更高版本。

## 常用命令

```powershell
pnpm install --frozen-lockfile
pnpm dev
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm check
```

开发服务器固定监听 `http://127.0.0.1:5173`；生产构建输出到 `dist/`。

## 当前边界

- 已装配 React、TypeScript、Vite、React Router 和 TanStack Query。
- 已装配 Vitest、Testing Library、MSW、jsdom 和 Oxlint。
- `src/app/App.tsx` 只是环境检查页，不代表业务页面设计。
- 开始业务实现前必须读取 `AGENTS.md`、`docs/SPEC.md`、`docs/ARCHITECTURE.md`、`docs/DEVELOPMENT.md` 和目标 feature 文档。
