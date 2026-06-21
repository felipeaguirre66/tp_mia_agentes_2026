from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from mia_agents.types import ToolSchema


def calculator(
    left_operand: Annotated[float, Field(description="Primer operando numérico.")],
    operator: Annotated[
        Literal["+", "-", "*", "%"],
        Field(description="Operador binario a aplicar: +, -, * o %."),
    ],
    right_operand: Annotated[float, Field(description="Segundo operando numérico.")],
) -> str:
    """Calcula una operación binaria simple entre dos operandos numéricos."""
    if operator == "+":
        return str(left_operand + right_operand)
    if operator == "-":
        return str(left_operand - right_operand)
    if operator == "*":
        return str(left_operand * right_operand)
    return str(left_operand % right_operand)


calculator_schema = ToolSchema.from_callable(calculator)