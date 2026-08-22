"""Reparación de tool calls emitidas como texto (experimento D).

Modelos chicos con tool-calling frágil (p. ej. `llama3.1:8b`) a veces
escriben la siguiente acción como JSON dentro de `content` en lugar de
emitir un `tool_call` estructurado::

    Parece que `take` no acepta `target`. Intentaré con otro enfoque.
    {"name": "examine", "parameters": {"target": "escritorio"}}

Un bucle ReAct estándar ve `response.tool_calls == []`, concluye que el
modelo terminó y devuelve ese texto como respuesta final. El agente se
detiene justo cuando estaba a punto de corregirse.

Este módulo detecta esos casos y los convierte en `ToolCall`s reales.
Es **conservador a propósito**: solo repara si el objeto JSON nombra una
herramienta *registrada*. Prosa que casualmente contenga llaves, o un
modelo que explique lo que hizo citando un nombre de tool, no disparan
nada — preferimos no reparar antes que inventar una acción que el modelo
no pidió.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from mia_agents.types import ToolCall

#: Claves con las que los modelos suelen nombrar la herramienta y sus args.
_NAME_KEYS = ("name", "tool", "tool_name", "function")
_ARG_KEYS = ("arguments", "parameters", "args", "params", "input")

#: Bloques ```json ... ``` que hay que desenvolver antes de parsear.
_FENCE = re.compile(r"```(?:json|tool_code|python)?\s*(.*?)```", re.DOTALL)


def _candidate_blobs(text: str) -> list[str]:
    """Extrae substrings que parecen objetos JSON, balanceando llaves."""
    blobs: list[str] = []
    for fenced in _FENCE.findall(text):
        blobs.append(fenced.strip())
        text = text.replace(fenced, " ")

    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    blobs.append(text[start : i + 1])
                    start = -1
    return blobs


def _as_dict(blob: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(blob)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_one(obj: dict[str, Any], known: set[str]) -> tuple[str, dict[str, Any]] | None:
    """Devuelve `(nombre, args)` si `obj` describe una tool conocida."""
    # Forma OpenAI anidada: {"function": {"name": ..., "arguments": ...}}
    fn = obj.get("function")
    if isinstance(fn, dict):
        inner = _extract_one(fn, known)
        if inner:
            return inner

    name = None
    for key in _NAME_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and value in known:
            name = value
            break
    if name is None:
        return None

    args: dict[str, Any] = {}
    for key in _ARG_KEYS:
        value = obj.get(key)
        if isinstance(value, dict):
            args = value
            break
        if isinstance(value, str):
            parsed = _as_dict(value)  # arguments a veces viene como string JSON
            if parsed is not None:
                args = parsed
                break
    return name, args


def extract_tool_calls(
    content: str | None,
    known_tools: Iterable[str],
    *,
    id_prefix: str = "repair",
) -> list[ToolCall]:
    """Convierte tool calls textuales de `content` en `ToolCall`s.

    Solo repara herramientas presentes en `known_tools`. Devuelve lista
    vacía si no hay nada reparable — el llamador debe tratar ese caso como
    una respuesta final legítima.
    """
    if not content:
        return []
    known = set(known_tools)
    if not known:
        return []

    calls: list[ToolCall] = []
    for blob in _candidate_blobs(content):
        obj = _as_dict(blob)
        if obj is None:
            continue
        extracted = _extract_one(obj, known)
        if extracted is None:
            continue
        name, args = extracted
        calls.append(
            ToolCall(
                id=f"{id_prefix}-{len(calls)}",
                name=name,
                arguments=json.dumps(args, ensure_ascii=False),
            )
        )
    return calls
