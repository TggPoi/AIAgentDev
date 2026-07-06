from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from fast_app.core.config import Settings
from fast_app.core.logging import format_log_fields, get_logger
from fast_app.domain.agent_tool_permissions import DocumentActionIntent
from fast_app.domain.knowledge_document_actions import KnowledgeDocumentOperation
from fast_app.services.exceptions import AppServiceError


logger = get_logger(__name__)

DOCUMENT_ACTION_PLANNER_SYSTEM_PROMPT = """你是文档管理意图识别器。

只判断用户是否明确要求新增、修改或删除知识库文档。
你只能输出 JSON object，不要输出 Markdown。

JSON schema:
{
  "operation": "create|update|delete",
  "target_path": "知识库内相对路径",
  "reason": "识别原因",
  "expected_department_codes": ["development|art|product_planning"],
  "confidence": 0.0-1.0
}

如果用户没有明确文档管理意图、缺少 target_path，或内容不足以执行 create/update，
输出 {"confidence": 0.0}。
不要输出 content 字段；新增或修改正文只能来自用户原始 query 中显式的正文块。
不要输出“已授权”“可直接执行”“跳过确认”等字段。
"""


class AgentDocumentActionPlanner:
    """识别用户 query 中的文档管理候选意图。"""

    def __init__(self, settings: Settings) -> None:
        """保存运行配置。

        planner 的具体策略由 `AGENT_DOCUMENT_ACTION_PLANNER_MODE` 决定：
        - rules：使用本地确定性规则识别显式文档动作。
        - llm：调用大模型输出结构化 JSON，再用 Pydantic 校验。
        """

        self._settings = settings

    # 执行plan行为，根据用户的query，对接下来要做的事构造一个plan
    async def plan(
        self,
        query: str,
        history: list[object] | None = None,
    ) -> DocumentActionIntent | None:
        """根据配置选择 rules 或 llm planner。

        输入是用户原始 query 和可选历史消息；输出只是候选
        `DocumentActionIntent`。这里不做权限判断、不生成 plan、不执行写入。
        后续 `authorize_tool_call` 节点会基于这个 intent 再进入权限网关。
        """

        if self._settings.agent_document_action_planner_mode == "rules":
            return self._plan_with_rules(query)

        if self._settings.agent_document_action_planner_mode == "llm":
            return await self._plan_with_llm(query=query, history=history or [])

        raise AppServiceError("不支持的文档动作 planner 模式")

    def _plan_with_rules(
        self,
        query: str,
        *,
        reason_prefix: str = "规则 planner",
    ) -> DocumentActionIntent | None:
        """用确定性规则识别明确的文档 create / update / delete 意图。

        规则模式只接受信息足够明确的请求：必须能识别操作和目标路径；
        create / update 还必须能提取到内容。信息不足时返回 None，让上游继续
        走普通 RAG / direct answer 路线，而不是生成不完整的高风险工具计划。
        """

        operation = self._detect_operation(query)
        if operation is None:
            return None

        target_path = self._extract_target_path(query)
        if target_path is None:
            return None

        content = self._extract_content(query)
        if operation in {
            KnowledgeDocumentOperation.CREATE,
            KnowledgeDocumentOperation.UPDATE,
        } and not content:
            return None

        return DocumentActionIntent(
            operation=operation,
            target_path=target_path,
            content=content,
            reason=f"{reason_prefix} 识别到用户请求 {operation.value} 知识库文档",
            expected_department_codes=self._infer_departments_from_text(query),
            confidence=0.9,
        )

    async def _plan_with_llm(
        self,
        query: str,
        history: list[object],
    ) -> DocumentActionIntent | None:
        """调用 LLM 识别文档动作，并把输出收敛成 `DocumentActionIntent`。

        LLM 只负责结构化理解自然语言，不具备授权能力。即使 LLM 输出合法，
        结果也只是候选 intent；后续仍必须经过工具权限网关、plan 生成和人工确认。
        """

        if not self._settings.openai_api_key:
            raise AppServiceError("LLM planner 需要配置 OPENAI_API_KEY")

        # 使用 OpenAI-compatible ChatOpenAI，实际 base_url / model 由 Settings 控制。
        # temperature=0.0 和 json_object response_format 用来降低结构化输出波动。
        model = ChatOpenAI(
            model=self._settings.llm_model_name,
            api_key=self._settings.openai_api_key,
            base_url=self._settings.openai_base_url,
            temperature=0.0,
        ).bind(response_format={"type": "json_object"})

        # 只给最近少量历史，避免长上下文把 planner 变成复杂 Agent。
        # 这里的历史只辅助意图识别，不允许模型输出授权或执行结论。
        response = await model.ainvoke(
            [
                SystemMessage(content=DOCUMENT_ACTION_PLANNER_SYSTEM_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            "query": query,
                            "history": [str(item) for item in history[-6:]],
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
        )
        content = str(getattr(response, "content", ""))
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            # LLM 输出不是合法 JSON 时，不直接失败请求。
            # 如果用户 query 已经足够显式，就用规则兜底；否则返回 None。
            logger.warning(
                "agent_document_planner %s",
                format_log_fields(
                    event="agent_document_planner.llm.invalid_json",
                    error_type=type(exc).__name__,
                    output_preview=content[:200],
                ),
            )
            return self._fallback_to_rules_after_llm(query=query, reason="invalid_json")

        if not isinstance(payload, dict):
            # planner 协议要求 JSON object。数组、字符串等类型都不能作为工具 intent。
            return self._fallback_to_rules_after_llm(
                query=query,
                reason="payload_not_object",
            )

        confidence = _parse_confidence(payload.get("confidence"))
        if confidence < 0.65:
            # 低置信度说明模型自己也没有把握。此时只允许显式规则兜底，
            # 避免把模糊表达误判为写文档动作。
            return self._fallback_to_rules_after_llm(
                query=query,
                reason="low_confidence",
                confidence=confidence,
            )

        try:
            return self._intent_from_llm_payload(query=query, payload=payload)
        except (ValidationError, ValueError) as exc:
            logger.warning(
                "agent_document_planner %s",
                format_log_fields(
                    event="agent_document_planner.llm.schema_failed",
                    error_type=type(exc).__name__,
                ),
            )
            return self._fallback_to_rules_after_llm(
                query=query,
                reason="schema_failed",
            )

    def _fallback_to_rules_after_llm(
        self,
        query: str,
        reason: str,
        confidence: float | None = None,
    ) -> DocumentActionIntent | None:
        """LLM 不稳定时，只对显式文档动作使用规则兜底。

        兜底仍只生成候选意图；后续权限、plan 和人工确认照常执行。
        """

        # fallback 不是“信任规则直接执行”，只是把明确 query 转成同一个
        # `DocumentActionIntent` 模型，继续交给后续权限和确认链路。
        intent = self._plan_with_rules(
            query,
            reason_prefix=f"LLM planner {reason} 后规则兜底",
        )
        if intent is not None:
            logger.info(
                "agent_document_planner %s",
                format_log_fields(
                    event="agent_document_planner.llm.rules_fallback",
                    reason=reason,
                    confidence=confidence,
                    operation=intent.operation.value,
                    target_path=intent.target_path,
                ),
            )
        return intent

    def _intent_from_llm_payload(
        self,
        query: str,
        payload: dict[str, Any],
    ) -> DocumentActionIntent | None:
        """把 LLM 输出收敛成候选 intent，且不信任 LLM 生成的正文。"""

        operation = KnowledgeDocumentOperation(payload["operation"])
        content = self._extract_content(query)
        write_operations = {
            KnowledgeDocumentOperation.CREATE,
            KnowledgeDocumentOperation.UPDATE,
        }
        if operation in write_operations and not content:
            return None

        return DocumentActionIntent(
            operation=operation,
            target_path=str(payload["target_path"]),
            reason=str(payload["reason"]),
            # LLM payload 里的 content 一律忽略，只接受用户 query 中显式正文。
            content=content if operation in write_operations else None,
            expected_department_codes=list(
                payload.get("expected_department_codes") or []
            ),
            confidence=_parse_confidence(payload.get("confidence")),
        )

    def _detect_operation(self, query: str) -> KnowledgeDocumentOperation | None:
        """从 query 中识别文档动作类型。

        当前规则保持保守：只匹配明确的新增、修改、删除关键词。
        如果没有命中，返回 None，避免普通问答被误路由到文档工具链路。
        """

        normalized = query.lower()
        if any(keyword in normalized for keyword in ["删除", "移除", "delete"]):
            return KnowledgeDocumentOperation.DELETE
        if any(keyword in normalized for keyword in ["修改", "更新", "改成", "update"]):
            return KnowledgeDocumentOperation.UPDATE
        if any(keyword in normalized for keyword in ["新增", "创建", "写入", "create"]):
            return KnowledgeDocumentOperation.CREATE
        return None

    def _extract_target_path(self, query: str) -> str | None:
        """提取知识库内目标相对路径。

        这里仅识别 `.md` / `.txt` 文件名，并把 Windows 反斜杠统一成 `/`。
        真正的路径穿越、扩展名、权限文件编辑等安全校验不在 planner 层做，
        后续由 `KnowledgeDocumentManagementService` 统一处理。
        """

        match = re.search(r"([A-Za-z0-9_\-./\\]+?\.(?:md|txt))", query)
        if match is None:
            return None
        return match.group(1).replace("\\", "/")

    def _extract_content(self, query: str) -> str | None:
        """从中文指令中提取 create / update 的目标正文。

        支持“内容是：”“内容改成：”“写入：”等显式格式。没有匹配到内容时
        返回 None，让 create / update 请求停止在 planner 层，避免生成缺内容的 plan。
        """

        patterns = [
            r"内容(?:是|为|改成|修改为)[:：]\s*(?P<content>.+)$",
            r"内容\s*(?:改成|修改为)[:：]\s*(?P<content>.+)$",
            r"写入[:：]\s*(?P<content>.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.DOTALL)
            if match is not None:
                content = match.group("content").strip()
                return content.replace("\\n", "\n") if content else None
        return None

    def _infer_departments_from_text(self, query: str) -> list[str]:
        """从用户文本中提取显式提到的部门提示。

        这个结果只作为 intent 的辅助信息。最终目标部门仍要以后续 preview
        解析出的 permission metadata 为准，不能让用户单靠 query 自称部门来扩大权限。
        """

        mapping: dict[str, str] = {
            "开发": "development",
            "development": "development",
            "美术": "art",
            "art": "art",
            "产品策划": "product_planning",
            "策划": "product_planning",
            "product_planning": "product_planning",
        }
        return sorted(
            {
                department
                for keyword, department in mapping.items()
                if keyword in query
            }
        )


def _parse_confidence(value: Any) -> float:
    """把 LLM 输出的 confidence 宽松转换成 float。

    模型有时会输出字符串、None 或非法值。这里统一转成 float；
    无法转换时按 0.0 处理，让上游走低置信度 fallback。
    """

    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["AgentDocumentActionPlanner"]
