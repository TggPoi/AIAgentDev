# RAG 后端部署规范文档

## 文档目的

本文档用于定义当前 Agent RAG 测试项目中的后端部署规范，主要面向 **开发部门 development** 使用。

该文档适用于以下工作：

* RAG 后端服务部署
* FastAPI 服务启动与检查
* Milvus / Elasticsearch / PostgreSQL 依赖服务联调
* 环境变量配置
* 索引初始化
* 日志检查
* 部署后健康检查
* 权限过滤功能验证

本文档属于开发部门内部知识库内容。非 development 部门用户在权限过滤正确的情况下，不应该检索到本文档内容。

---

## 1. 部署目标

RAG 后端部署的目标是保证以下能力稳定可用：

```text id="rugk9h"
用户认证
知识库文档导入
向量检索
关键词检索
Hybrid Retrieval
Rerank
权限过滤
SSE 流式问答
日志追踪
异常处理
```

部署完成后，系统应能够支持：

1. 用户登录并获取 access token。
2. 用户通过 API Key 调用 RAG 接口。
3. 不同部门用户只能检索到自己有权限的文档。
4. public 文档可以被所有认证用户检索。
5. Milvus 和 Elasticsearch 的权限过滤结果保持一致。
6. 无权限文档不会进入 LLM prompt。

---

## 2. 服务组成

当前 RAG 后端部署至少包含以下服务：

| 服务                 | 作用                 |
| ------------------ | ------------------ |
| FastAPI Backend    | 提供认证、文档导入、RAG 查询接口 |
| PostgreSQL         | 存储用户、权限、文档元数据      |
| Milvus             | 存储向量索引，用于语义检索      |
| Elasticsearch      | 存储文本索引，用于关键词检索     |
| Redis              | 可选，用于缓存、限流、任务状态    |
| LLM Provider       | 提供大模型生成能力          |
| Embedding Provider | 提供文档向量化能力          |
| Rerank Provider    | 提供召回结果重排能力         |

如果当前测试阶段没有接入 Redis，可以先忽略 Redis，但部署文档中仍保留该项，方便后续扩展。

---

## 3. 推荐目录结构

推荐部署目录结构如下：

```text id="8x2tok"
project-root/
  fast_app/
    main.py
    routers/
    services/
    repositories/
    models/
    schemas/
    core/
  migrations/
  scripts/
  tests/
  knowledge-base-acl-test/
    art/
    product_planning/
    development/
    public/
  .env
  docker-compose.yml
  README.md
```

其中：

```text id="6v1bf7"
fast_app/                 后端应用代码
migrations/               Alembic 数据库迁移脚本
scripts/                  初始化、导入、测试脚本
knowledge-base-acl-test/  ACL 权限测试知识库
.env                      本地环境变量
docker-compose.yml        本地依赖服务编排
```

---

## 4. 环境变量配置

部署前需要检查 `.env` 文件。

推荐至少包含以下配置：

```env id="631npg"
APP_ENV=local
APP_NAME=agent-rag-backend
LOG_LEVEL=INFO

AUTH_ENABLED=true
JWT_SECRET_KEY=replace-with-local-secret
JWT_ALGORITHM=HS256
JWT_ISSUER=agent-rag
JWT_AUDIENCE=agent-rag-api
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=14
API_KEY_PEPPER=replace-with-api-key-pepper

DATABASE_URL=postgresql+asyncpg://rag_user:rag_password@localhost:5432/rag_db

MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=rag_chunks_acl_test

ELASTICSEARCH_URL=http://localhost:9200
ELASTICSEARCH_INDEX=rag_chunks_acl_test

OPENAI_API_KEY=replace-with-provider-key
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
EMBEDDING_MODEL_NAME=text-embedding-v3
RERANK_MODEL_NAME=gte-rerank
```

注意事项：

```text id="zj1uxw"
JWT_SECRET_KEY 不允许为空。
API_KEY_PEPPER 不允许为空。
AUTH_ENABLED=true 时，受保护接口必须携带有效认证信息。
Elasticsearch 客户端版本需要和 Docker 服务版本保持一致。
```

