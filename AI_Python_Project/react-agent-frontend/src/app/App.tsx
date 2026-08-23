export function App() {
  return (
    <main className="environment-check">
      <section className="environment-check__card" aria-labelledby="environment-title">
        <p className="environment-check__eyebrow">React Agent Frontend</p>
        <h1 id="environment-title">开发环境已就绪</h1>
        <p>
          React、TypeScript、Vite、路由、服务端状态与自动化测试基础设施已经装配。
        </p>
        <p className="environment-check__notice">
          当前仅验证工程环境，尚未开始任何业务功能开发。
        </p>
      </section>
    </main>
  )
}
