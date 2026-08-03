"""TaskPlan JSON/Markdown 快照的原子文件存储。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fast_app.core.config import Settings
from fast_app.core.logging import get_logger
from fast_app.domain.agent_task_plan import AgentTaskPlan, AgentTaskPlanStatus
from fast_app.domain.knowledge_document_actions import KnowledgeDocumentOperation
from fast_app.domain.research_task_plan import ResearchTaskPlan
from fast_app.services.exceptions import AgentTaskPlanSchemaUnsupportedError, AppServiceError


StoredAgentTaskPlan = AgentTaskPlan | ResearchTaskPlan
logger = get_logger(__name__)

class AgentTaskPlanStore:
    """用 runtime JSON 文件保存 TaskPlan 的当前快照。"""

    def __init__(self, settings: Settings) -> None:
        self._task_plan_dir = Path(settings.agent_task_plan_dir)

    def save(self, plan: StoredAgentTaskPlan) -> None:
        """新增或覆盖同一个 task_plan_id 对应的 JSON 文件。"""

        # JSON 是接口读取的事实快照；Markdown 是同一份事实的人类可读视图。
        self._task_plan_dir.mkdir(parents=True, exist_ok=True)
        plan.updated_at = datetime.now(UTC)
        path = self._path_for_new_plan(plan)
        self._atomic_write_text(path, plan.model_dump_json(indent=2))
        try:
            self._atomic_write_text(
                path.with_suffix(".md"),
                _render_task_plan_markdown(plan),
            )
        except OSError as exc:
            # JSON 是唯一事实源；Markdown 只是可再生成的审查视图。
            logger.warning("TaskPlan Markdown 快照写入失败: %s", type(exc).__name__)

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        """在目标目录写完临时文件后原子替换，避免轮询者读到半份快照。"""

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temp_path = Path(handle.name)
            os.replace(temp_path, path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def load(self, task_plan_id: str) -> StoredAgentTaskPlan:
        """按 task_plan_id 读取最近一次保存的计划快照。"""

        # task_plan_id 来自外部确认接口，先做最小格式校验，避免任意 glob 查询。
        if not task_plan_id.startswith("task_plan_"):
            raise AppServiceError("非法 task_plan_id")
        self._task_plan_dir.mkdir(parents=True, exist_ok=True)
        matches = sorted(self._task_plan_dir.glob(f"*_{task_plan_id}.json"))
        if not matches:
            raise AppServiceError("Agent task plan 不存在")
        payload = json.loads(matches[-1].read_text(encoding="utf-8"))
        if payload.get("task_kind") == "question_decomposition":
            if payload.get("schema_version") != 2:
                raise AgentTaskPlanSchemaUnsupportedError(
                    "Research TaskPlan schema_version 不受支持"
                )
            return ResearchTaskPlan.model_validate(payload)
        return AgentTaskPlan.model_validate(payload)

    def load_markdown(self, task_plan_id: str) -> str:
        """读取面向人工审查的 Markdown；没有旧文件时按 JSON 现场渲染。"""

        plan = self.load(task_plan_id)
        matches = sorted(self._task_plan_dir.glob(f"*_{task_plan_id}.md"))
        if matches:
            return matches[-1].read_text(encoding="utf-8")
        return _render_task_plan_markdown(plan)

    def _path_for_new_plan(self, plan: StoredAgentTaskPlan) -> Path:
        """已有文件继续覆盖，避免同一个 plan 在执行中生成多份快照。"""

        existing = sorted(self._task_plan_dir.glob(f"*_{plan.task_plan_id}.json"))
        if existing:
            return existing[-1]
        created = plan.created_at.strftime("%Y%m%d_%H%M%S")
        return self._task_plan_dir / f"{created}_{plan.task_plan_id}.json"



def _render_task_plan_markdown(plan: StoredAgentTaskPlan) -> str:
    """把 TaskPlan JSON 快照渲染成更适合人工审查的 Markdown。"""

    if isinstance(plan, ResearchTaskPlan):
        return _render_research_task_plan_markdown(plan)

    lines = [
        f"# Agent TaskPlan: {plan.task_plan_id}",
        "",
        f"- 状态: `{plan.status.value}`",
        f"- 任务类型: `{plan.task_kind}` / `{plan.task_type}`",
        f"- 用户目标: {plan.objective}",
        f"- 原始问题: {plan.original_query}",
        f"- 检索 query: `{plan.source_query}`",
        f"- 查询接口: `/agent/task-plans/{plan.task_plan_id}`",
        f"- 确认接口: `/agent/task-plans/{plan.task_plan_id}/confirm`",
        f"- 取消接口: `/agent/task-plans/{plan.task_plan_id}/cancel`",
        f"- 重试接口: `/agent/task-plans/{plan.task_plan_id}/retry`",
    ]

    if plan.task_kind == "question_decomposition":
        if plan.research_policy is not None:
            lines.extend(
                [
                    "",
                    "## 研究参数",
                    "",
                    f"```json\n{plan.research_policy.model_dump_json(indent=2)}\n```",
                ]
            )
        lines.extend(["", "## 子问题拆解"])
        for item in sorted(plan.sub_questions, key=lambda sub: sub.order):
            depends_on = ", ".join(item.depends_on) if item.depends_on else "无"
            lines.extend(
                [
                    "",
                    f"### {item.order}. {item.question}",
                    "",
                    f"- sub_question_id: `{item.sub_question_id}`",
                    f"- 目的: {item.purpose}",
                    f"- 依赖: {depends_on}",
                    f"- 建议信息来源: `{item.information_source_hint}`",
                    f"- 拆解原因: {item.reason}",
                    f"- 期望证据: {item.expected_evidence or '无'}",
                ]
            )
        lines.extend(["", "## 最终整合要求", "", plan.final_synthesis_instruction])

        results = plan.final_output.get("sub_question_results", [])
        # JSON 快照可能来自旧版本或中断前的状态，渲染时继续做类型收敛，不能让展示接口失败。
        if isinstance(results, list) and results:
            lines.extend(["", "## 执行结果"])
            for result in results:
                if not isinstance(result, dict):
                    continue
                lines.extend(
                    [
                        "",
                        f"### {result.get('sub_question_id')} - {result.get('question')}",
                        "",
                        f"- 状态: `{result.get('status')}`",
                        f"- 使用工具: `{result.get('selected_tool')}`",
                        "",
                        result.get("answer") or result.get("error") or "",
                    ]
                )

        final_answer = plan.final_output.get("final_answer")
        if isinstance(final_answer, str) and final_answer.strip():
            lines.extend(["", "## 最终答案", "", final_answer.strip()])
    else:
        checkpoint = plan.final_output.get("checkpoint")
        if isinstance(checkpoint, dict):
            lines.extend(
                [
                    "",
                    "## Tool Loop 检查点",
                    "",
                    f"- 版本: `{checkpoint.get('version', '')}`",
                    f"- 最近完整轮次: `{checkpoint.get('round', 0)}`",
                    f"- 已消耗 ToolCall: `{checkpoint.get('call_count', 0)}`",
                    f"- 候选 doc_id: `{json.dumps(list((checkpoint.get('candidates') or {}).keys()), ensure_ascii=False)}`",
                    f"- 已读取 doc_id: `{json.dumps(checkpoint.get('read_doc_ids', []), ensure_ascii=False)}`",
                    f"- Tool Loop 已完成: `{checkpoint.get('completed', False)}`",
                ]
            )
        lines.extend(["", "## 文档动作"])
        for step in plan.steps:
            # Markdown 是审查视图：只读取 step 已冻结的 output，不重新调用领域服务取最新文档。
            preview = step.output.get("preview")
            preview = preview if isinstance(preview, dict) else {}
            action_request = step.output.get("action_request")
            action_request = action_request if isinstance(action_request, dict) else {}
            operation = str(action_request.get("operation") or "")
            target_path = action_request.get("target_path") or step.input.get("target_path")
            warnings = preview.get("warnings")
            warnings = warnings if isinstance(warnings, list) else []
            lines.extend(
                [
                    "",
                    f"### {step.tool_name}: {target_path}",
                    "",
                    f"- 状态: `{step.status.value}`",
                    f"- tool_call_id: `{step.output.get('tool_call_id', '')}`",
                    f"- 操作: `{operation}`",
                    f"- 目标路径: `{target_path}`",
                    f"- doc_id: `{preview.get('affected_doc_id', '')}`",
                    f"- 风险等级: `{step.risk_level}`",
                    f"- 需要确认: `{step.requires_confirmation}`",
                    f"- 选择理由: {step.output.get('selection_reason') or '用户明确指定或创建任务'}",
                    f"- 操作原因: {action_request.get('reason') or '无'}",
                    f"- 权限: `{json.dumps(preview.get('permission_metadata', {}), ensure_ascii=False)}`",
                    f"- 影响 chunk 数: `{preview.get('affected_chunk_count', 0)}`",
                    f"- before_hash: `{preview.get('before_hash') or ''}`",
                    f"- after_hash: `{preview.get('after_hash') or ''}`",
                    f"- warnings: `{json.dumps(warnings, ensure_ascii=False)}`",
                ]
            )

            content = action_request.get("content")
            if operation == KnowledgeDocumentOperation.CREATE.value and isinstance(content, str):
                lines.extend(["", "#### 候选正文", "", *_markdown_fenced_block(content, "markdown")])

            replacements = step.output.get("replacements")
            if operation == KnowledgeDocumentOperation.UPDATE.value and isinstance(replacements, list):
                for index, replacement in enumerate(replacements, start=1):
                    if not isinstance(replacement, dict):
                        continue
                    lines.extend(
                        [
                            "",
                            f"#### 精确替换 {index}",
                            "",
                            "##### old_text",
                            "",
                            *_markdown_fenced_block(str(replacement.get("old_text") or ""), "text"),
                            "",
                            "##### new_text",
                            "",
                            *_markdown_fenced_block(str(replacement.get("new_text") or ""), "text"),
                        ]
                    )

            diff = step.output.get("diff")
            if isinstance(diff, str) and diff.strip():
                lines.extend(["", "#### 差异", "", *_markdown_fenced_block(diff, "diff")])

            candidate = step.output.get("candidate")
            if operation == KnowledgeDocumentOperation.DELETE.value and isinstance(candidate, dict):
                lines.extend(
                    [
                        "",
                        "#### 删除候选证据",
                        "",
                        f"- 标题: {candidate.get('title') or '无'}",
                        f"- source_path: `{candidate.get('source_path') or ''}`",
                    ]
                )
                matched_chunks = candidate.get("matched_chunks")
                if isinstance(matched_chunks, list):
                    for index, chunk in enumerate(matched_chunks, start=1):
                        lines.extend(
                            [
                                "",
                                f"##### 匹配片段 {index}",
                                "",
                                *_markdown_fenced_block(str(chunk), "text"),
                            ]
                        )

            execution_result = step.output.get("execution_result")
            if isinstance(execution_result, dict):
                lines.extend(
                    [
                        "",
                        "#### 执行结果",
                        "",
                        f"- executed: `{execution_result.get('executed', False)}`",
                        f"- message: {execution_result.get('message') or '无'}",
                    ]
                )
            elif step.error:
                lines.extend(["", "#### 执行错误", "", step.error])

    if plan.status == AgentTaskPlanStatus.FAILED and plan.error:
        lines.extend(["", "## 计划错误", "", plan.error])
    return "\n".join(lines) + "\n"


def _render_research_task_plan_markdown(plan: ResearchTaskPlan) -> str:
    """从 ResearchTaskPlan v2 结构化事实生成只读审查视图。"""

    lines = [
        f"# Research TaskPlan: {plan.task_plan_id}",
        "",
        f"- Schema: `{plan.schema_version}`",
        f"- 状态: `{plan.status.value}`",
        f"- 目标: {plan.objective}",
        f"- 解析后问题: {plan.source_query}",
        f"- 确认接口: `/agent/task-plans/{plan.task_plan_id}/confirm`",
        "",
        "## Requirements",
    ]
    statuses = {item.requirement_id: item for item in plan.requirement_evidence_statuses}
    for requirement in plan.requirements:
        status = statuses.get(requirement.requirement_id)
        lines.extend(
            [
                "",
                f"### {requirement.requirement_id}",
                "",
                f"- 描述: {requirement.description}",
                f"- 来源策略: `{requirement.source_policy.mode}` / "
                f"`{', '.join(requirement.source_policy.source_types) or 'none'}`",
                f"- 完成策略: `{requirement.completion_policy}`",
                f"- 当前状态: `{status.status if status else 'pending'}`",
            ]
        )
    lines.extend(["", "## SubQuestions"])
    results = {item.sub_question_id: item for item in plan.sub_question_results}
    for sub_question in sorted(plan.sub_questions, key=lambda item: item.order):
        result = results.get(sub_question.sub_question_id)
        lines.extend(
            [
                "",
                f"### {sub_question.order}. {sub_question.question}",
                "",
                f"- ID: `{sub_question.sub_question_id}`",
                f"- 覆盖: `{', '.join(sub_question.covers_requirement_ids)}`",
                f"- 依赖: `{', '.join(sub_question.depends_on) or 'none'}`",
                f"- 来源: `{sub_question.information_source_hint}`",
                f"- WebUsage: `{sub_question.web_usage}`",
                f"- 执行状态: `{result.status if result else 'pending'}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Quality Review",
            "",
            f"- Verdict: `{plan.quality_review.verdict}`",
            f"- Revision count: `{plan.quality_review.revision_count}`",
            "",
            "## Final Synthesis",
            "",
            plan.final_output.answer if plan.final_output else "尚未执行。",
        ]
    )
    return "\n".join(lines) + "\n"

def _markdown_fenced_block(text: str, language: str) -> list[str]:
    """生成不会被正文内部反引号提前闭合的 Markdown 代码块。"""

    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    # 栅栏长度必须大于正文中最长的连续反引号，避免 diff/正文提前闭合代码块。
    fence = "`" * max(3, longest_run + 1)
    return [f"{fence}{language}", text, fence]

__all__ = ["AgentTaskPlanStore", "StoredAgentTaskPlan"]