---

## 5. 本地依赖服务启动

本地开发建议通过 Docker Compose 启动依赖服务。

启动命令：

```bash id="hbnu5i"
docker compose up -d
```

检查容器状态：

```bash id="0mxgo8"
docker ps
```

需要确认：

```text id="zo0auh"
PostgreSQL 正常运行
Milvus 正常运行
Elasticsearch 正常运行
Elasticsearch IK 分词插件已安装
```

如果 Elasticsearch 使用中文检索，必须确认 IK 分词器可用，否则中文关键词检索效果会明显下降。

---

## 6. Python 依赖安装

建议在虚拟环境中安装依赖。

```bash id="kqazg5"
python -m venv .venv
```

Windows PowerShell 激活：

```powershell id="cp59u5"
.venv\Scripts\Activate.ps1
```

安装依赖时应固定关键版本，避免客户端与服务端不兼容。

示例：

```bash id="1804x5"
pip install fastapi==0.115.6
pip install uvicorn[standard]==0.34.0
pip install pydantic-settings==2.7.1
pip install sqlalchemy==2.0.36
pip install asyncpg==0.30.0
pip install alembic==1.14.0
pip install elasticsearch==8.17.0
pip install aiohttp>=3,<4
pip install pymilvus==2.5.0
pip install argon2-cffi==25.1.0
pip install pyjwt==2.10.1
```

如果本地 Docker Elasticsearch 镜像版本是 `elasticsearch:8.17.0`，Python 客户端应优先使用：

```bash id="jtvljm"
pip install elasticsearch==8.17.0
```

异步 Elasticsearch 客户端需要：

```bash id="mfbtsh"
pip install aiohttp>=3,<4
```

---

## 7. 数据库迁移

启动依赖服务后，需要执行 Alembic migration。

```bash id="byuvfz"
alembic upgrade head
```

迁移完成后，需要确认以下表存在：

```text id="4tdx0e"
users
api_keys
refresh_tokens
documents
document_chunks
knowledge_bases
```

如果权限模块已经完成，还需要确认权限相关字段存在，例如：

```text id="f78wa8"
visibility
owner_user_id
allowed_departments_json
allowed_users_json
department_codes_json
```

具体字段名称以当前工程实现为准。

---

## 8. FastAPI 服务启动

本地启动命令：

```bash id="y5pu75"
uvicorn fast_app.main:app --reload
```

启动成功后，访问：

```text id="eepzsn"
http://127.0.0.1:8000/docs
```

需要确认 OpenAPI 文档可以正常打开。

如果项目提供健康检查接口，可以执行：

```bash id="bb3sbs"
curl http://127.0.0.1:8000/health
```

预期结果：

```json id="g4uy5a"
{
  "status": "ok"
}
```

---

## 9. 认证功能检查

如果 `AUTH_ENABLED=true`，需要先登录获取 token。

登录请求示例：

```bash id="sp7z9w"
curl -X POST "http://127.0.0.1:8000/auth/login" ^
  -H "Content-Type: application/json" ^
  -d "{\"username_or_email\":\"dev_user\",\"password\":\"dev_password\"}"
```

预期返回：

```json id="0bbmdp"
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

后续请求需要携带：

```http id="5wwcet"
Authorization: Bearer <access_token>
```

如果使用 API Key，则请求头应为：

```http id="vn8h49"
X-API-Key: <api_key>
```

---

## 10. ACL 测试知识库导入

测试知识库目录为：

```text id="q2axh9"
knowledge-base-acl-test/
  art/character-art-style.md
  product_planning/combat-design.md
  development/rag-backend-deployment.md
  public/project-overview.md
