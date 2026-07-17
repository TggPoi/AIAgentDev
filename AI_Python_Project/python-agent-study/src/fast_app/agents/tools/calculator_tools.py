import ast
import operator
from typing import Literal

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from fast_app.core.config import Settings


CALCULATOR_TOOL_NAME = "calculator"
CalculatorOperation = Literal["add", "subtract", "multiply", "divide"]
CalculatorMode = Literal["basic_ops", "safe_expression"]


class CalculatorBasicOpsInput(BaseModel):
    """结构化四则运算输入。"""

    operation: CalculatorOperation = Field(description="计算操作")
    left: float = Field(description="左操作数")
    right: float = Field(description="右操作数")


class CalculatorExpressionInput(BaseModel):
    """安全表达式计算输入。"""

    expression: str = Field(description="只包含数字、括号和四则运算符的表达式")


ALLOWED_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

ALLOWED_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def calculate_basic_ops(
    *,
    operation: CalculatorOperation,
    left: float,
    right: float,
) -> float:
    """执行结构化四则运算，不解析或执行用户字符串。"""
    if operation == "add":
        return left + right

    if operation == "subtract":
        return left - right

    if operation == "multiply":
        return left * right

    if operation == "divide":
        if right == 0:
            raise ValueError("除数不能为 0")
        return left / right

    raise ValueError(f"不支持的计算操作: {operation}")


def _ensure_result_in_range(value: float, max_abs_value: float) -> float:
    if abs(value) > max_abs_value:
        raise ValueError("计算结果超出允许范围")

    return value


def _eval_ast_node(node: ast.AST, *, max_abs_value: float) -> float:
    """递归求值安全 AST 节点，只允许数字、括号和四则运算。"""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("表达式只能包含数字")

        return _ensure_result_in_range(float(node.value), max_abs_value)

    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        op = ALLOWED_BIN_OPS.get(op_type)
        if op is None:
            raise ValueError("表达式只支持 + - * / 运算符")

        left = _eval_ast_node(node.left, max_abs_value=max_abs_value)
        right = _eval_ast_node(node.right, max_abs_value=max_abs_value)
        if op_type is ast.Div and right == 0:
            raise ValueError("除数不能为 0")

        return _ensure_result_in_range(op(left, right), max_abs_value)

    if isinstance(node, ast.UnaryOp):
        op = ALLOWED_UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("表达式只支持正负号")

        operand = _eval_ast_node(node.operand, max_abs_value=max_abs_value)
        return _ensure_result_in_range(op(operand), max_abs_value)

    raise ValueError("表达式包含不允许的语法")


def evaluate_safe_expression(
    expression: str,
    *,
    max_length: int,
    max_abs_value: float,
) -> float:
    """使用 AST 白名单解析数学表达式，不使用 eval。"""
    normalized_expression = expression.strip()
    if not normalized_expression:
        raise ValueError("表达式不能为空")

    if len(normalized_expression) > max_length:
        raise ValueError("表达式过长")

    try:
        tree = ast.parse(normalized_expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("表达式语法不正确") from exc

    return _eval_ast_node(tree.body, max_abs_value=max_abs_value)


def build_basic_ops_calculator_tool(settings: Settings) -> BaseTool:
    """构造结构化四则运算 calculator tool。"""

    async def calculate(
        operation: CalculatorOperation,
        left: float,
        right: float,
    ) -> str:
        result = calculate_basic_ops(
            operation=operation,
            left=left,
            right=right,
        )
        _ensure_result_in_range(result, settings.calculator_max_abs_value)
        return str(result)

    return StructuredTool.from_function(
        coroutine=calculate,
        name=CALCULATOR_TOOL_NAME,
        description="执行安全的基础四则运算。",
        args_schema=CalculatorBasicOpsInput,
    )


def build_safe_expression_calculator_tool(settings: Settings) -> BaseTool:
    """构造安全表达式 calculator tool。"""

    async def calculate(expression: str) -> str:
        result = evaluate_safe_expression(
            expression=expression,
            max_length=settings.calculator_max_expression_length,
            max_abs_value=settings.calculator_max_abs_value,
        )
        return str(result)

    return StructuredTool.from_function(
        coroutine=calculate,
        name=CALCULATOR_TOOL_NAME,
        description="解析并计算安全的数学表达式，只支持数字、括号和四则运算符。",
        args_schema=CalculatorExpressionInput,
    )


def build_calculator_tool(settings: Settings) -> BaseTool:
    """根据 Settings.calculator_mode 构造唯一对外暴露的 calculator tool。"""
    mode = settings.calculator_mode.lower().strip()

    if mode == "basic_ops":
        return build_basic_ops_calculator_tool(settings)

    if mode == "safe_expression":
        return build_safe_expression_calculator_tool(settings)

    raise ValueError(f"不支持的 CALCULATOR_MODE: {settings.calculator_mode}")


__all__ = [
    "CALCULATOR_TOOL_NAME",
    "CalculatorBasicOpsInput",
    "CalculatorExpressionInput",
    "CalculatorMode",
    "CalculatorOperation",
    "build_basic_ops_calculator_tool",
    "build_calculator_tool",
    "build_safe_expression_calculator_tool",
    "calculate_basic_ops",
    "evaluate_safe_expression",
]
