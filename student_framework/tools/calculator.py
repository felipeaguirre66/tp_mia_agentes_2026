from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from mia_agents.types import ToolSchema


def calculator(
    left_operand: 
        Annotated[float, Field(description="Primer operando numérico.")],
    operator: Annotated[
        Literal["+", "-", "*", "%"],
        Field(description="Operador binario a aplicar: +, -, * o %."),
    ],
    right_operand: 
        Annotated[float, Field(description="Segundo operando numérico.")],
) -> str:
    
    """Calcula una operación binaria simple entre dos operandos numéricos."""
    #parsear los operandos a float
    try:
        left = float(left_operand)
    except (TypeError, ValueError):
        return f"Error recuperable: left_operand recibió {left_operand!r}, que no es numérico. Enviá un número."
    try:
        right = float(right_operand)
    except (TypeError, ValueError):
        return f"Error recuperable: right_operand recibió {right_operand!r}, que no es numérico. Enviá un número."
    if operator not in ("+", "-", "*", "%"):
        return f"Error recuperable: operator recibió {operator!r}. Permitidos: +, -, *, %."
    if operator == "%" and right == 0:
        return "Error recuperable: módulo por cero — right_operand debe ser distinto de 0."
    
    if operator == "+":
        return str(left + right)
    if operator == "-":
        return str(left - right)
    if operator == "*":
        return str(left * right)
    return str(left % right)


calculator_schema = ToolSchema.from_callable(calculator)