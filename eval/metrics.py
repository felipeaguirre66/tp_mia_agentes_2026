"""Métricas cuantitativas sobre los registros de una corrida.

Elección y justificación (sección 2 del informe):

- **Task success rate (`pass@1`)** sobre `check_goal`. Es la métrica
  principal porque se computa sobre el **estado del mundo**: el agente puede
  afirmar que escapó sin haber abierto nada, y esa afirmación no cuenta.
- **`pass@k`**: ¿resolvió el escenario *alguna* vez en k repeticiones? La
  brecha `pass@k − pass@1` mide **inconsistencia**, información que el
  promedio esconde: 1/3 y 3/3 no son el mismo agente aunque compartan media.
- **Eficiencia de acciones** = `optimal / tool_calls`, solo sobre casos
  resueltos. Separa "resolvió" de "resolvió bien": resolver en 30 calls algo
  de óptimo 3 es estar a un `max_iterations` del fracaso.
- **Tool-error rate**: proporción de tool calls que devolvieron error. Proxy
  directo de disciplina de tool-calling. Ojo: las tools del mundo **no
  lanzan**, devuelven strings `"Error: ..."` (ver `eval.tracing`).
- **Coste y latencia**: tokens y segundos. Necesarios para argumentar sobre
  `extreme-archive`, cuyo diseño es justamente no caber en contexto.

Todo se reporta **por dificultad**, no solo agregado: el promedio global
mezcla un `easy` al 100% con un `extreme` al 0% y no describe a ninguno.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Iterable

from eval.failures import classify


def load_run(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Lee un JSONL de corrida: devuelve `(meta, records)`."""
    meta: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "_meta" in obj:
                meta = obj["_meta"]
            else:
                records.append(obj)
    return meta, records


def enrich(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrega campos derivados: eficiencia, overhead y clasificación."""
    out = []
    for r in records:
        r = dict(r)
        optimal = r.get("optimal_calls")
        calls = r.get("n_tool_calls") or 0
        r["action_efficiency"] = (
            (optimal / calls) if (r["goal_achieved"] and optimal and calls) else None
        )
        # El óptimo del enunciado es un lower bound de oráculo: no incluye
        # necesariamente acciones de observación como el `look` inicial que
        # pide ESCAPE_V1. El overhead deja esa diferencia visible sin alterar
        # el óptimo oficial ni fingir que eficiencia=1 es siempre alcanzable.
        r["excess_tool_calls"] = (
            (calls - optimal) if (r["goal_achieved"] and optimal is not None) else None
        )
        r.update(classify(r))
        out.append(r)
    return out


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Métricas agregadas de un conjunto de casos."""
    n = len(records)
    if n == 0:
        return {"n": 0}

    achieved = [r for r in records if r["goal_achieved"]]
    efficiencies = [r["action_efficiency"] for r in achieved if r["action_efficiency"]]
    error_rates = [r["tool_error_rate"] for r in records if r.get("tool_error_rate") is not None]

    # pass@k: por BRAZO + escenario, ¿lo resolvió alguna repetición?
    # Incluir config evita que un éxito de repair_on convierta en éxito al
    # baseline cuando el reporte agrega varios experimentos a la vez.
    by_scenario: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records:
        key = (str(r.get("config")), str(r["scenario"]))
        by_scenario.setdefault(key, []).append(r)
    pass_at_k = _mean([float(any(x["goal_achieved"] for x in v)) for v in by_scenario.values()])

    return {
        "n": n,
        "n_scenarios": len({r["scenario"] for r in records}),
        "n_config_scenarios": len(by_scenario),
        "pass_at_1": round(len(achieved) / n, 3),
        "pass_at_k": pass_at_k,
        "action_efficiency": _mean(efficiencies),
        "median_excess_tool_calls": _median(
            [float(r["excess_tool_calls"]) for r in achieved if r.get("excess_tool_calls") is not None]
        ),
        "tool_error_rate": _mean(error_rates),
        "median_tool_calls": _median([float(r["n_tool_calls"]) for r in records]),
        "median_latency_s": _median([float(r["latency_s"]) for r in records]),
        "mean_input_tokens": _mean([float(r["input_tokens"]) for r in records if r.get("input_tokens")]),
        "mean_output_tokens": _mean([float(r["output_tokens"]) for r in records if r.get("output_tokens")]),
        "max_messages_per_call": max((r.get("max_messages_per_call") or 0) for r in records),
        "repaired_tool_calls": sum((r.get("repaired_tool_calls") or 0) for r in records),
    }


def compare_configs(
    records: list[dict[str, Any]],
    control: str,
    treatment: str,
) -> dict[str, Any]:
    """Compara dos brazos sobre la intersección exacta de escenarios.

    El baseline completo cubre ocho escenarios, mientras que varios brazos
    solo corren medium+hard. Comparar agregados sin emparejar cohortes sesga
    el delta por composición de dificultad.
    """
    control_records = [r for r in records if r.get("config") == control]
    treatment_records = [r for r in records if r.get("config") == treatment]
    control_scenarios = {r["scenario"] for r in control_records}
    treatment_scenarios = {r["scenario"] for r in treatment_records}
    cohort = sorted(control_scenarios & treatment_scenarios)
    if not cohort:
        raise ValueError(
            f"No hay escenarios comparables entre {control!r} y {treatment!r}."
        )

    control_matched = [r for r in control_records if r["scenario"] in cohort]
    treatment_matched = [r for r in treatment_records if r["scenario"] in cohort]
    control_summary = summarize(control_matched)
    treatment_summary = summarize(treatment_matched)

    delta: dict[str, float | None] = {}
    for metric in (
        "pass_at_1",
        "pass_at_k",
        "action_efficiency",
        "tool_error_rate",
        "median_tool_calls",
        "median_excess_tool_calls",
    ):
        before = control_summary.get(metric)
        after = treatment_summary.get(metric)
        delta[metric] = (
            round(float(after) - float(before), 3)
            if before is not None and after is not None
            else None
        )

    return {
        "control": control,
        "treatment": treatment,
        "scenarios": cohort,
        "control_summary": control_summary,
        "treatment_summary": treatment_summary,
        "delta": delta,
    }


def group_by(records: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        groups.setdefault(str(r.get(key)), []).append(r)
    return groups


def failure_breakdown(records: list[dict[str, Any]]) -> dict[str, int]:
    """Cuenta de `primary_failure` sobre los casos NO resueltos."""
    counts: dict[str, int] = {}
    for r in records:
        label = r.get("primary_failure")
        if label:
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def label_frequency(records: list[dict[str, Any]]) -> dict[str, int]:
    """Cuenta de TODAS las etiquetas (un caso puede tener varias)."""
    counts: dict[str, int] = {}
    for r in records:
        for label in r.get("labels") or []:
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
