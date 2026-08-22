#!/usr/bin/env python3
"""Genera el informe resumen a partir de uno o varios JSONL de corrida.

    python eval/report.py results/run-*.jsonl
    python eval/report.py results/run-*.jsonl --judge      # + rúbrica LLM
    python eval/report.py results/run-*.jsonl -o reports/m3.md

Separado de `run.py` a propósito: el análisis se re-corre cuantas veces
quieras sobre resultados ya pagados, sin volver a gastar en el LLM.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.catalog import DIFFICULTY_ORDER, OPTIMAL_CALLS  # noqa: E402
from eval.failures import DESCRIPTIONS  # noqa: E402
from eval.metrics import (  # noqa: E402
    compare_configs,
    enrich,
    failure_breakdown,
    group_by,
    label_frequency,
    load_run,
    summarize,
)
from eval.validation import ResultValidationError, validate_result_files  # noqa: E402

REPORTS_DIR = REPO_ROOT / "reports"


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        out.append("| " + " | ".join(_fmt(c) for c in row) + " |")
    return "\n".join(out)


SUMMARY_COLS = [
    ("n", "n"),
    ("pass_at_1", "pass@1"),
    ("pass_at_k", "pass@k"),
    ("action_efficiency", "eficiencia"),
    ("median_excess_tool_calls", "overhead calls"),
    ("tool_error_rate", "err. tools"),
    ("median_tool_calls", "calls (mediana)"),
    ("median_latency_s", "latencia s"),
]


def _summary_rows(
    groups: dict[str, list[dict[str, Any]]],
    order: list[str] | None = None,
    columns: list[tuple[str, str]] | None = None,
) -> list[list[Any]]:
    columns = columns or SUMMARY_COLS
    keys = order or sorted(groups)
    rows = []
    for key in keys:
        if key not in groups:
            continue
        s = summarize(groups[key])
        rows.append([key] + [s.get(col) for col, _ in columns])
    return rows


class DryRunReportError(SystemExit):
    """Se intentó informar sobre resultados producidos por un LLM falso."""


def build_report(
    paths: list[Path],
    judge: bool = False,
    judge_limit: int = 12,
    allow_dry_run: bool = False,
    judge_scores_path: Path | None = None,
    judge_agreement_path: Path | None = None,
) -> str:
    all_records: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    for path in paths:
        meta, records = load_run(path)
        meta["_path"] = str(path)
        metas.append(meta)
        all_records.extend(records)

    records = enrich(all_records)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts: list[str] = [
        "# Informe de evaluación — M3",
        "",
        f"Generado: {stamp}",
        "",
        "## Corridas incluidas",
        "",
        _table(
            ["archivo", "modelo", "proveedor", "git", "casos", "dry-run"],
            [
                [
                    Path(m.get("_path", "?")).name,
                    m.get("model"),
                    m.get("provider"),
                    m.get("git_sha"),
                    len(m.get("scenarios") or []) * m.get("repeats", 1) * len(m.get("configs") or {}),
                    m.get("dry_run"),
                ]
                for m in metas
            ],
        ),
        "",
    ]

    dry = [m for m in metas if m.get("dry_run")]
    if dry and not allow_dry_run:
        culpables = ", ".join(Path(m["_path"]).name for m in dry)
        raise DryRunReportError(
            f"\nESTOS ARCHIVOS SON CORRIDAS --dry-run (LLM falso): {culpables}\n"
            "Sus números describen al mock, no al agente: un informe hecho con\n"
            "ellos sería ficción, y se ve exactamente igual que uno real.\n\n"
            "Corré la evaluación de verdad:\n"
            "    python eval/run.py --scenarios all --repeats 3\n\n"
            "Si de verdad querés inspeccionar la salida del mock, repetí con "
            "--allow-dry-run.\n"
        )

    if dry:
        parts += [
            "> ⚠️ Alguna corrida es `--dry-run` (LLM falso). Sus números no",
            "> describen al agente: sirven solo para validar la infraestructura.",
            "",
        ]

    try:
        validation = validate_result_files(paths, allow_dry_run=allow_dry_run)
    except ResultValidationError as exc:
        raise SystemExit(f"Resultados inválidos: {exc}") from exc

    repeats = {m.get("repeats") for m in metas}
    repeat_count = next(iter(repeats)) if len(repeats) == 1 else None
    summary_cols = [
        (
            key,
            (
                "escenario resuelto"
                if key == "pass_at_k" and repeat_count == 1
                else f"pass@{repeat_count}"
                if key == "pass_at_k" and repeat_count is not None
                else label
            ),
        )
        for key, label in SUMMARY_COLS
    ]

    # --- resultados globales -------------------------------------------
    headers = ["grupo"] + [label for _, label in summary_cols]
    parts += [
        "## Resultados",
        "",
        "### Global",
        "",
        f"Cohorte validada: **{validation['n_cases']} casos**, "
        f"modelo **{validation.get('model')}**, git **{validation.get('git_sha')}**.",
        "",
        _table(headers, _summary_rows({"todo": records}, columns=summary_cols)),
        "",
        "### Por dificultad",
        "",
        _table(
            headers,
            _summary_rows(
                group_by(records, "difficulty"), DIFFICULTY_ORDER, summary_cols
            ),
        ),
        "",
        "### Por configuración",
        "",
        _table(headers, _summary_rows(group_by(records, "config"), columns=summary_cols)),
        "",
        "### Por escenario",
        "",
    ]

    scenario_groups = group_by(records, "scenario")
    scenario_rows = []
    for scenario, group in sorted(
        scenario_groups.items(),
        key=lambda kv: (
            DIFFICULTY_ORDER.index(kv[1][0]["difficulty"])
            if kv[1][0]["difficulty"] in DIFFICULTY_ORDER
            else 99,
            kv[0],
        ),
    ):
        s = summarize(group)
        scenario_rows.append(
            [
                scenario,
                group[0]["difficulty"],
                OPTIMAL_CALLS.get(scenario),
                s["n"],
                s["pass_at_1"],
                s["pass_at_k"],
                s["action_efficiency"],
                s["median_excess_tool_calls"],
                s["tool_error_rate"],
                s["median_tool_calls"],
            ]
        )
    parts += [
        _table(
            [
                "escenario",
                "dif.",
                "óptimo",
                "n",
                "pass@1",
                "pass@k",
                "eficiencia",
                "overhead calls",
                "err. tools",
                "calls (mediana)",
            ],
            scenario_rows,
        ),
        "",
    ]

    # --- experimentos con cohortes emparejadas ------------------------
    experiment_names = {
        "prompt_baseline": "A — prompt genérico",
        "mem_6": "B — memoria 6",
        "mem_20": "B — memoria 20",
        "noop_examine": "C — examine no-op",
        "iters_10": "C — 10 iteraciones",
        "iters_20": "C — 20 iteraciones",
        "repair_off": "D — reparación OFF",
    }
    comparisons = []
    present_configs = {str(r.get("config")) for r in records}
    if "baseline" in present_configs:
        for treatment, label in experiment_names.items():
            if treatment not in present_configs:
                continue
            comparison = compare_configs(records, "baseline", treatment)
            base = comparison["control_summary"]
            arm = comparison["treatment_summary"]
            delta = comparison["delta"]
            comparisons.append(
                [
                    label,
                    ", ".join(comparison["scenarios"]),
                    base["pass_at_1"],
                    arm["pass_at_1"],
                    None if delta["pass_at_1"] is None else 100 * delta["pass_at_1"],
                    base["pass_at_k"],
                    arm["pass_at_k"],
                    base["action_efficiency"],
                    arm["action_efficiency"],
                    delta["median_tool_calls"],
                ]
            )
    if comparisons:
        parts += [
            "## Comparación de experimentos",
            "",
            "Cada brazo se compara con `baseline` sobre la intersección exacta "
            "de escenarios; el delta de pass@1 está en puntos porcentuales.",
            "",
            _table(
                [
                    "brazo",
                    "cohorte",
                    "base pass@1",
                    "brazo pass@1",
                    "Δ pp",
                    "base pass@k",
                    "brazo pass@k",
                    "base efic.",
                    "brazo efic.",
                    "Δ calls",
                ],
                comparisons,
            ),
            "",
            "> El óptimo es un lower bound de oráculo. `overhead calls` hace "
            "visible el costo de exploración (por ejemplo, el `look` inicial) "
            "sin modificar los óptimos oficiales del enunciado.",
            "",
            "> Con tres repeticiones por brazo, los deltas son evidencia "
            "direccional y no significancia estadística.",
            "",
        ]

    # --- análisis de errores --------------------------------------------
    failed = [r for r in records if not r["goal_achieved"]]
    primary = failure_breakdown(failed)
    parts += [
        "## Análisis de errores",
        "",
        f"Casos fallidos: **{len(failed)}** de {len(records)}.",
        "",
        "### Modo de fallo principal",
        "",
        _table(
            ["modo", "casos", "%", "descripción"],
            [
                [k, v, round(100 * v / len(failed), 1) if failed else 0, DESCRIPTIONS.get(k, "")]
                for k, v in primary.items()
            ],
        ),
        "",
        "### Todas las etiquetas (un caso puede tener varias)",
        "",
        _table(["etiqueta", "apariciones"], [[k, v] for k, v in label_frequency(failed).items()]),
        "",
        "### Modo principal × dificultad",
        "",
    ]

    diff_groups = group_by(failed, "difficulty")
    modes = list(primary)
    rows = []
    for difficulty in DIFFICULTY_ORDER:
        if difficulty not in diff_groups:
            continue
        counts = failure_breakdown(diff_groups[difficulty])
        rows.append([difficulty] + [counts.get(m, 0) for m in modes])
    parts += [_table(["dificultad"] + modes, rows), ""]

    # --- rúbrica ---------------------------------------------------------
    if judge:
        from eval.judge import AXES, build_judge, judge_record

        judge_agent = build_judge()
        sample = records[:judge_limit]
        print(f"# juzgando {len(sample)} trazas…", file=sys.stderr)
        scored = []
        for rec in sample:
            result = judge_record(rec, judge_agent)
            rec.update(result)
            scored.append(rec)
        ok = [r for r in scored if r.get("judge_error") is None]
        parts += [
            "## Dimensión cualitativa (LLM-as-judge)",
            "",
            f"Trazas puntuadas: {len(ok)}/{len(sample)} "
            f"({len(sample) - len(ok)} fallaron en el juez).",
            "",
            _table(
                ["escenario", "rep", "goal", *AXES, "justificación"],
                [
                    [
                        r["scenario"],
                        r.get("repeat"),
                        r["goal_achieved"],
                        *[r.get(a) for a in AXES],
                        (r.get("justificacion") or "")[:120],
                    ]
                    for r in ok
                ],
            ),
            "",
            "> ⚠️ Estos scores **no están validados**. Puntuá 8–10 trazas a mano",
            "> y pasalas por `eval.judge.compare_with_human` antes de citarlos.",
            "",
        ]

    if judge_scores_path is not None:
        payload = json.loads(judge_scores_path.read_text(encoding="utf-8"))
        scores = payload.get("scores") or []
        ok = [row for row in scores if not row.get("judge_error")]
        parts += [
            "## Dimensión cualitativa (artefacto persistido)",
            "",
            f"Scores válidos: **{len(ok)}/{len(scores)}**. Fuente: "
            f"`{judge_scores_path}`.",
            "",
            _table(
                ["escenario", "rep", "goal", "exploración", "evidencia", "recuperación", "justificación"],
                [
                    [
                        row["scenario"],
                        row.get("repeat"),
                        row.get("goal_achieved"),
                        row.get("exploracion"),
                        row.get("uso_evidencia"),
                        row.get("recuperacion"),
                        (row.get("justificacion") or "")[:120],
                    ]
                    for row in ok
                ],
            ),
            "",
        ]

    if judge_agreement_path is not None:
        payload = json.loads(judge_agreement_path.read_text(encoding="utf-8"))
        agreement = payload.get("agreement") or {}
        parts += [
            "### Acuerdo juez-humano",
            "",
            _table(
                ["eje", "n", "acuerdo exacto", "acuerdo ±1", "diferencia abs. media"],
                [
                    [
                        axis,
                        values.get("n"),
                        values.get("exact_agreement"),
                        values.get("within_1"),
                        values.get("mean_abs_diff"),
                    ]
                    for axis, values in agreement.items()
                ],
            ),
            "",
        ]

    # --- compliance de M2 -------------------------------------------------
    max_msgs = max((r.get("max_messages_per_call") or 0) for r in records)
    budgets = {r["agent_config"].get("max_history_messages") for r in records}
    repaired = summarize(records).get("repaired_tool_calls", 0)
    parts += [
        "## Chequeos de invariantes",
        "",
        f"- Máximo de mensajes en una sola llamada al LLM: **{max_msgs}** "
        f"(presupuestos configurados: {sorted(b for b in budgets if b)}). "
        "Debe ser `<=` al presupuesto en todos los casos.",
        f"- Tool calls recuperadas de texto (experimento D): **{repaired}**. "
        "En los brazos con reparación apagada debe ser 0.",
        "",
    ]

    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval/report.py")
    parser.add_argument("results", nargs="+", help="JSONL de corridas.")
    parser.add_argument("-o", "--out", default=None, help="Markdown de salida.")
    parser.add_argument("--judge", action="store_true", help="Correr el LLM-as-judge (gasta tokens).")
    parser.add_argument("--judge-limit", type=int, default=12, help="Cuántas trazas puntuar.")
    parser.add_argument(
        "--judge-scores",
        type=Path,
        default=None,
        help="JSON persistido por `python -m eval.judge score`.",
    )
    parser.add_argument(
        "--judge-agreement",
        type=Path,
        default=None,
        help="JSON persistido por `python -m eval.judge compare`.",
    )
    parser.add_argument(
        "--allow-dry-run",
        action="store_true",
        help="Permite informar sobre corridas con LLM falso (solo para inspeccionar la infra).",
    )
    args = parser.parse_args(argv)

    paths = [Path(p) for p in args.results]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise SystemExit(f"No existen: {', '.join(str(m) for m in missing)}")

    report = build_report(
        paths,
        judge=args.judge,
        judge_limit=args.judge_limit,
        allow_dry_run=args.allow_dry_run,
        judge_scores_path=args.judge_scores,
        judge_agreement_path=args.judge_agreement,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else REPORTS_DIR / f"report-{stamp}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"# -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
