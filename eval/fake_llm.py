"""Clientes LLM falsos para validar la infraestructura sin gastar tokens.

`--dry-run` en `eval/run.py` usa `LookOnceLLM`: funciona con cualquier
escenario, ejercita el camino completo (tool call -> traza -> mensaje
`role: "tool"` -> respuesta final) y no requiere proveedor configurado.
`ScriptedLLM` reproduce una secuencia fija de acciones y es lo que usa el
test del harness para comprobar que un caso ganador se reporta como tal.
"""

from __future__ import annotations

import json
from typing import Any

from mia_agents.types import LLMResponse, ToolCall, ToolSchema

ToolSpecInput = ToolSchema | dict[str, Any]


class _RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _record(self, messages: list[dict[str, Any]], tools: Any, system: Any) -> None:
        self.calls.append({"messages": messages, "tools": tools, "system": system})

    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def max_messages_seen(self) -> int:
        return max((len(c["messages"]) for c in self.calls), default=0)


class LookOnceLLM(_RecordingLLM):
    """Llama `look` una vez y después cierra con texto.

    Sirve de prueba de humo agnóstica del escenario: nunca resuelve nada,
    pero recorre el circuito completo del harness.
    """

    def __init__(self, answer: str = "No logré salir.") -> None:
        super().__init__()
        self._answer = answer
        self._used = False

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpecInput] | None = None,
        system: str | None = None,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self._record(messages, tools, system)
        if not self._used:
            self._used = True
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="c0", name="look", arguments="{}")],
                input_tokens=10,
                output_tokens=5,
            )
        return LLMResponse(content=self._answer, input_tokens=10, output_tokens=5)


class ScriptedLLM(_RecordingLLM):
    """Reproduce una secuencia fija de ``(tool, args)`` y luego cierra.

    Ejemplo::

        ScriptedLLM([
            ("examine", {"target": "alfombra"}),
            ("take", {"item": "llave_oro"}),
            ("use", {"item": "llave_oro", "target": "puerta_principal"}),
        ])
    """

    def __init__(
        self,
        script: list[tuple[str, dict[str, Any]]],
        answer: str = "Listo.",
    ) -> None:
        super().__init__()
        self._script = list(script)
        self._answer = answer
        self._i = 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpecInput] | None = None,
        system: str | None = None,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self._record(messages, tools, system)
        if self._i >= len(self._script):
            return LLMResponse(content=self._answer, input_tokens=10, output_tokens=5)
        name, args = self._script[self._i]
        self._i += 1
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id=f"c{self._i}", name=name, arguments=json.dumps(args))],
            input_tokens=10,
            output_tokens=5,
        )


#: Secuencias óptimas conocidas, para tests de la infraestructura.
WINNING_SCRIPTS: dict[str, list[tuple[str, dict[str, Any]]]] = {
    "study-with-key": [
        ("examine", {"target": "alfombra"}),
        ("take", {"item": "llave_oro"}),
        ("use", {"item": "llave_oro", "target": "puerta_principal"}),
    ],
}
