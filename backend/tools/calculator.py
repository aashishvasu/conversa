"""Model-callable calculator: bounded math expressions and unit conversions."""

import ast
import math

from pydantic import Field, model_validator

from .conversa_tool import ConversaTool, ToolArguments, ToolFailed, ToolOutput
from .units import convert_units

MAX_EXPRESSION_LENGTH = 500
MAX_AST_NODES = 100
MAX_EXPONENT = 1000
# 100! is ~525 bits: large enough to be useful, inside the 4096-bit result bound.
MAX_FACTORIAL = 100
MAX_BIT_LENGTH = 4096

CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
}


def _safe_factorial(n: object) -> int:
    if isinstance(n, bool) or not isinstance(n, int):
        raise ToolFailed("factorial requires an integer argument")
    if not (0 <= n <= MAX_FACTORIAL):
        raise ToolFailed(f"factorial argument must be between 0 and {MAX_FACTORIAL}")
    return math.factorial(n)


def _safe_exp(x: object) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ToolFailed("exp requires a numeric argument")
    if x > 709:
        raise ToolFailed("exp argument causes overflow")
    return math.exp(x)


def _safe_log(x: object, base: object = math.e) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x <= 0:
        raise ToolFailed("log requires a positive argument")
    if isinstance(base, bool) or not isinstance(base, (int, float)) or base <= 0 or base == 1:
        raise ToolFailed("log base must be positive and not 1")
    return math.log(x, base)


def _safe_sqrt(x: object) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0:
        raise ToolFailed("sqrt requires a non-negative argument")
    return math.sqrt(x)


def _safe_round(x: object, ndigits: object = None) -> int | float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ToolFailed("round requires a numeric argument")
    if ndigits is None:
        return round(x)
    if isinstance(ndigits, bool) or not isinstance(ndigits, int) or not (-20 <= ndigits <= 20):
        raise ToolFailed("round digits must be an integer between -20 and 20")
    return round(x, ndigits)


def _safe_pow(a: object, b: object) -> int | float:
    return _safe_binop(a, b, ast.Pow)


MATH_FUNCTIONS = {
    "abs": abs,
    "acos": math.acos,
    "asin": math.asin,
    "atan": math.atan,
    "atan2": math.atan2,
    "ceil": math.ceil,
    "cos": math.cos,
    "degrees": math.degrees,
    "exp": _safe_exp,
    "factorial": _safe_factorial,
    "floor": math.floor,
    "gcd": math.gcd,
    "log": _safe_log,
    "log10": math.log10,
    "log2": math.log2,
    "pow": _safe_pow,
    "radians": math.radians,
    "round": _safe_round,
    "sin": math.sin,
    "sqrt": _safe_sqrt,
    "tan": math.tan,
    "trunc": math.trunc,
}


def _check_result(value: object) -> int | float:
    if isinstance(value, complex):
        raise ToolFailed("complex numbers are not supported")
    if isinstance(value, bool):
        raise ToolFailed("boolean results are not supported")
    if isinstance(value, int):
        if value.bit_length() > MAX_BIT_LENGTH:
            raise ToolFailed(f"integer overflow: result exceeds {MAX_BIT_LENGTH} bits")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolFailed("floating point result is not finite")
        return value
    raise ToolFailed(f"unsupported result type: {type(value).__name__}")


