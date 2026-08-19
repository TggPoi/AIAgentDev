# 空章节修复与章节面包屑下沉方案

## Summary

三项修改一次落地，全部集中在 `src/fast_app/ingestion/processing/markdown_hierarchy.py` 及其测试：

1. **空标题章节合并**：仅含标题的章节不再产出空壳父块/子块，其标题块并入下一个有正文的章节
2. **面包屑下沉**：父块与子块的 content 前置完整路径面包屑（`部署指南 > 回滚操作\n\n`），子块 search_text 改为等于 content——LLM 可见文本（唯一进上下文的字段）从此自描述，ES 匹配文本与 embedding 文本保持逐字等价（召回零回退）
3. **策略版本升 v2**：`markdown_parent_child_v2`，ID 哈希含版本号 → 全量 ID 换新，GitLab 增量同步的版本闸门（sync_service.py 第 479 行）自动判旧记录陈旧并重写，空壳残留自清理

已确认决策：① 面包屑用完整路径；② 升 v2；③ 父块 content 同样前置面包屑。

## markdown_hierarchy.py 核心改动

### 常量与日志

- 第 15 行 `MARKDOWN_CHUNK_STRATEGY_VERSION`：`v1` → `v2`
- 新增 `logger = get_logger(__name__)`（来自 `fast_app.core.logging`，与工程其他模块一致）

### `_parse_sections`：空标题合并（第 239~303 行）

- 新增 `pending_heading_blocks: list[MarkdownBlock]` 待合并队列
- `flush()` 改造（第 249~264 行）：
  - `current_blocks` 为空 → 原样返回
  - **全部是 heading block** → 移入 pending，不产出章节，返回
  - 否则 → `blocks = pending + current_blocks`，清空 pending，正常产出章节
- 文末兜底（第 302 行 flush 之后）：
  - pending 非空且已有章节 → **丢弃** + `logger.warning`（文末空标题不引出任何内容）
  - pending 非空且无任何章节（全文只有空标题）→ **兜底产出**该章节 + `logger.warning`（避免文档变成 0 chunk 完全不可检索）

### 面包屑与预算预留（详细设计）

#### 1. 为什么需要"预算预留"

现状装箱只装正文 blocks。修改后每个 chunk 的 content 头部要加一段面包屑前缀，**前缀本身占 token**。而工程里有硬约束链条：

- `_metadata` 第 563 行：`token_count = token_counter.count(content)`——按**最终 content**（含前缀）计数
- 测试第 117~124 行断言：所有父块 `token_count ≤ parent_max_tokens`、所有子块 `token_count ≤ child_max_tokens`

如果装箱时仍按原预算把正文装满，再拼上前缀，最终 content 必然超限。因此顺序必须是：**先算前缀占多少 → 装箱只用"剩余预算" → 最后拼前缀**，这样 `前缀 + 正文 ≤ 原 max` 在数学上恒成立。

#### 2. 面包屑与前缀格式

- 新增静态方法 `_breadcrumb(section_path)` → `" > ".join(section_path)`，如 `部署指南 > 回滚操作`
- 前缀 = 面包屑 + `"\n\n"`——**刻意与旧 `_search_text` 的拼接格式完全一致**，这是"ES 匹配文本、embedding 文本逐字等价、召回零回退"的等价性基础

#### 3. 父块装箱：数字推演（第 169~176 行）

设默认预算 parent target=900 / max=1200 / max_chars=6000，章节路径 `[部署指南, 回滚操作]`：

| 步骤 | 动作 | 示例值 |
|---|---|---|
| ① 算前缀 | `prefix = "部署指南 > 回滚操作\n\n"`，`P = token_counter.count(prefix)`，`C = len(prefix)` | 假设 P=12，C=16 |
| ② 有效预算 | `eff_target = max(1, 900-P)`；`eff_max = max(1, 1200-P)`；`eff_chars = 6000-C` | 888 / 1188 / 5984 |
| ③ 装箱 | `_pack_blocks(section.blocks, eff_target, eff_max, eff_chars)`——正文块在剩余预算内贪心装箱 | 每箱正文 ≤1188，通常 ~888 |
| ④ 拼接 | `parent_content = prefix + _join_blocks(group)` | 总 token = P + 正文 ≤ P + (1200-P) = **1200，恰好不超 max** ✓ |

metadata 的 token_count/char_count/content_hash 按拼接后的最终 content 计算（第 563~567 行逻辑不动，天然正确）。

#### 4. 子块装箱：数字推演（`_build_child_groups`，第 348~386 行）

设默认预算 child target=260 / max=350 / min=80 / overlap=50，同一前缀 P=12：

- 函数签名增加 `prefix: str` 参数；函数开头先算 `reserved = token_counter.count(prefix)`，得到有效预算 `eff_target = max(1, 260-P) = 248`、`eff_max = max(1, 350-P) = 338`
- 函数内**全部三处**预算判断统一替换为有效预算，一处都不能漏：

