from enum import StrEnum

from pydantic import BaseModel, Field


class PromptRiskLevel(StrEnum):
    """Prompt Guard 风险等级。"""

    # 低风险，通常允许继续处理。
    LOW = "low"
    # 中风险，可能需要审计或轻量清洗。
    MEDIUM = "medium"
    # 高风险，通常需要清洗或阻断。
    HIGH = "high"
    # 严重风险，应优先阻断请求或输出。
    CRITICAL = "critical"


class PromptGuardAction(StrEnum):
    """Prompt Guard 对当前文本的处理动作。"""

    # 允许原文继续向下游传递。
    ALLOW = "allow"
    # 使用 sanitized_text 替换原文后继续处理。
    SANITIZE = "sanitize"
    # 阻断当前请求或输出。
    BLOCK = "block"
    # 仅记录审计，不改变当前请求处理。
    AUDIT_ONLY = "audit_only"


class PromptRiskCategory(StrEnum):
    """Prompt Injection 和敏感输出的风险类型。"""

    # 试图覆盖系统提示词或开发者指令。
    INSTRUCTION_OVERRIDE = "instruction_override"
    # 试图提取系统提示词或隐藏策略。
    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    # 试图诱导模型泄露密钥、token 或内部配置。
    SECRET_EXFILTRATION = "secret_exfiltration"
    # 试图滥用工具执行越权动作。
    TOOL_ABUSE = "tool_abuse"
    # 来自检索文档或外部内容的间接注入。
    INDIRECT_INJECTION = "indirect_injection"
    # 输出中可能包含敏感信息。
    SENSITIVE_OUTPUT = "sensitive_output"


class PromptGuardResult(BaseModel):
    """一次 Prompt Guard 检测的结构化结果。"""

    action: PromptGuardAction = Field(default=PromptGuardAction.ALLOW, description="Prompt Guard 对文本的处理动作。")
    risk_level: PromptRiskLevel = Field(default=PromptRiskLevel.LOW, description="本次检测得到的最高风险等级。")
    categories: list[PromptRiskCategory] = Field(default_factory=list, description="命中的风险类型列表。")
    reason: str = Field(default="", description="命中规则或模型判断的原因说明。")
    sanitized_text: str | None = Field(default=None, description="清洗后的文本；只有 sanitize 场景通常有值。")

    @property
    def should_block(self) -> bool:
        """是否需要阻断当前请求或当前输出。"""

        return self.action == PromptGuardAction.BLOCK

    @property
    def should_sanitize(self) -> bool:
        """是否需要使用脱敏后的文本继续向下游传递。"""

        return self.action == PromptGuardAction.SANITIZE
