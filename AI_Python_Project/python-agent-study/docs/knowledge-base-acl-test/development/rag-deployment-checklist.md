# RAG 后端本地部署验收清单

> 本文档基于 RAG 后端部署规范整理，用于本地部署完成后的逐项验收。

---

## 一、环境准备

- [ ] `.env` 文件已创建并包含所有必要配置
- [ ] `JWT_SECRET_KEY` 不为空
- [ ] `API_KEY_PEPPER` 不为空
- [ ] `AUTH_ENABLED=true` 时认证配置完整
- [ ] `DATABASE_URL` 指向正确的 PostgreSQL 实例
- [ ] `MILVUS_HOST` / `MILVUS_PORT` 配置正确
- [ ] `ELASTICSEARCH_URL` 配置正确
- [ ] LLM / Embedding / Rerank Provider 的 API Key 已配置
- [ ] Elasticsearch 客户端版本与 Docker 服务端版本一致（如 `elasticsearch==8.17.0`）
- [ ] 已安装 `aiohttp>=3,<4`（异步 ES 客户端依赖）

---

## 二、依赖服务启动

- [ ] 执行 `docker compose up -d` 成功
- [ ] `docker ps` 确认以下容器运行正常：
  - [ ] PostgreSQL
  - [ ] Milvus
  - [ ] Elasticsearch
- [ ] Elasticsearch IK 分词插件已安装（中文检索必需）

---

## 三、数据库（PostgreSQL）

- [ ] 执行 `alembic upgrade head` 成功
- [ ] 确认以下表已创建：
  - [ ] `users`
  - [ ] `api_keys`
  - [ ] `refresh_tokens`
  - [ ] `documents`
  - [ ] `document_chunks`
  - [ ] `knowledge_bases`
- [ ] 确认权限相关字段存在：
  - [ ] `visibility`
  - [ ] `owner_user_id`
  - [ ] `allowed_departments_json`
  - [ ] `allowed_users_json`
  - [ ] `department_codes_json`

---

## 四、FastAPI 服务

- [ ] 执行 `uvicorn fast_app.main:app --reload` 启动成功
- [ ] 访问 `http://127.0.0.1:8000/docs`，OpenAPI 文档正常打开
- [ ] 健康检查接口返回正常：
  ```bash
  curl http://127.0.0.1:8000/health
  ```
  预期返回：`{"status": "ok"}`

---

## 五、认证功能

- [ ] 用户登录成功，返回 `access_token` 和 `refresh_token`
  ```bash
  curl -X POST "http://127.0.0.1:8000/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username_or_email":"dev_user","password":"dev_password"}'
  ```
- [ ] 携带 `Authorization: Bearer <access_token>` 可调用受保护接口
- [ ] 携带 `X-API-Key: <api_key>` 可调用受保护接口
- [ ] 无认证信息时受保护接口返回 401/403

---

## 六、Milvus 索引检查

- [ ] Collection 已创建（如 `rag_chunks_acl_test`）
- [ ] 确认以下字段存在于 schema：
  - [ ] `doc_id`
  - [ ] `chunk_id`
  - [ ] `vector`（维度正确）
  - [ ] `visibility`
  - [ ] `allowed_departments`
  - [ ] `allowed_users`
  - [ ] `source_path`
- [ ] 权限字段类型可用于 filter expression
- [ ] 文档导入后，chunk metadata 包含完整权限信息
- [ ] Milvus 查询时传入了权限 filter

---

## 七、Elasticsearch 索引检查

- [ ] Index 已创建（如 `rag_chunks_acl_test`）
- [ ] 确认 mapping 包含以下字段：
  - [ ] `content`
  - [ ] `doc_id`
  - [ ] `chunk_id`
  - [ ] `visibility`
  - [ ] `allowed_departments`
  - [ ] `allowed_users`
  - [ ] `source_path`
  - [ ] `department_code`
  - [ ] `created_at`
- [ ] `content` 字段使用 IK 分词器：
  ```json
  {
    "content": {
      "type": "text",
      "analyzer": "ik_max_word",
      "search_analyzer": "ik_smart"
    }
  }
  ```
- [ ] `allowed_departments` 使用 keyword 类型（用于精确过滤）

---

## 八、权限过滤验证

### 8.1 权限规则

- [ ] `visibility = public` 的文档对所有认证用户可见
- [ ] `allowed_departments` 包含当前用户部门时可见
- [ ] `allowed_users` 包含当前用户 ID 时可见
- [ ] `owner_user_id` 匹配当前用户时可见
- [ ] 无 `knowledge:read` 权限时请求被拒绝

### 8.2 Hybrid Retrieval 权限一致性

- [ ] Milvus 和 Elasticsearch 使用相同的权限规则
- [ ] 权限过滤流程正确：
  ```
  构建 PermissionScope → 生成 Milvus filter → 生成 ES bool filter
  → 分别检索 → 合并结果 → rerank → prompt 前兜底校验
  ```
- [ ] 不存在以下问题：
  - [ ] Milvus 有过滤但 ES 没有
  - [ ] ES 有过滤但 Milvus 没有
  - [ ] 两个检索源使用不同规则
  - [ ] 权限过滤仅在 Python 后处理阶段执行

### 8.3 Prompt 前兜底校验

- [ ] 进入 LLM prompt 前执行 `final_permission_check`
- [ ] 只允许 `allowed_chunks` 进入上下文

### 8.4 部门隔离测试（以 development 用户为例）

- [ ] development 用户 **能** 检索到 `development/` 目录文档
- [ ] development 用户 **能** 检索到 `public/` 目录文档
- [ ] development 用户 **不能** 检索到 `art/` 目录文档
- [ ] development 用户 **不能** 检索到 `product_planning/` 目录文档

---

## 九、健康检查汇总

| 检查项 | 验证方式 | 预期结果 |
|--------|----------|----------|
| FastAPI 服务 | `curl http://127.0.0.1:8000/health` | `{"status": "ok"}` |
| OpenAPI 文档 | 浏览器访问 `/docs` | 页面正常加载 |
| PostgreSQL | `alembic current` | 显示最新 migration |
| Milvus | 查询 collection 列表 | `rag_chunks_acl_test` 存在 |
| Elasticsearch | `curl http://localhost:9200/rag_chunks_acl_test/_mapping` | 返回正确 mapping |
| 认证 | 登录接口 | 返回 access_token |
| 权限过滤 | 跨部门检索测试 | 仅返回有权限文档 |

---

## 十、常见问题排查

| 问题 | 排查方向 |
|------|----------|
| ES 客户端兼容性错误 | 确认 Docker ES 版本与 Python 客户端版本一致 |
| AsyncElasticsearch 报错 | 确认已安装 `aiohttp>=3,<4` |
| 文档导入成功但检索不到 | 检查 chunk 切分、embedding、Milvus/ES 写入、权限 filter |
| 非授权用户检索到文档 | **高优先级**：检查 metadata、Milvus filter、ES filter、prompt 兜底校验 |

---

## 十一、验收通过标准

所有以下项必须通过：

- [ ] FastAPI 服务正常启动，`/docs` 可访问
- [ ] 用户可登录获取 access token
- [ ] API Key 可调用受保护接口
- [ ] PostgreSQL migration 成功
- [ ] Milvus collection 创建成功，权限字段完整
- [ ] Elasticsearch index 创建成功，mapping 正确
- [ ] 测试知识库文档成功导入
- [ ] 部门用户只能检索到有权限的文档
- [ ] Milvus 与 Elasticsearch 权限过滤结果一致
- [ ] 无权限 chunk 不会进入 LLM prompt
