# 外部集成测试

## 脚本

| 脚本 | 作用 | 使用方式 |
| --- | --- | --- |
| `test_chatgpt_code_bridge.py` | 验证只读代码桥接的路径限制、敏感文件拒绝、Bearer 鉴权、OpenAPI 和 MCP STDIO。 | 无真实 Tunnel 依赖，直接运行。 |
| `test_gitlab_enterprise_sync.py` | 验证 GitLab Client、版本身份、归档安全、MR 幂等、合并同步和失败分类。 | 默认使用 Fake；真实存储/队列分别设置 `RUN_GITLAB_LIVE_STORE_TEST=1`、`RUN_GITLAB_LIVE_QUEUE_TEST=1`。 |
| `test_langsmith_tracing.py` | 验证集中式 LangSmith naming、metadata、tags 和敏感字段策略。 | 无需连接 LangSmith；建议运行前关闭环境中的 tracing。 |
| `test_mcp_tool_adapter.py` | 启动本地 MCP demo server，验证工具发现、白名单和 Agent Tool 调用。 | 无公网依赖，直接运行。 |

## 示例

```powershell
$env:PYTHONPATH="src"
$env:LANGSMITH_TRACING="false"
.\.venv\Scripts\python.exe scripts\tests\integrations\test_chatgpt_code_bridge.py
.\.venv\Scripts\python.exe scripts\tests\integrations\test_mcp_tool_adapter.py
```
