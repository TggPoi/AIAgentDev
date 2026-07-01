# Qwen模型对结构化输出的支持：
## 结论

阿里云官方文档里说的 **Structured output** 本质是 **JSON mode**，配置方式是：

```json
"response_format": {"type": "json_object"}
```

它不是严格等同于 LangChain 的所有 `with_structured_output()` 模式。尤其要区分：

- `with_structured_output(method="function_calling")`：依赖工具/函数调用协议。
- `with_structured_output(method="json_schema")`：依赖 JSON Schema structured output。
- `with_structured_output(method="json_mode")`：更接近阿里云文档里的 `response_format={"type":"json_object"}`。
- 直接 OpenAI-compatible 调用：手动传 `response_format={"type":"json_object"}`，再用 Pydantic 校验。

对 Qwen，我建议优先按 **JSON mode + Pydantic 校验** 理解，不要默认用 `function_calling`。

## Qwen 哪些支持 JSON mode

根据阿里云官方文档，支持 JSON mode 的 Qwen 文本模型包括：

- Qwen-Max 非思考模式：
  - Qwen3.6-Max series
  - Qwen3-Max series
  - Qwen-Max series

- Qwen-Plus 非思考模式：
  - Qwen3.7-Plus series
  - Qwen3.6-Plus series
  - Qwen3.5-Plus series
  - Qwen-Plus series

- Qwen-Flash 非思考模式：
  - Qwen3.6-Flash series
  - Qwen3.5-Flash series
  - Qwen-Flash series

- Qwen-Turbo series

- Qwen-Coder：
  - Qwen3-Coder series

- Qwen-Long series

- 开源系列：
  - Qwen3.6 open-source 非思考模式
  - Qwen3.5 open-source 非思考模式
  - Qwen3 open-source 非思考模式
  - Qwen3-Coder open-source series
  - Qwen2.5 open-source series，排除 math 和 coder models

限制点：**thinking mode 不支持 structured output / JSON mode**。官方也明确说，thinking mode 下不要设置 `response_format={"type":"json_object"}`。

来源：阿里云 Structured output 文档说明支持模型和 thinking mode 限制。  
https://www.alibabacloud.com/help/en/model-studio/qwen-structured-output

## OpenAI-compatible JSON mode 配置方式

原生 OpenAI-compatible 调用时这样配置：

```python
completion = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {
            "role": "system",
            "content": "You are a JSON classifier. Return the result as JSON.",
        },
        {
            "role": "user",
            "content": "待分类文本...",
        },
    ],
    response_format={"type": "json_object"},
)
```

两个关键要求：

1. 请求体必须带：

```python
response_format={"type": "json_object"}
```

2. system 或 user message 里必须出现 `JSON` 这个词，否则接口会报错。

官方还提醒：启用 JSON mode 时不要设置 `max_tokens`，否则可能截断 JSON，导致解析失败。

## LangChain 里怎么用

如果是 Qwen OpenAI-compatible，我建议分两种情况。

支持 `with_structured_output(method="json_mode")` 时，可以尝试：

```python
structured_model = model.with_structured_output(
    PromptGuardResult,
    method="json_mode",
)
result = await structured_model.ainvoke(messages)
```

如果 `with_structured_output` 在当前 Qwen 模型上不稳定，更稳的是直接 bind：

```python
json_model = model.bind(
    response_format={"type": "json_object"}
)

response = await json_model.ainvoke(messages)
content = str(response.content)

result = PromptGuardResult.model_validate_json(content)
```

这个方式最贴近阿里云 OpenAI-compatible 文档。

## 当前工程建议

你当前 `.env` 如果使用 Qwen3.5+，建议先这样：

```env
PROMPT_GUARD_STRUCTURED_OUTPUT_ENABLED=false
PROMPT_GUARD_STRUCTURED_OUTPUT_METHOD=json_mode
```

原因是当前工程的 `PROMPT_GUARD_STRUCTURED_OUTPUT_ENABLED=true` 走的是 LangChain `with_structured_output()` 分支。如果你确认当前 Qwen 模型不支持这个 LangChain 封装，就先关闭它。

更理想的下一步是给工程再补一个单独模式：

```env
PROMPT_GUARD_JSON_MODE_ENABLED=true
```

代码里走：

```python
self._get_classifier_model().bind(
    response_format={"type": "json_object"}
)
```

这样就能区分：

