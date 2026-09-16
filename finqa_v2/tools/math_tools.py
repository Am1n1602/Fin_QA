"""Mathematical tool (§19): calculate -- restricted arithmetic over named variables."""
from __future__ import annotations

from pydantic import BaseModel, Field

from finqa_v2.engine.calculator import calculate


class _Calc(BaseModel):
    expression: str = Field(..., description="arithmetic over the given variables, e.g. '(a - b) / b * 100'")
    variables: dict[str, float] = Field(default_factory=dict)


def register(reg) -> None:
    def _run(m: _Calc):
        result = calculate(m.expression, **m.variables)
        return {"expression": m.expression, "variables": m.variables, "result": result}

    reg.add("calculate",
            "Evaluate a small arithmetic expression over named numeric variables. "
            "Only + - * / // % ** and abs/min/max/round are allowed.",
            _Calc, _run)
