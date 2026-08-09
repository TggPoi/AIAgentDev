# Ingestion 测试

## 脚本

| 脚本 | 作用 | 使用方式 |
| --- | --- | --- |
| `test_markdown_ingestion.py` | 验证 Markdown 读取、Chunk、metadata、稳定 ID，并可选择写入 ES/Milvus。 | 默认 dry-run；真实写入需追加 `--write-stores --write-mode replace_docs --yes`。 |
| `test_markdown_parent_child.py` | 验证 Markdown 父子 Chunk、稳定 ID、存储行、父上下文扩展和 Prompt Guard 边界。 | 无外部服务，直接运行。 |
| `test_office_ingestion.py` | 验证 PPTX/XLSX loader、增量 diff、OOXML 拒绝、接口限制、幂等、心跳和 ACL。 | 默认无外部依赖；可追加 `--real-db`、`--real-stores` 或 `--real-worker`。 |

## 示例

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe scripts\tests\ingestion\test_markdown_parent_child.py
.\.venv\Scripts\python.exe scripts\tests\ingestion\test_office_ingestion.py
```
