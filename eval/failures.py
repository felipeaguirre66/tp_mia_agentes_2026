"""Clasificación de modos de fallo.

El enunciado pide categorizar los fallos, no reportar un número. Buena parte
se puede etiquetar mecánicamente leyendo la traza; lo que no, queda como
`unclassified` para revisión manual (y que aparezca mucho es una señal de que
falta una categoría, no de que el agente sea inescrutable).

Un caso puede disparar varias etiquetas: `labels` las lista todas y
`primary_failure` elige una según `PRIORITY`, para que la tabla del informe
sume 100%. La prioridad va de la causa más "estructural" (el caso ni siquiera
llegó a jugar) a la más "de razonamiento" (jugó y se equivocó).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

#: Regex de una tool call emitida como TEXTO en vez de como tool_call
#: estructurada. Es el fallo que corta el bucle antes de tiempo: el agente
#: ve `tool_calls == []` y lo interpreta como respuesta final.
TEXTUAL_TOOL_CALL = re.compile(
    r'\{\s*"(?:name|tool|tool_name|function)"\s*:\s*"(look|examine|take|use|go)"',
    re.IGNORECASE,
)

#: `no_tool_calls` va casi al final a propósito: es una OBSERVACIÓN
#: estructural ("no invocó herramientas"), no un diagnóstico. Cuando el
#: agente emitió la acción como texto, o cerró en prosa declarando el
#: final, esas etiquetas explican *por qué* la traza quedó vacía y son las
#: que deben aparecer en la tabla. `no_tool_calls` solo gana cuando nada
#: más explica el caso (p. ej. respuesta vacía).
PRIORITY = [
    "crash",
    "budget_timeout",
    "budget_tool_calls",
    "max_iterations",
    "text_tool_call",
    "bad_tool_args",
    "hallucinated_id",
    "not_visible",
    "loop",
    "no_exploration",
    "navigation_lost",
    "wrong_order",
    "premature_stop",
    "no_tool_calls",
    "unclassified",
]

DESCRIPTIONS = {
    "crash": "Excepción no controlada (proveedor o tool).",
    "budget_timeout": "Se agotó el presupuesto de wall-clock.",
    "budget_tool_calls": "Se agotó el presupuesto de tool calls.",
    "max_iterations": "El bucle del agente alcanzó max_iterations.",
    "no_tool_calls": "El agente no invocó ninguna herramienta.",
    "text_tool_call": "Emitió una tool call como texto; el bucle la tomó por respuesta final.",
    "bad_tool_args": "Invocó una tool con argumentos que no matchean la firma.",
    "hallucinated_id": "Actuó sobre un id de objeto que no existe en el mundo.",
    "not_visible": "Actuó sobre un objeto existente pero no visible desde donde estaba.",
    "loop": "Repitió la misma llamada con los mismos argumentos 3+ veces.",
    "no_exploration": "Intentó `use`/`take` sin haber explorado antes.",
    "navigation_lost": "Falló al navegar: dirección inexistente o salida bloqueada.",
    "wrong_order": "Violó el orden del goal compuesto (abrió la puerta antes de tiempo).",
    "premature_stop": "Cerró con texto declarando el final sin haber cumplido el goal.",
    "unclassified": "Fallo sin categoría automática: requiere revisión manual.",
}


def _args_key(event: dict[str, Any]) -> str:
    return f"{event['tool']}::{json.dumps(event.get('args', {}), sort_keys=True)}"


def classify(record: dict[str, Any]) -> dict[str, Any]:
    """Devuelve `{labels, primary_failure, evidence}` para un registro."""
    labels: list[str] = []
    evidence: dict[str, Any] = {}

    if record["goal_achieved"]:
        return {"labels": [], "primary_failure": None, "evidence": {}}

    status = record.get("status", "ok")
    trace = record.get("trace") or []
    answer = record.get("answer") or ""

    # --- el caso ni siquiera llegó a jugar ---------------------------------
    if status == "crash":
        labels.append("crash")
        evidence["error"] = record.get("error")
    if status == "budget_timeout":
        labels.append("budget_timeout")
    if status == "budget_tool_calls":
        labels.append("budget_tool_calls")
    if record.get("agent_error"):
        labels.append("max_iterations")
    if not trace:
        labels.append("no_tool_calls")

    # --- disciplina de tool calling ----------------------------------------
    textual = [t for t in (record.get("textual_responses") or []) if TEXTUAL_TOOL_CALL.search(t)]
    if TEXTUAL_TOOL_CALL.search(answer) or textual:
        labels.append("text_tool_call")
        evidence["textual_tool_call"] = (textual or [answer])[0][:300]

    for ev in trace:
        exc = ev.get("exception") or ""
        if "TypeError" in exc and "keyword argument" in exc:
            labels.append("bad_tool_args")
            evidence.setdefault("bad_tool_args", exc)
            break

    for ev in trace:
        out = ev.get("output") or ""
        if "no existe ningún objeto con id" in out:
            labels.append("hallucinated_id")
            evidence.setdefault("hallucinated_id", ev.get("args"))
            break

    for ev in trace:
        out = ev.get("output") or ""
        if "no ves ningún" in out or "no es visible o accesible" in out:
            labels.append("not_visible")
            evidence.setdefault("not_visible", ev.get("args"))
            break

    # --- patrones de razonamiento ------------------------------------------
    repeats = Counter(_args_key(ev) for ev in trace)
    looped = [k for k, n in repeats.items() if n >= 3]
    if looped:
        labels.append("loop")
        evidence["loop"] = {k: repeats[k] for k in looped[:3]}

    if trace:
        explored = False
        for ev in trace:
            if ev["tool"] in ("look", "examine"):
                explored = True
            if ev["tool"] in ("use", "take") and not explored:
                labels.append("no_exploration")
                break

    for ev in trace:
        if ev["tool"] == "go" and ev.get("is_error"):
            labels.append("navigation_lost")
            evidence.setdefault("navigation_lost", ev.get("output", "")[:200])
            break

    # --- goal compuesto y ordenado (office-sequence) -----------------------
    log = (record.get("final_state") or {}).get("event_log") or []
    goal = record.get("goal") or {}
    if goal.get("type") == "sequence":
        opens = [i for i, e in enumerate(log) if e.startswith("open:puerta")]
        takes = [i for i, e in enumerate(log) if e.startswith("take:documento")]
        if opens and (not takes or takes[0] > opens[0]):
            labels.append("wrong_order")
            evidence["event_log"] = log

    # --- cierre prematuro ---------------------------------------------------
    if status == "ok" and not record.get("agent_error") and answer and "text_tool_call" not in labels:
        labels.append("premature_stop")
        evidence.setdefault("answer", answer[:300])

    if not labels:
        labels.append("unclassified")

    ordered = [lbl for lbl in PRIORITY if lbl in labels]
    return {
        "labels": ordered,
        "primary_failure": ordered[0] if ordered else None,
        "evidence": evidence,
    }