```

目录到权限 metadata 的映射规则：

```text id="6vvrwn"
art/** -> allowed_departments = ["art"]
product_planning/** -> allowed_departments = ["product_planning"]
development/** -> allowed_departments = ["development"]
public/** -> visibility = "public"
```

导入时需要确保每个文档 chunk 都携带权限 metadata。

例如 development 文档对应 metadata：

```json id="n40s3c"
{
  "visibility": "department",
  "allowed_departments": ["development"],
  "allowed_users": [],
  "source_path": "knowledge-base-acl-test/development/rag-backend-deployment.md"
}
```

如果 chunk 缺少权限 metadata，Milvus 或 Elasticsearch 查询阶段无法正确过滤。

---

## 11. Milvus 索引检查

文档导入后，需要确认 Milvus collection 已创建。

需要检查：

```text id="4hoja6"
collection name
vector dimension
primary key
doc_id
chunk_id
visibility
allowed_departments
allowed_users
source_path
```

如果 Milvus schema 没有权限字段，则无法在向量检索阶段做权限下推过滤。

开发部门必须确认：

```text id="645txp"
权限字段写入 Milvus metadata
权限字段类型可用于 filter expression
Milvus 查询时传入了权限 filter
```

错误风险：

```text id="291m0v"
文档表权限正确
但 Milvus chunk metadata 缺失权限
导致向量召回绕过 ACL
```

---

## 12. Elasticsearch 索引检查

Elasticsearch index 需要包含文本字段和权限 metadata 字段。

推荐检查 mapping：

```bash id="uw3p4o"
curl http://localhost:9200/rag_chunks_acl_test/_mapping
```

需要确认字段：

```text id="z4o3yd"
content
doc_id
chunk_id
visibility
allowed_departments
allowed_users
source_path
department_code
created_at
```

中文检索字段建议使用 IK 分词：

```json id="m5ki8r"
{
  "content": {
    "type": "text",
    "analyzer": "ik_max_word",
    "search_analyzer": "ik_smart"
  }
}
```

如果使用 `allowed_departments` 做精确过滤，应使用 keyword 类型或 keyword 数组。

---

## 13. 权限过滤规则

development 用户应能检索到：

```text id="x7r9n5"
development/rag-backend-deployment.md
public/project-overview.md
```

development 用户不应检索到：

```text id="gxod7x"
art/character-art-style.md
product_planning/combat-design.md
```

基本权限规则如下：

```text id="nfa3sf"
如果 visibility = public，则所有认证用户可见。
如果 allowed_departments 包含当前用户 department_code，则可见。
如果 allowed_users 包含当前用户 user_id，则可见。
如果 owner_user_id 等于当前用户 user_id，则可见。
否则不可见。
```

如果当前用户没有 `knowledge:read` 权限，则应在检索前直接拒绝请求。

---

## 14. Hybrid Retrieval 权限一致性

当前系统使用 Hybrid Retrieval 时，需要保证 Milvus 和 Elasticsearch 使用相同的权限规则。

正确流程：

```text id="kq0gpd"
构建 PermissionScope
    ↓
生成 Milvus filter expression
    ↓
生成 Elasticsearch bool filter
    ↓
分别执行向量检索和关键词检索
    ↓
合并结果
    ↓
进入 rerank
    ↓
进入 prompt 前再次做权限兜底校验
```

需要避免：

```text id="h9xu6z"
Milvus 有权限过滤，Elasticsearch 没有权限过滤
Elasticsearch 有权限过滤，Milvus 没有权限过滤
两个检索源使用不同规则
权限过滤只在 Python 后处理阶段执行
```

权限过滤必须尽量下推到检索层。

---

## 15. Prompt 前兜底校验

即使 Milvus 和 Elasticsearch 都已经做了权限过滤，进入 LLM prompt 前仍然需要做一次兜底校验。

原因：

```text id="jtqczf"
索引 metadata 可能滞后
权限字段可能同步失败
混合检索合并时可能引入异常结果
开发调试时可能绕过 filter
```

推荐流程：

```text id="xu9m47"
retrieved_chunks
    ↓
final_permission_check
    ↓
allowed_chunks
    ↓
build_rag_context
    ↓
LLM
```

只允许 `allowed_chunks` 进入上下文。

---

## 16. 部署后测试问题

可以使用以下问题测试 development 部门权限：

```text id="o2s4d5"
RAG 后端如何部署？
FastAPI 服务启动命令是什么？
Milvus 权限字段需要检查哪些？
Elasticsearch 为什么要检查 allowed_departments？
Hybrid Retrieval 权限一致性如何保证？
进入 LLM prompt 前为什么还要做兜底校验？
```

development 用户应该能检索到本文档内容。

art 用户、product_planning 用户在没有跨部门授权的情况下，不应该检索到本文档内容。

---

## 17. 内部测试关键词

以下关键词用于 ACL 权限检索测试，属于 development 部门内部内容：

```text id="eqlh7j"
Milvus 权限字段下推
Elasticsearch ACL bool filter
Hybrid Retrieval 权限一致性
Prompt 前兜底校验
RAG 后端部署健康检查
API_KEY_PEPPER 环境变量检查
AsyncElasticsearch aiohttp 依赖
ACL chunk metadata 同步
development 部门检索隔离
rag_chunks_acl_test 索引检查
```

如果当前用户不属于 development 部门，且文档没有被设置为 public 或跨部门共享，那么这些关键词不应该被检索出来。

---

## 18. 常见部署问题

### 18.1 Elasticsearch 客户端版本不兼容

现象：

```text id="dd9qet"
客户端请求 Elasticsearch 时报 Accept header 或兼容性错误
```

处理方式：

```text id="pprfx1"
确认 Docker Elasticsearch 版本
安装匹配版本的 Python elasticsearch 客户端
```

如果服务端是 8.17.0，建议：

```bash id="e50wrt"
pip install elasticsearch==8.17.0
```

---

### 18.2 AsyncElasticsearch 缺少 aiohttp

现象：

```text id="78eyno"
运行异步 ES 客户端时报 aiohttp 相关错误
```

处理方式：

```bash id="2jo3vb"
pip install aiohttp>=3,<4
```

---

### 18.3 文档导入成功但检索不到

需要检查：

```text id="p4jf5g"
文档是否成功切分 chunk
embedding 是否成功生成
Milvus 是否写入向量
Elasticsearch 是否写入文本索引
当前用户是否有部门权限
权限 filter 是否过严
```

---

### 18.4 非授权用户检索到了文档

这是高优先级问题。

需要立即检查：

```text id="1vysr1"
文档 metadata 是否正确
chunk metadata 是否正确
Milvus filter 是否生效
Elasticsearch filter 是否生效
rerank 前结果是否已过滤
prompt 前兜底校验是否存在
```

如果发现无权限 chunk 进入 prompt，应停止使用该索引并重新导入。

---

## 19. 验收标准

部署完成后，需要满足以下验收标准：

* FastAPI 服务可以正常启动。
* `/docs` 页面可以打开。
* 用户可以登录并获取 access token。
* API Key 可以调用受保护接口。
* PostgreSQL migration 成功执行。
* Milvus collection 创建成功。
* Elasticsearch index 创建成功。
* knowledge-base-acl-test 文档成功导入。
* development 用户可以检索 development 文档。
* development 用户可以检索 public 文档。
* development 用户不能检索 art 文档。
* development 用户不能检索 product_planning 文档。
* Milvus 与 Elasticsearch 权限过滤结果一致。
* 无权限 chunk 不会进入 LLM prompt。

---

## 20. 总结

本文档定义了 RAG 后端部署与 ACL 权限测试相关的开发规范。

核心原则是：

> 权限过滤不能只停留在接口层，必须贯穿文档导入、chunk metadata、Milvus 检索、Elasticsearch 检索、rerank 和 prompt 构建全过程。

在知识库 ACL 权限测试中，本文档应自动获得以下权限 metadata：

```text id="nxdorc"
allowed_departments = ["development"]
visibility = department 或默认部门可见
```

因此，该文档应该只对 development 部门用户可见，不应该被 art 或 product_planning 部门用户检索到。
