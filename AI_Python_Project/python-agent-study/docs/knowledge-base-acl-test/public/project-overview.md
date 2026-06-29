# 项目整体介绍文档

## 文档目的

本文档用于介绍当前 Agent RAG 测试项目的整体目标、模块组成、测试范围和权限验证方式。

该文档位于：

```text id="e1naxg"
knowledge-base-acl-test/public/project-overview.md
```

根据 ACL 测试目录规则，`public/**` 目录下的文档应自动生成以下权限 metadata：

```text id="n240qb"
visibility = "public"
```

因此，本文档应该对所有已认证用户可见，包括：

```text id="6v82xc"
art 部门用户
product_planning 部门用户
development 部门用户
其他拥有 knowledge:read 权限的用户
```

本文档主要用于验证：

> public 文档是否可以被不同部门用户共同检索到。

---

## 1. 项目背景

当前项目是一个用于学习和验证企业级 RAG 权限控制的测试项目。

系统目标是构建一个支持多用户、多部门、多权限隔离的 Agent RAG 后端，使不同部门用户在使用同一个知识库检索接口时，只能检索到自己有权限访问的文档。

项目重点不是单纯完成问答，而是验证以下能力：

```text id="bt3wga"
用户认证
部门权限识别
文档权限 metadata 生成
Milvus 权限过滤
Elasticsearch 权限过滤
Hybrid Retrieval 权限一致性
Rerank 前后权限保持
Prompt 构建前最终兜底校验
```

---

## 2. 项目核心目标

本项目的核心目标是：

```text id="k8ne4x"
让 RAG 系统在多部门知识库场景下，能够正确控制文档召回范围。
```

具体目标包括：

1. 用户登录后能获得当前用户身份。
2. 系统能识别用户所属部门。
3. 文档导入时能根据目录自动生成权限 metadata。
4. 检索时能根据当前用户权限生成 permission scope。
5. Milvus 向量检索只召回有权限的 chunk。
6. Elasticsearch 关键词检索只召回有权限的 chunk。
7. 混合检索结果合并后不会引入无权限文档。
8. 最终进入 LLM prompt 的内容必须全部通过权限校验。

---

## 3. 测试知识库目录

当前测试知识库目录如下：

```text id="aal0yq"
knowledge-base-acl-test/
  art/
    character-art-style.md
  product_planning/
    combat-design.md
  development/
    rag-backend-deployment.md
  public/
    project-overview.md
```

每个目录代表一种权限来源。

目录权限映射规则如下：

