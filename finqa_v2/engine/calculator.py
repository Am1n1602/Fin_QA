"""calculate(expr, **vars) -- restricted arithmetic evaluator for the tool layer.

Allows: numbers, + - * / // % ** , unary +/- , parentheses, names bound in `vars`,
and abs/min/max/round. Everything else raises ValueError. No attribute access, no
comprehensions, no lambdas, no builtins beyond the four named.
"""
from __future__ import annotations

import ast
import operator
from typing import Any

_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "min": min, "max": max, "round": round}


def calculate(expr: str, **vars: Any) -> float:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"cannot parse expression: {e}") from e

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError(f"disallowed constant: {node.value!r}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            return _BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name):
            if node.id in vars:
                v = vars[node.id]
                if v is None:
                    raise ValueError(f"variable {node.id!r} is None")
                return v
            raise ValueError(f"unknown variable: {node.id!r}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                raise ValueError("only abs/min/max/round calls are allowed")
            if node.keywords:
                raise ValueError("keyword arguments are not allowed")
            return _FUNCS[node.func.id](*(ev(a) for a in node.args))
        raise ValueError(f"disallowed syntax: {type(node).__name__}")

    return float(ev(tree))
