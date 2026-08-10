# Agent RAG Backend

本上下文描述企业 RAG 与 Agent 后端中需要跨模块保持一致的业务术语。

## Evaluation Language

**Evaluation Dataset Version**:
一组评测 case 的不可变语义版本；问题、相关来源、事实权重、身份范围或审核结论发生语义变化时必须产生新版本。
_Avoid_: Latest dataset, mutable baseline

**Candidate Evaluation Case**:
尚未完成独立人工审核、不能进入正式质量门禁的评测标注。
_Avoid_: Golden case, approved case

**Golden Evaluation Case**:
已经由人工复核问题、身份范围、逻辑来源、关键事实和权重，可进入正式质量门禁的评测标注。
_Avoid_: Fixture, candidate, model-generated case

**Eval Principal ID**:
服务端评测身份注册表中的稳定引用，用于在执行时重建真实权限范围；它不是客户端提供的 ACL，也不是某次环境中易变化的用户主键。
_Avoid_: User filter, embedded ACL, department list

**Logical Chunk ID**:
跨知识版本保持稳定、表示同一语义子块的身份；同一逻辑子块可以在不同版本中对应不同物理记录。
_Avoid_: Physical record ID, vector-store primary key

**Expected Source**:
经过审核、通过逻辑文档和逻辑子块身份追溯的问题相关证据来源。
_Avoid_: Source preview, filename-only match

**Required Key Fact**:
答案完整性评测必须检查的一条带权可核验事实；关键事实可以触发质量 hard gate。
_Avoid_: Keyword, style hint

**Knowledge Target**:
由知识版本和不可变语料 revision 共同确定的评测证据边界。
_Avoid_: Current index, latest documents

**Knowledge Release Revision**:
数据集与 case 绑定的知识发布身份，例如 `knowledge-version:6`；用于保证整次评测针对同一发布边界。
_Avoid_: Per-document commit, local directory hash

**Source Document Revision**:
一个 Expected Source 对应文档的不可变 Git commit 或等价 revision；多来源 case 必须分别记录每份文档的修订。
_Avoid_: Knowledge release version, mutable branch name
