"""Instrumentación del cliente LLM.

`build_agent` construye el cliente por dentro (`LLMClient.from_env()`), así
que el harness no lo ve y no puede medirlo. `CountingLLM` lo envuelve: es un
`LLMClient` transparente que además cuenta llamadas, acumula tokens y —lo
más útil— registra **cuántos mensajes viajaron en cada llamada**, que es la
única forma de verificar empíricamente que el recorte de M2 se respeta bajo
carga real (el contrato dice `<= max_history_messages`, no `==`).
"""

from __future__ import annotations

from typing import Any

from mia_agents.types import LLMResponse, ToolSchema

ToolSpecInput = ToolSchema | dict[str, Any]


class CountingLLM:
    """Decorador transparente sobre cualquier `LLMClient`."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.call_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.messages_per_call: list[int] = []
        #: Respuestas sin `tool_calls`: candidatas a "tool call emitida como
        #: texto", el fallo que corta el bucle antes de tiempo.
        self.textual_responses: list[str] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpecInput] | None = None,
        system: str | None = None,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        self.call_count += 1
        self.messages_per_call.append(len(messages))
        response = self._inner.chat(
            messages=messages,
            tools=tools,
            system=system,
            temperature=temperature,
            response_format=response_format,
        )
        if response.input_tokens:
            self.input_tokens += response.input_tokens
        if response.output_tokens:
            self.output_tokens += response.output_tokens
        if not response.tool_calls and response.content:
            self.textual_responses.append(response.content)
        return response

    def stats(self) -> dict[str, Any]:
        return {
            "n_llm_calls": self.call_count,
            "input_tokens": self.input_tokens or None,
            "output_tokens": self.output_tokens or None,
            "max_messages_per_call": max(self.messages_per_call, default=0),
            "textual_responses": list(self.textual_responses),
        }
