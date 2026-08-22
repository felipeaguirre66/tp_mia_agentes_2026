"""Dimensión cualitativa: rúbrica evaluada por LLM-as-judge.

Por qué hace falta algo cualitativo: dos casos con `goal_achieved=False`
pueden ser radicalmente distintos — uno quedó a una acción del éxito, el
otro repitió `look` veinte veces. La métrica binaria los iguala. La rúbrica
puntúa el **proceso**, no el resultado.

Tres ejes, 1–5, elegidos porque cada uno aísla una capacidad distinta del
agente y los tres son legibles desde la traza sin conocer la solución:

1. `exploracion`   — ¿observa antes de actuar y examina de forma sistemática?
2. `uso_evidencia` — ¿actúa sobre lo que las tools le informaron, o inventa?
3. `recuperacion`  — tras un error, ¿corrige o insiste con lo mismo?

Implementación: reusa `structured_call` de M2 (herramienta sintética
`final_result` + reparación). El juez no es infraestructura nueva; es M2
aplicado a un problema de evaluación.

**Validación obligatoria**: un score de LLM-as-judge sin acuerdo medido
contra humano no vale nada. `compare_with_human()` computa ese acuerdo;
puntuá 8–10 trazas a mano y reportá el resultado en el informe.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

MAX_TRACE_EVENTS = 40
MAX_OUTPUT_CHARS = 300


class RubricScore(BaseModel):
    """Puntuación de la calidad del proceso del agente."""

    exploracion: int = Field(ge=1, le=5, description="1-5: ¿observó antes de actuar y exploró de forma sistemática?")
    uso_evidencia: int = Field(ge=1, le=5, description="1-5: ¿actuó sobre ids y hechos que las herramientas realmente reportaron?")
    recuperacion: int = Field(ge=1, le=5, description="1-5: tras un error de herramienta, ¿corrigió el rumbo o insistió?")
    justificacion: str = Field(description="Dos o tres frases citando pasos concretos de la traza.")


RUBRIC_PROMPT = """\
Sos un evaluador de agentes. Te doy la traza de un agente resolviendo una sala
de escape por texto. Puntuá la CALIDAD DEL PROCESO en tres ejes, de 1 a 5.
No puntúes si ganó o perdió: eso ya se mide aparte. Un agente puede fallar con
un proceso excelente (el puzzle era largo) o acertar con un proceso pésimo
(probó al azar y tuvo suerte).

Ejes:
- exploracion (1-5): 1 = actuó a ciegas sin mirar; 5 = observó primero y
  examinó de forma sistemática, sin repetir ni saltear.
- uso_evidencia (1-5): 1 = inventó ids u objetos que nadie le mostró;
  5 = todas sus acciones referencian cosas que las herramientas reportaron.
- recuperacion (1-5): 1 = repitió la misma llamada fallida una y otra vez;
  5 = leyó cada error y ajustó los argumentos o la estrategia.

Escenario: {scenario} (dificultad: {difficulty})
Objetivo alcanzado: {achieved}
Motivo del veredicto: {reason}

Traza de herramientas ({n_calls} llamadas):
{trace}

Respuesta final del agente:
{answer}

Invocá `final_result` con los tres enteros y una justificación breve que cite
pasos concretos por su índice.
"""


def format_trace(record: dict[str, Any]) -> str:
    """Traza compacta y truncada, para no volar la ventana del juez."""
    lines = []
    trace = record.get("trace") or []
    for ev in trace[:MAX_TRACE_EVENTS]:
        output = (ev.get("output") or "").replace("\n", " ")
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "…"
        flag = " [ERROR]" if ev.get("is_error") else ""
        lines.append(f"[{ev['index']}] {ev['tool']}({json.dumps(ev.get('args', {}), ensure_ascii=False)}){flag} -> {output}")
    if len(trace) > MAX_TRACE_EVENTS:
        lines.append(f"… ({len(trace) - MAX_TRACE_EVENTS} llamadas más, truncadas)")
    return "\n".join(lines) or "(el agente no invocó ninguna herramienta)"


def build_prompt(record: dict[str, Any]) -> str:
    return RUBRIC_PROMPT.format(
        scenario=record["scenario"],
        difficulty=record["difficulty"],
        achieved=record["goal_achieved"],
        reason=record.get("goal_reason"),
        n_calls=record.get("n_tool_calls", 0),
        trace=format_trace(record),
        answer=(record.get("answer") or "(sin respuesta)")[:600],
    )


def judge_record(record: dict[str, Any], judge_agent: Any) -> dict[str, Any]:
    """Puntúa un registro. Nunca lanza: un juez caído no rompe el análisis."""
    try:
        score = judge_agent.structured_call(build_prompt(record), RubricScore)
        return {
            "exploracion": score.exploracion,
            "uso_evidencia": score.uso_evidencia,
            "recuperacion": score.recuperacion,
            "justificacion": score.justificacion,
            "judge_error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"judge_error": f"{type(exc).__name__}: {exc}"}


def build_judge(llm_client: Any | None = None) -> Any:
    """Agente juez: modo genérico, sin tools del mundo, prompt neutro."""
    from student_framework import build_agent

    config: dict[str, Any] = {
        "system_prompt": "Sos un evaluador riguroso y conciso de trazas de agentes.",
        "max_history_messages": 20,
    }
    if llm_client is not None:
        config["llm_client"] = llm_client
    return build_agent(config)


AXES = ("exploracion", "uso_evidencia", "recuperacion")


def compare_with_human(
    judged: list[dict[str, Any]],
    human: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Acuerdo juez-humano sobre los casos anotados a mano.

    `human` mapea `"<scenario>#<repeat>"` -> `{eje: score}`. Reporta acuerdo
    exacto y acuerdo ±1 por eje: en una escala de 5 puntos, exigir
    coincidencia exacta entre dos anotadores es una vara irreal, y el ±1 es
    la convención habitual para decir "miden lo mismo".
    """
    per_axis: dict[str, dict[str, Any]] = {}
    for axis in AXES:
        exact = 0
        within_1 = 0
        total = 0
        diffs: list[int] = []
        for rec in judged:
            key = f"{rec['scenario']}#{rec.get('repeat', 0)}"
            if key not in human or axis not in human[key] or rec.get(axis) is None:
                continue
            total += 1
            diff = abs(int(rec[axis]) - int(human[key][axis]))
            diffs.append(diff)
            exact += diff == 0
            within_1 += diff <= 1
        per_axis[axis] = {
            "n": total,
            "exact_agreement": round(exact / total, 3) if total else None,
            "within_1": round(within_1 / total, 3) if total else None,
            "mean_abs_diff": round(sum(diffs) / len(diffs), 3) if diffs else None,
        }
    return per_axis