| 目录                  | 自动生成权限 metadata                            | 说明                      |
| ------------------- | ------------------------------------------ | ----------------------- |
| art/**              | allowed_departments = ["art"]              | 仅 art 部门可见              |
| product_planning/** | allowed_departments = ["product_planning"] | 仅 product_planning 部门可见 |
| development/**      | allowed_departments = ["development"]      | 仅 development 部门可见      |
| public/**           | visibility = "public"                      | 所有认证用户可见                |

本文档位于 `public/` 目录，因此应作为公开文档参与检索。

---

## 4. 权限模型说明

当前项目采用混合权限模型：

```text id="gz81bz"
RBAC + ACL + ABAC
```

三者职责如下：

```text id="5u0oye"
RBAC：
判断用户是否有使用知识库功能的权限，例如 knowledge:read。

ACL：
记录文档允许哪些用户或部门访问，例如 allowed_departments、allowed_users。

ABAC：
根据当前用户属性和文档属性，动态判断某个文档 chunk 是否可以被召回。
```

在本项目中，权限判断不应只发生在接口入口处。

正确的权限控制应该贯穿：

```text id="z4kesz"
接口入口
文档导入
chunk metadata 写入
Milvus 检索
Elasticsearch 检索
Rerank
Prompt 构建
LLM 回答
```

---

## 5. 部门私有文档与公开文档的区别

部门私有文档通常具有：

```text id="tvb0q4"
visibility = "department"
allowed_departments = ["某个部门"]
```

例如：

```text id="bpehp8"
art/character-art-style.md
```

应该只能被 art 部门用户检索。

公开文档通常具有：

```text id="n8efee"
visibility = "public"
```

例如：

```text id="e8ygk9"
public/project-overview.md
```

应该能被所有已认证用户检索。

因此，本文档适合用于测试：

```text id="s55wh6"
不同部门用户是否都能检索到 public 文档。
```

---

## 6. 预期检索行为

### 6.1 art 部门用户

art 用户应该能检索到：

```text id="kzwsf0"
art/character-art-style.md
public/project-overview.md
```

art 用户不应该检索到：

```text id="tbnuux"
product_planning/combat-design.md
development/rag-backend-deployment.md
```

---

### 6.2 product_planning 部门用户

product_planning 用户应该能检索到：

```text id="l4z6k8"
product_planning/combat-design.md
public/project-overview.md
```

product_planning 用户不应该检索到：

```text id="d5n55f"
art/character-art-style.md
development/rag-backend-deployment.md
```

---

### 6.3 development 部门用户

development 用户应该能检索到：

```text id="nv55e8"
development/rag-backend-deployment.md
public/project-overview.md
```

development 用户不应该检索到：

```text id="myl39s"
art/character-art-style.md
product_planning/combat-design.md
```

---

## 7. 推荐测试问题

以下问题可以用于验证 public 文档是否能被不同部门用户共同检索：

```text id="g3vjnl"
这个项目的整体目标是什么？
当前测试知识库有哪些目录？
public 目录下的文档应该具有什么权限？
RBAC、ACL、ABAC 在这个项目中分别负责什么？
不同部门用户应该都能检索到哪一份文档？
```

无论当前用户属于哪个部门，只要用户拥有 `knowledge:read` 权限，都应该可以通过这些问题检索到本文档。

---

## 8. 公开文档测试关键词

以下关键词用于 public 权限检索测试：

```text id="mndxck"
公开项目总览
public 文档可见性测试
多部门共同可见文档
知识库 ACL 测试目录
RAG 权限过滤总览
RBAC ACL ABAC 混合模型说明
Hybrid Retrieval 权限验证
Prompt 前最终兜底校验
```

这些关键词应该可以被 art、product_planning、development 三个部门用户检索到。

如果某个已认证用户无法检索到这些关键词，说明 public 文档权限处理可能存在问题。

---

## 9. 权限过滤验收标准

本文档的权限验收标准如下：

* art 用户可以检索到本文档。
* product_planning 用户可以检索到本文档。
* development 用户可以检索到本文档。
* 已认证且拥有 `knowledge:read` 权限的普通用户可以检索到本文档。
* 本文档不应依赖 `allowed_departments` 才能被检索。
* 本文档的 chunk metadata 中应包含 `visibility = "public"`。
* Milvus 和 Elasticsearch 都应支持 public 文档过滤规则。
* public 文档可以和部门文档一起参与 Hybrid Retrieval。
* public 文档进入 prompt 前仍应通过最终权限校验。

---

## 10. 常见错误

### 10.1 public 文档被当成部门文档

错误表现：

```text id="d1bmfg"
public/project-overview.md 被错误写入 allowed_departments = ["public"]
```

这种情况下，系统可能会尝试匹配用户部门是否为 `public`，导致正常部门用户无法检索到公开文档。

正确做法：

```text id="ubtrz8"
public/** -> visibility = "public"
```

而不是：

```text id="3frr8n"
public/** -> allowed_departments = ["public"]
```

---

### 10.2 只在 Elasticsearch 中支持 public 过滤

错误表现：

```text id="rx0u62"
Elasticsearch 可以检索 public 文档
Milvus 无法检索 public 文档
```

这会导致 Hybrid Retrieval 结果不一致。

正确做法：

```text id="vkih0f"
Milvus 和 Elasticsearch 都必须使用同一套权限规则。
```

---

### 10.3 Prompt 前没有最终校验

即使 public 文档一般风险较低，也不应该跳过最终权限校验。

正确流程：

```text id="j19fid"
retrieved_chunks
    ↓
final_permission_check
    ↓
allowed_chunks
    ↓
build_rag_context
```

---

## 11. 总结

本文档是 ACL 权限测试知识库中的公开文档，用于验证 `public/**` 目录下的文档是否可以被所有已认证用户检索。

核心测试点是：

```text id="utw2ty"
部门私有文档只能被对应部门检索。
public 文档应该被所有拥有 knowledge:read 权限的认证用户检索。
```

本文档应自动获得以下权限 metadata：

```text id="l37oec"
visibility = "public"
```

如果 art、product_planning、development 三个部门用户都能检索到本文档，同时不能越权检索其他部门私有文档，则说明基础 ACL 权限过滤逻辑符合预期。