def _safe_binop(left: object, right: object, op_type: type) -> int | float:
    if isinstance(left, bool) or isinstance(right, bool) or not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        raise ToolFailed("operands must be numeric")

    if op_type is ast.Add:
        return _check_result(left + right)
    if op_type is ast.Sub:
        return _check_result(left - right)
    if op_type is ast.Mult:
        return _check_result(left * right)
    if op_type is ast.Div:
        if right == 0:
            raise ToolFailed("division by zero")
        return _check_result(left / right)
    if op_type is ast.FloorDiv:
        if right == 0:
            raise ToolFailed("division by zero")
        return _check_result(left // right)
    if op_type is ast.Mod:
        if right == 0:
            raise ToolFailed("division by zero")
        return _check_result(left % right)
    if op_type is ast.Pow:
        if abs(right) > MAX_EXPONENT:
            raise ToolFailed(f"exponent too large: maximum magnitude is {MAX_EXPONENT}")
        if left == 0 and right < 0:
            raise ToolFailed("division by zero")
        if left < 0 and isinstance(right, float) and not right.is_integer():
            raise ToolFailed("complex numbers are not supported")
        try:
            return _check_result(left ** right)
        except OverflowError as error:
            raise ToolFailed("exponentiation overflow") from error
    raise ToolFailed(f"unsupported binary operator: {op_type.__name__}")


def _eval_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolFailed(f"literal value '{node.value}' is not a permitted numeric constant")
        return _check_result(node.value)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        if isinstance(node.op, ast.UAdd):
            return _check_result(+operand)
        if isinstance(node.op, ast.USub):
            return _check_result(-operand)
        raise ToolFailed(f"unsupported unary operator: {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        return _safe_binop(left, right, type(node.op))
    if isinstance(node, ast.Name):
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise ToolFailed(f"unknown identifier or constant: '{node.id}'")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ToolFailed("only direct named function calls are allowed")
        func_name = node.func.id
        if func_name not in MATH_FUNCTIONS:
            raise ToolFailed(f"unsupported function: '{func_name}'")
        if node.keywords:
            raise ToolFailed("keyword arguments are not permitted")
        args = [_eval_node(arg) for arg in node.args]
        func = MATH_FUNCTIONS[func_name]
        try:
            return _check_result(func(*args))
        except (TypeError, ValueError, OverflowError) as error:
            raise ToolFailed(f"function '{func_name}' evaluation error: {error}") from error
    raise ToolFailed(f"unsupported expression syntax: {type(node).__name__}")


def evaluate_expression(expression: str) -> int | float:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as error:
        raise ToolFailed(f"syntax error in expression: {error.msg}") from error

    node_count = sum(1 for _ in ast.walk(tree))
    if node_count > MAX_AST_NODES:
        raise ToolFailed(f"expression exceeds maximum complexity ({node_count} nodes > {MAX_AST_NODES})")

    return _eval_node(tree)


class CalculatorArguments(ToolArguments):
    expression: str | None = Field(default=None, min_length=1, max_length=MAX_EXPRESSION_LENGTH)
    value: float | int | None = Field(default=None, allow_inf_nan=False)
    from_unit: str | None = Field(default=None, min_length=1, max_length=32)
    to_unit: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_mode(self) -> "CalculatorArguments":
        has_expr = self.expression is not None
        has_conv = self.value is not None or self.from_unit is not None or self.to_unit is not None

        if has_expr and has_conv:
            raise ValueError("provide either 'expression' or ('value', 'from_unit', 'to_unit'), not both")
        if not has_expr and not has_conv:
            raise ValueError("provide either 'expression' or ('value', 'from_unit', 'to_unit')")
        if has_conv:
            if self.value is None or self.from_unit is None or self.to_unit is None:
                raise ValueError("unit conversion requires 'value', 'from_unit', and 'to_unit'")
            if isinstance(self.value, bool):
                raise ValueError("value must be numeric, not boolean")
        return self


async def execute_calculator(arguments: CalculatorArguments) -> ToolOutput:
    if arguments.expression is not None:
        result = evaluate_expression(arguments.expression)
        return ToolOutput({"result": result, "expression": arguments.expression}, {"mode": "expression"})

    conversion = convert_units(arguments.value, arguments.from_unit, arguments.to_unit)
    return ToolOutput(conversion, {"mode": "conversion", "category": conversion["category"]})


CALCULATOR_TOOL = ConversaTool(
    name="calculator",
    description="Evaluate math expressions (+, -, *, /, //, %, **, functions) or convert units across length, mass, duration, data size, speed, area, volume, pressure, energy, and temperature.",
    arguments=CalculatorArguments,
    execute=execute_calculator,
    artifact_fresh_for=None,
)
