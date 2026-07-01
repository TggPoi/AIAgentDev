from enum import StrEnum

from pydantic import BaseModel, Field


class PromptRiskLevel(StrEnum):
    """Prompt Guard 风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PromptGuardAction(StrEnum):
    """Prompt Guard 对当前文本的处理动作。"""

    ALLOW = "allow"
    SANITIZE = "sanitize"
    BLOCK = "block"
    AUDIT_ONLY = "audit_only"


class PromptRiskCategory(StrEnum):
    """Prompt Injection 和敏感输出的风险类型。"""

    INSTRUCTION_OVERRIDE = "instruction_override"
    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    SECRET_EXFILTRATION = "secret_exfiltration"
    TOOL_ABUSE = "tool_abuse"
    INDIRECT_INJECTION = "indirect_injection"
    SENSITIVE_OUTPUT = "sensitive_output"


class PromptGuardResult(BaseModel):
    """一次 Prompt Guard 检测的结构化结果。"""

    action: PromptGuardAction = PromptGuardAction.ALLOW
    risk_level: PromptRiskLevel = PromptRiskLevel.LOW
    categories: list[PromptRiskCategory] = Field(default_factory=list)
    reason: str = ""
    sanitized_text: str | None = None

    @property
    def should_block(self) -> bool:
        """是否需要阻断当前请求或当前输出。"""

        return self.action == PromptGuardAction.BLOCK

    @property
    def should_sanitize(self) -> bool:
        """是否需要使用脱敏后的文本继续向下游传递。"""

        return self.action == PromptGuardAction.SANITIZE