- provider structured output：给支持 `with_structured_output` 的模型用
- Qwen JSON mode：给阿里云 OpenAI-compatible `response_format=json_object` 用
- fallback JSON parse：兜底路径

当前结论：**Qwen3.5 Plus 及之后的非思考模式支持 JSON mode，但不应默认等同于支持 LangChain 的 `function_calling/json_schema` structured output。Qwen 路线优先用 `response_format={"type":"json_object"}` + Pydantic 校验。**


# 结构化输出的另一个方案：自定义Tool调用

你说的是**显式自定义 tool**，让模型调用这个 tool，并把结构化结果放到 tool arguments 里。这个方向是成立的。

它和：

```python
with_structured_output(method="function_calling")
```

底层思路很接近，都是利用 tool/function calling 协议。但区别是：

```text
with_structured_output：
    LangChain 帮你把 Pydantic schema 包装成一个隐式工具，并帮你解析结果。

自定义 tool：
    你自己定义工具名、description、args_schema，然后手动检查模型是否真的调用了该 tool，再解析 tool_call.args。
```

所以自定义 tool 更显式，也更适合学习和调试。

## Python / LangChain 对应写法

在当前工程里可以类似这样写：

```python
from pydantic import BaseModel, Field
from langchain_core.tools import tool


class PromptGuardClassifierArgs(BaseModel):
    action: str = Field(description="allow, sanitize, block, or audit_only")
    risk_level: str = Field(description="low, medium, high, or critical")
    categories: list[str] = Field(default_factory=list)
    reason: str = Field(description="short reason")
    sanitized_text: str | None = None


@tool("classify_prompt_guard", args_schema=PromptGuardClassifierArgs)
def classify_prompt_guard(
    action: str,
    risk_level: str,
    categories: list[str],
    reason: str,
    sanitized_text: str | None = None,
) -> str:
    """Return the structured Prompt Guard classification result."""
    return "ok"
```

然后绑定：

```python
model_with_tool = model.bind_tools(
    [classify_prompt_guard],
    tool_choice="classify_prompt_guard",
)
```

调用：

```python
response = await model_with_tool.ainvoke(messages)
```

解析：

```python
tool_calls = getattr(response, "tool_calls", []) or []
if not tool_calls:
    raise ValueError("classifier did not call classify_prompt_guard")

tool_call = tool_calls[0]
args = tool_call["args"]

result = PromptGuardResult.model_validate(args)
```

## 为什么这比纯 Prompt 稳

因为模型不只是生成一段普通文本：

```text
{"action": "block", ...}
```

而是生成：

```text
tool_call:
  name: classify_prompt_guard
  args:
    action: block
    risk_level: high
    categories: [...]
```

也就是结构化参数对象进入了 tool calling 协议。通常比自然语言 JSON 更可靠。

## 但仍然不是 100% 保证

你仍然要处理这些异常：

```text
模型没有调用 tool
调用了错误 tool
args 字段缺失
args 枚举值非法
args 类型不对
provider 不支持 tool_choice 强制指定
provider 声称支持 tools 但兼容性不完整
```

所以工程上仍然需要：

```python
PromptGuardResult.model_validate(args)
```

以及失败策略：

```text
hybrid 模式：fallback 到 rule_result
llm 模式：fail closed，block
```

## 和当前工程怎么结合

你可以把当前 Prompt Guard classifier 做成三层：

```text
1. explicit_tool_call
   model.bind_tools([classify_prompt_guard], tool_choice=...)
   手动解析 tool_calls[0].args

2. qwen_json_mode
   model.bind(response_format={"type": "json_object"})
   PromptGuardResult.model_validate_json(content)

3. prompt_json_parse
   当前 _extract_json_object()
   PromptGuardResult.model_validate(...)
```

然后 `.env` 可以变成：

```env
PROMPT_GUARD_CLASSIFIER_OUTPUT_MODE=explicit_tool_call
```

可选值：

```text
explicit_tool_call
structured_output
json_mode
prompt_json
```

## 关键判断

如果你的模型/provider 对 tool calling 支持稳定，自定义 tool 是非常好的方案。它比纯 Prompt JSON 更可靠，也比 `with_structured_output()` 更透明。

但如果你当前主要使用 Qwen OpenAI-compatible，而且该模型版本不稳定支持 tool calling，那么 Qwen 路线仍然建议优先：

```text
response_format={"type": "json_object"}
+ Pydantic 校验
```

自定义 tool 更适合放在支持 tool calling 的模型分支里。