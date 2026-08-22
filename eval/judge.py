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

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from eval.catalog import DIFFICULTY_ORDER
from eval.metrics import enrich, load_run
from eval.validation import validate_result_files

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


def select_human_sample(
    records: list[dict[str, Any]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Muestra determinística del sistema final para juez y humano.

    Toma un repeat=0 de cada escenario y completa con los fallos de mayor
    horizonte. Si no hay suficientes fallos, usa los casos restantes de
    mayor cantidad de tool calls.
    """
    if limit < 1:
        raise ValueError("limit debe ser >= 1.")
    baseline = [r for r in records if r.get("config") == "baseline"]
    order = {name: i for i, name in enumerate(DIFFICULTY_ORDER)}
    ranked = sorted(
        baseline,
        key=lambda r: (
            order.get(r.get("difficulty"), 99),
            str(r.get("scenario")),
            int(r.get("repeat", 0)),
        ),
    )

    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for record in ranked:
        key = (str(record["scenario"]), int(record.get("repeat", 0)))
        if record.get("repeat", 0) == 0 and key not in seen:
            selected.append(record)
            seen.add(key)
        if len(selected) >= limit:
            return selected[:limit]

    remaining = [
        r
        for r in baseline
        if (str(r["scenario"]), int(r.get("repeat", 0))) not in seen
    ]
    remaining.sort(
        key=lambda r: (
            bool(r.get("goal_achieved")),
            -(r.get("n_tool_calls") or 0),
            str(r.get("scenario")),
            int(r.get("repeat", 0)),
        )
    )
    selected.extend(remaining[: max(0, limit - len(selected))])
    return selected[:limit]


def _load_records(paths: list[Path]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation = validate_result_files(paths)
    records: list[dict[str, Any]] = []
    for path in paths:
        _, file_records = load_run(path)
        records.extend(file_records)
    return validation, enrich(records)


def _score_payload(
    validation: dict[str, Any],
    sample: list[dict[str, Any]],
    judge_agent: Any,
) -> dict[str, Any]:
    scores = []
    for index, record in enumerate(sample, 1):
        print(
            f"[{index}/{len(sample)}] judge {record['scenario']}#{record.get('repeat', 0)}",
            file=sys.stderr,
        )
        score = judge_record(record, judge_agent)
        scores.append(
            {
                "scenario": record["scenario"],
                "difficulty": record["difficulty"],
                "config": record["config"],
                "repeat": record.get("repeat", 0),
                "goal_achieved": record["goal_achieved"],
                **score,
            }
        )
    return {
        "_meta": {
            "provider": validation.get("provider"),
            "model": validation.get("model"),
            "git_sha": validation.get("git_sha"),
            "sample_policy": "baseline repeat=0 por escenario + fallos más largos",
            "n": len(scores),
        },
        "scores": scores,
    }


def _human_template(
    validation: dict[str, Any],
    sample: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "_meta": {
            "provider": validation.get("provider"),
            "model": validation.get("model"),
            "git_sha": validation.get("git_sha"),
            "instructions": "Completar exploracion, uso_evidencia y recuperacion con enteros 1-5.",
            "n": len(sample),
        },
        "scores": [
            {
                "scenario": record["scenario"],
                "difficulty": record["difficulty"],
                "config": record["config"],
                "repeat": record.get("repeat", 0),
                "goal_achieved": record["goal_achieved"],
                "exploracion": None,
                "uso_evidencia": None,
                "recuperacion": None,
                "justificacion_humana": "",
                "trace": format_trace(record),
                "answer": (record.get("answer") or "")[:600],
            }
            for record in sample
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _compare_files(judge_path: Path, human_path: Path) -> dict[str, Any]:
    judged_payload = _read_json(judge_path)
    human_payload = _read_json(human_path)
    judged = judged_payload.get("scores") or []
    human_scores = human_payload.get("scores") or []
    if any(row.get(axis) is None for row in human_scores for axis in AXES):
        raise SystemExit("La plantilla humana todavía contiene scores nulos.")
    human = {
        f"{row['scenario']}#{row.get('repeat', 0)}": {
            axis: int(row[axis]) for axis in AXES
        }
        for row in human_scores
    }
    agreement = compare_with_human(judged, human)
    return {
        "_meta": {
            "judge_scores": str(judge_path),
            "human_scores": str(human_path),
            "n": len(human_scores),
        },
        "agreement": agreement,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.judge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    score_parser = subparsers.add_parser("score", help="Puntuar muestra y exportar plantilla humana.")
    score_parser.add_argument("results", nargs="+", type=Path)
    score_parser.add_argument("--limit", type=int, default=10)
    score_parser.add_argument("--out", required=True, type=Path)
    score_parser.add_argument("--human-template", required=True, type=Path)

    compare_parser = subparsers.add_parser("compare", help="Calcular acuerdo juez-humano.")
    compare_parser.add_argument("--judge", required=True, type=Path)
    compare_parser.add_argument("--human", required=True, type=Path)
    compare_parser.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "score":
        validation, records = _load_records(args.results)
        sample = select_human_sample(records, args.limit)
        if len(sample) < args.limit:
            raise SystemExit(
                f"Solo hay {len(sample)} casos baseline para una muestra de {args.limit}."
            )
        payload = _score_payload(validation, sample, build_judge())
        _write_json(args.out, payload)
        _write_json(args.human_template, _human_template(validation, sample))
        errors = [row for row in payload["scores"] if row.get("judge_error")]
        if errors:
            print(f"# {len(errors)} scores del judge fallaron; revisar {args.out}.", file=sys.stderr)
            return 1
        return 0

    payload = _compare_files(args.judge, args.human)
    _write_json(args.out, payload)
    print(json.dumps(payload["agreement"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
