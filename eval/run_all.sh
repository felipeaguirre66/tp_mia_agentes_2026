#!/usr/bin/env bash
# Corrida completa de M3: baseline + los cuatro experimentos + informe.
#
#   bash eval/run_all.sh            # completo (~1-3 h con un 8B local)
#   REPEATS=1 bash eval/run_all.sh  # pasada rápida para ver que todo fluye
#
# `baseline` se corre UNA vez y se reusa como brazo de control de todos los
# experimentos: las suites exp_* lo incluyen por comodidad, pero correrlas
# enteras lo pagaría cuatro veces.
set -euo pipefail

cd "$(dirname "$0")/.."

REPEATS="${REPEATS:-3}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="results/final-${STAMP}"
mkdir -p "$OUT" reports

if [[ -n "${PYTHON_BIN:-}" ]]; then
  : # respetar override explícito
elif [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=.venv/bin/python
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  PYTHON_BIN=python
fi

echo "### python: $PYTHON_BIN"

echo "### baseline (dataset completo)"
"$PYTHON_BIN" eval/run.py --scenarios easy,medium --repeats "$REPEATS" --out "$OUT/baseline-a.jsonl"
"$PYTHON_BIN" eval/run.py --scenarios hard        --repeats "$REPEATS" --out "$OUT/baseline-b.jsonl"
"$PYTHON_BIN" eval/run.py --scenarios extreme     --repeats "$REPEATS" --timeout 600 --out "$OUT/baseline-c.jsonl"

# Los experimentos A-C van sobre medium+hard: en `easy` todo satura y en
# `extreme` todo falla, así que la señal está en el medio.
echo "### experimento A — prompting genérico vs especializado"
"$PYTHON_BIN" eval/run.py --config prompt_baseline --scenarios medium,hard --repeats "$REPEATS" --out "$OUT/exp-a.jsonl"

echo "### experimento B — ventana de memoria"
"$PYTHON_BIN" eval/run.py --config mem_6,mem_20 --scenarios medium,hard --repeats "$REPEATS" --out "$OUT/exp-b.jsonl"

echo "### experimento C — ablación de examine y presupuesto de iteraciones"
"$PYTHON_BIN" eval/run.py --config noop_examine,iters_10,iters_20 --scenarios medium,hard --repeats "$REPEATS" --out "$OUT/exp-c.jsonl"

# El D va sobre el dataset completo: `text_tool_call` puede aparecer en
# cualquier dificultad.
echo "### experimento D — reparación de tool calls textuales"
"$PYTHON_BIN" eval/run.py --config repair_off --scenarios all --repeats "$REPEATS" --timeout 600 --out "$OUT/exp-d.jsonl"

echo "### informe"
"$PYTHON_BIN" eval/report.py "$OUT"/*.jsonl -o "reports/m3-${STAMP}.md"

echo "### manifiesto"
{
  echo "# Manifest de resultados M3"
  echo
  echo "- Timestamp UTC: $STAMP"
  echo "- Git SHA: $(git rev-parse --short HEAD)"
  echo "- Casos esperados: $((40 * REPEATS))"
  echo
  echo "## SHA-256"
  echo
  echo '```text'
  sha256sum "$OUT"/*.jsonl
  echo '```'
} > "$OUT/MANIFEST.md"
echo
echo "Resultados crudos: $OUT/"
echo "Informe:           reports/m3-${STAMP}.md"
echo
echo "Para agregar la rúbrica (gasta tokens, ~1 llamada por traza):"
echo "  $PYTHON_BIN -m eval.judge score $OUT/*.jsonl --limit 10 --out reports/judge-scores-${STAMP}.json --human-template reports/human-scores-${STAMP}.json"
