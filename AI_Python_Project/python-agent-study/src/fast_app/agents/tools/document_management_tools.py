"""知识库文档管理 Tool 的参数契约与构造函数。

这个模块不直接执行文档的读取、创建、修改或删除。
它负责完成三件事：

1. 定义暴露给 LLM 的工具名称；
2. 使用 Pydantic 模型约束每个工具允许接收的参数；
3. 把业务层传入的异步函数包装成 LangChain ``StructuredTool``。

真正的文档读写逻辑由调用方传入的 coroutine 实现。本模块只负责建立
“LLM 可以看到什么工具、每个工具需要什么参数”的边界。
"""

from collections.abc import Awaitable, Callable

from langchain_core.tools import BaseTool, StructuredTool
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


# 工具名是 LLM Tool Calling、工具注册表以及执行器之间共同使用的稳定标识。
# 不建议随意修改这些字符串，否则模型返回的 tool name 可能无法被后端正确匹配。
KNOWLEDGE_DOCUMENT_READ_TOOL_NAME = "knowledge_document_read"
KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME = "knowledge_document_create"
KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME = "knowledge_document_update"
KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME = "knowledge_document_delete"


class KnowledgeDocumentReadToolInput(BaseModel):
    """读取文档工具的参数结构。

    这里只允许模型提交 doc_id，不允许模型直接提供文件路径。doc_id 必须来自
    当前一轮经过权限过滤的知识库检索结果，调用方会再根据 doc_id 查找真实文档。
    """

    # extra="forbid" 表示：如果 LLM 额外生成 schema 中不存在的参数，
    # Pydantic 会直接校验失败，而不是静默忽略这些未知参数。
    model_config = ConfigDict(extra="forbid")

    # min_length=1 阻止空字符串；description 会进入 Tool 的 JSON Schema，
    # 用于告诉 LLM 这个参数的含义和来源。
    doc_id: str = Field(min_length=1, description="本轮知识库检索返回的候选文档 ID")


class KnowledgeDocumentCreateToolInput(BaseModel):
    """创建文档 dry-run 工具的参数结构。

    创建工具需要模型一次性给出候选文件名、完整正文和创建原因。
    这里的 filename 只代表文件名，最终目录仍由服务端根据用户作用域决定。
    """

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(
        min_length=1,
        max_length=255,
        description="建议文件名，只允许 .md 或 .txt；目录由服务端决定",
    )
    # content 要求是完整候选正文，而不是局部 patch。长度上限用于限制异常大输入。
    content: str = Field(min_length=1, max_length=200_000, description="完整候选正文")
    # reason 会进入后续 dry-run、人工确认和审计信息，因此不能省略。
    reason: str = Field(min_length=1, max_length=1000, description="创建原因")

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        """规范化并校验模型建议的文件名。

        ``Path(value.strip()).name`` 只保留路径最后一段。例如模型传入
        ``development/guide.md`` 时，最终得到 ``guide.md``。这样可以避免 LLM
        自己决定目录，目录必须由后端的权限与用户作用域规则生成。
        """

        # 去掉首尾空白后，通过 Path.name 丢弃父目录部分。
        filename = Path(value.strip()).name

        # 当前知识库管理工具只接受 Markdown 和纯文本文件。
        if not filename.endswith((".md", ".txt")):
            raise ValueError("filename 只允许 .md 或 .txt")

        # validator 的返回值会替换原始 filename，因此后续业务层拿到的是
        # 已经清理过、只包含文件名本身的值。
        return filename


class KnowledgeDocumentReplacement(BaseModel):
    """一次精确文本替换的参数结构。

    调用方会在完整文档中寻找 old_text，并把它替换成 new_text。通常还会要求
    old_text 在目标文档中只出现一次，以避免修改到错误位置。
    """

    model_config = ConfigDict(extra="forbid")

    # old_text 不能为空，否则无法确定要替换的目标片段。
    old_text: str = Field(min_length=1, max_length=100_000)
    # new_text 可以为空字符串；为空时就表示删除 old_text 对应的内容。
    new_text: str = Field(max_length=100_000)


class KnowledgeDocumentUpdateToolInput(BaseModel):
    """修改文档 dry-run 工具的参数结构。

    update 不直接提交完整新文档，而是提交一组精确 replacements。执行器会先读取
    原文，再逐项应用替换并生成 diff，最后形成等待人工确认的 dry-run 计划。
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, description="本轮检索返回的候选文档 ID")
    replacements: list[KnowledgeDocumentReplacement] = Field(
        # 至少要有一个替换项，否则这次 update 不会产生任何修改。
        min_length=1,
        description="一次 update 中的全部唯一精确替换",
    )
    reason: str = Field(min_length=1, max_length=1000, description="修改原因")
    selection_reason: str = Field(
        min_length=1,
        max_length=1000,
        # 该字段解释为什么检索结果中的这个 doc_id 是正确目标，便于人工审查。
        description="为什么选择该候选文档",
    )


class KnowledgeDocumentDeleteToolInput(BaseModel):
    """删除文档 dry-run 工具的参数结构。

    删除属于高风险操作，因此除了 doc_id 和删除原因，还要求模型说明为什么选择
    这个候选文档。真正删除仍需要后续权限检查和人工确认。
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1, description="本轮检索返回的候选文档 ID")
    reason: str = Field(min_length=1, max_length=1000, description="删除原因")
    selection_reason: str = Field(
        min_length=1,
        max_length=1000,
        description="为什么选择该候选文档",
    )


