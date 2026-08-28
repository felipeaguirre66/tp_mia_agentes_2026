#!/usr/bin/env bash
# Corrida completa de M3: baseline + los cuatro experimentos + informe
# (con y sin rúbrica LLM-as-judge).
#
#   bash eval/run_all.sh                     # completo (~1-3 h con un 8B local)
#   REPEATS=1 bash eval/run_all.sh           # pasada rápida para ver que todo fluye
#   JUDGE_LIMIT=20 bash eval/run_all.sh      # puntuar más trazas con el juez
#
# `baseline` se corre UNA vez y se reusa como brazo de control de todos los
# experimentos: las suites exp_* lo incluyen por comodidad, pero correrlas
# enteras lo pagaría cuatro veces.
set -euo pipefail

cd "$(dirname "$0")/.."

REPEATS="${REPEATS:-3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="results/suite-${STAMP}"
mkdir -p "$OUT" reports

echo "### baseline (dataset completo)"
python eval/run.py --scenarios easy,medium --repeats "$REPEATS" --out "$OUT/baseline-a.jsonl"
python eval/run.py --scenarios hard        --repeats "$REPEATS" --out "$OUT/baseline-b.jsonl"
python eval/run.py --scenarios extreme     --repeats "$REPEATS" --timeout 600 --out "$OUT/baseline-c.jsonl"

# Los experimentos A-C van sobre medium+hard: en `easy` todo satura y en
# `extreme` todo falla, así que la señal está en el medio.
echo "### experimento A — prompting genérico vs especializado"
python eval/run.py --config prompt_baseline --scenarios medium,hard --repeats "$REPEATS" --out "$OUT/exp-a.jsonl"

echo "### experimento B — ventana de memoria"
python eval/run.py --config mem_6,mem_20 --scenarios medium,hard --repeats "$REPEATS" --out "$OUT/exp-b.jsonl"

echo "### experimento C — ablación de examine y presupuesto de iteraciones"
python eval/run.py --config noop_examine,iters_10,iters_20 --scenarios medium,hard --repeats "$REPEATS" --out "$OUT/exp-c.jsonl"

# El D va sobre el dataset completo: `text_tool_call` puede aparecer en
# cualquier dificultad.
echo "### experimento D — reparación de tool calls textuales"
python eval/run.py --config repair_on --scenarios all --repeats "$REPEATS" --timeout 600 --out "$OUT/exp-d.jsonl"

echo "### informe"
python eval/report.py "$OUT"/*.jsonl -o "reports/m3-${STAMP}.md"
echo
echo "### rúbrica (LLM-as-judge)"
JUDGE_LIMIT="${JUDGE_LIMIT:-12}"
python eval/report.py "$OUT"/*.jsonl --judge --judge-limit "$JUDGE_LIMIT" -o "reports/m3-${STAMP}-judged.md"
echo
echo "Resultados crudos: $OUT/"
echo "Informe:           reports/m3-${STAMP}.md"
echo "Informe + rúbrica: reports/m3-${STAMP}-judged.md"
