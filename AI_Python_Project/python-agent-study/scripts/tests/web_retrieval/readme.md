# Web 检索测试

这些脚本默认使用 Fake HTTP Client 或 MockTransport，不访问公网。真实网络完整流程由 Web 人工验收负责。

## 脚本

| 脚本 | 作用 | 使用方式 |
| --- | --- | --- |
| `test_web_search_tool.py` | 验证 Bocha 请求、site 约束和响应转换。 | 默认 Mock；追加 `--real <query>` 可执行真实 Bocha 验收。 |
| `test_enhanced_web_search.py` | 验证多来源、全文读取、强制站点、主题拒绝、候选池和统一 payload。 | 直接运行。 |
| `test_direct_web_filter_fetch.py` | 验证域名/URL/正文约束、过滤降级、并发全文读取和 Sitemap rescue 决策。 | 直接运行。 |
| `test_direct_web_page_text.py` | 验证正文容器选择、噪声标签清理、SPA 空壳和正文阈值。 | 直接运行。 |
| `test_direct_web_redirect_error.py` | 验证重定向终点约束、exact URL 校验和 Direct Web 错误边。 | 直接运行。 |
| `test_direct_web_sitemap.py` | 验证 Sitemap/robots 解析、URL 排名、复合词和版本片段过滤。 | 直接运行。 |

## 示例

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\tests\web_retrieval\test_direct_web_sitemap.py
.\.venv\Scripts\python.exe scripts\tests\web_retrieval\test_enhanced_web_search.py
```