| 位置 | 原判断 | 改后判断 |
|---|---|---|
| 主装箱（第 353~358 行） | `_pack_blocks(..., child_target_tokens, child_max_tokens, ...)` | 传 `eff_target, eff_max` |
| 小尾合并（第 362~366 行） | 合并后 ≤ `child_max_tokens` | 合并后 ≤ `eff_max`（注意：`child_min_tokens=80` 的阈值**不扣减**——它衡量"尾块正文是否太小"，与前缀无关） |
| overlap 校验（第 382 行） | 加完重叠 ≤ `child_max_tokens` | 加完重叠 ≤ `eff_max`（`overlap=50` 也不扣减，它是正文间的重叠量） |

- 装配（第 204~236 行）：`child_content = prefix + 装箱正文` → 总 token ≤ 350 ✓；`search_text = child_content`（不再调用 `_search_text`）

#### 5. 为什么选"预留"而不是"装完再裁"

备选方案是照常装箱、拼上前缀后若超限就从尾部裁掉超出部分。否决原因：裁剪会把某个 block 拦腰切断，违背"block 不拦腰"的结构承诺，且引入新的切割分支。预留法不动装箱对象的完整性，改动只发生在预算参数的传入值上。

#### 6. 最终产物示例（用例 A 修复后的第一个子块）

```text
部署指南 > 回滚操作

## 回滚操作

出现问题时执行回滚。

1. 停止服务
```

其 content 与 search_text 逐字相同；ES 里该记录的 `content`、`search_text` 两字段也逐字相同（与现状父块记录的形态一致）。LLM 拿到它时，第一行就知道这是"部署指南"下"回滚操作"一节的正文。

#### 7. 清理

删除 `_search_text` 静态方法（第 571~573 行）：唯一调用方改为直接使用 content 后已无人引用。

## 行为关联点（无需改代码，已核实）

| 位置 | 结论 |
|---|---|
| `rag_store_writer.py` 第 258 行 | ES 子块 search_text 写 `chunk.search_text or content` → 落库为含面包屑的 content，与 content 逐字相同 |
| `rag_store_writer.py` 第 194~199 行 | 父块 content_hash 校验按 content 双向计算，前缀不影响一致性 |
| `markdown_ingestion_service.py` | embedding 输入 `search_text or content` → 文本与现状逐字等价 |
| `markdown_parent_context.py` 第 230~236 行 | 版本检查是父子 metadata 互比，无硬编码 v1；过渡期旧 v1 父块自动走降级路径 |
| `gitlab/sync_service.py` 第 479 行 | 版本闸门使旧 v1 记录下次同步判陈旧 → 重写/删除，空壳 chunk 残留自清理，无需手工迁移 |

## 测试更新（scripts/tests/ingestion/test_markdown_parent_child.py）

- **新增 `test_empty_heading_sections`**（复用复现脚本三用例）：
  - 用例 A（一级空标题 + 两个二级节）：断言无"仅标题"父块/子块；回滚节父块 content 含 `# 部署指南`；共 2 父块 2 子块
  - 用例 B（三连空标题）：全部并入三级正文节，1 父块，content 含三个标题行
  - 用例 C（全文仅一个空标题）：兜底产出 1 父块 + 1 子块
- **新增面包屑断言**：每个父块/子块 content 以 `" > ".join(section_path) + "\n\n"` 开头；`token_count ≤ 对应 max` 预算
- 既有 fixture 含四个连续空标题（第 78~84 行）→ 将被合并；既有断言（`###### Level 6` in combined 等）预期自然成立，重跑验证
- GitLab 同步测试 fixture（`# 标题 + 正文`）不受合并影响，重跑确认

## 验证步骤

1. `GetProblems` 检查修改文件无语法/lint 错误
2. 重跑 `.tmp/repro_empty_heading_sections.py`：预期三个用例均无"仅含标题=True"章节
3. `.venv\Scripts\python.exe scripts\tests\ingestion\test_markdown_parent_child.py`（PYTHONPATH=src）
4. `.venv\Scripts\python.exe scripts\tests\integrations\test_gitlab_enterprise_sync.py`
5. 复现脚本保留在 `.tmp`（临时目录，不属仓库主体）

## Assumptions 与风险

- **病态边界**：极深章节树 + 超长标题时面包屑可能吃掉大部分预算，有效预算保底 1 token，极端情况最终 token_count 可能超预算——接受此病理边界，不额外防御
- **子块 ⊂ 父块不变量**放宽为"子块正文 ⊂ 父块正文"：同一章节的父块与子块共享相同面包屑首行，父块扩展的覆盖语义不受影响
- **v2 升版即全量 ID 换新**：首次 GitLab/手动摄取为全量重写，这是有意行为（版本字段语义诚实）
- 所有新增代码注释采用中文教学风格，与文件现有注释密度一致