---
name: document-writing
description: 依据研究证据和原文生成完整、可审查的 Markdown/TXT 草稿。
---

# Document Writing

1. 每个交付物使用独立草稿文件，正文写入 `/workspace/drafts`。
2. 更新必须读取 Researcher 保存到 `/workspace/research/{deliverable_id}/source.md` 的完整原文，并继承 summary 中的服务端候选身份和 `base_sha256`。
3. 事实结论必须能对应 `evidence_refs`；不确定内容写入 assumptions 或 unresolved_points。
4. Reviewer 要求修订时只修改指出的问题，不扩大操作范围。
5. 输出完整目标正文，不输出可直接操作真实知识库的命令。