def _build_tool(
    *,
    coroutine: Callable[..., Awaitable[str]],
    name: str,
    description: str,
    args_schema: type[BaseModel],
) -> BaseTool:
    """把一个异步业务函数统一包装为 LangChain StructuredTool。

    参数说明：
    - coroutine：真正执行工具业务的异步函数；调用后返回 Awaitable[str]；
    - name：LLM 调用工具时使用的稳定名称；
    - description：注入模型上下文的工具说明，帮助模型判断何时调用；
    - args_schema：Pydantic 参数模型，用于生成 JSON Schema 和运行时校验。

    ``Callable[..., Awaitable[str]]`` 表示：这是一个参数形式暂不限定的可调用对象，
    调用它会得到一个可等待对象，await 之后得到字符串结果。
    """

    # StructuredTool.from_function 会读取 name、description 和 args_schema，
    # 构造一个支持结构化参数校验的 LangChain Tool。
    # 这里传入 coroutine 而不是 func，说明底层业务函数是异步函数。
    return StructuredTool.from_function(
        coroutine=coroutine,
        name=name,
        description=description,
        args_schema=args_schema,
    )


def build_knowledge_document_read_tool(
    coroutine: Callable[..., Awaitable[str]],
) -> BaseTool:
    """构造“读取完整文档”工具。

    调用方负责提供实际的异步读取函数。本函数只把该函数与固定工具名、说明文本
    和参数 schema 绑定起来，返回可交给 ``model.bind_tools()`` 的 BaseTool。
    """

    return _build_tool(
        coroutine=coroutine,
        name=KNOWLEDGE_DOCUMENT_READ_TOOL_NAME,
        description=(
            "读取本轮 knowledge_retrieval 已返回候选文档的完整正文。"
            "必须先检索，再使用候选 doc_id 调用。"
        ),
        args_schema=KnowledgeDocumentReadToolInput,
    )


def build_knowledge_document_management_tools(
    *,
    create: Callable[..., Awaitable[str]],
    update: Callable[..., Awaitable[str]],
    delete: Callable[..., Awaitable[str]],
) -> list[BaseTool]:
    """构造创建、修改、删除三个文档管理工具。

    三个参数都是由执行器或 Service 层提供的异步业务函数。本函数统一为它们绑定：

    - 固定的工具名称；
    - 面向 LLM 的 description；
    - 对应的 Pydantic 参数 schema。

    返回列表后，调用方通常会把这些工具交给 ``ChatOpenAI.bind_tools()``。
    这些工具当前表达的是 dry-run 提案：先生成预览和待确认计划，不立即写入数据源。
    """

    return [
        _build_tool(
            coroutine=create,
            name=KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME,
            description=(
                # description 会直接影响 LLM 的工具选择。这里明确声明 dry-run，
                # 防止模型调用工具后错误地向用户声称文档已经创建完成。
                "提交新增知识库文档的 dry-run 提案。只生成预览和待确认计划，"
                "不会写文件、Elasticsearch 或 Milvus。"
            ),
            args_schema=KnowledgeDocumentCreateToolInput,
        ),
        _build_tool(
            coroutine=update,
            name=KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME,
            description=(
                # update 必须建立在“先检索、再读取完整文档”的执行顺序上。
                "提交候选文档的 dry-run 精确修改提案。必须先检索并读取文档；"
                "不会执行真实修改。"
            ),
            args_schema=KnowledgeDocumentUpdateToolInput,
        ),
        _build_tool(
            coroutine=delete,
            name=KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME,
            description=(
                # 限制 doc_id 必须来自当前检索轮次，可以避免模型随意构造目标。
                "提交候选文档的 dry-run 删除提案。必须使用本轮检索返回的 doc_id；"
                "不会执行真实删除。"
            ),
            args_schema=KnowledgeDocumentDeleteToolInput,
        ),
    ]


__all__ = [
    "KNOWLEDGE_DOCUMENT_CREATE_TOOL_NAME",
    "KNOWLEDGE_DOCUMENT_DELETE_TOOL_NAME",
    "KNOWLEDGE_DOCUMENT_READ_TOOL_NAME",
    "KNOWLEDGE_DOCUMENT_UPDATE_TOOL_NAME",
    "KnowledgeDocumentCreateToolInput",
    "KnowledgeDocumentDeleteToolInput",
    "KnowledgeDocumentReadToolInput",
    "KnowledgeDocumentReplacement",
    "KnowledgeDocumentUpdateToolInput",
    "build_knowledge_document_management_tools",
    "build_knowledge_document_read_tool",
]