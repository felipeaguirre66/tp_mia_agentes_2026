#!/usr/bin/env python3
"""Entrypoint reproducible de la evaluación de M3.

    python eval/run.py                          # baseline sobre todo el dataset
    python eval/run.py --scenarios easy,medium  # subconjunto
    python eval/run.py --config exp_a --repeats 3
    python eval/run.py --dry-run                # sin proveedor LLM, valida la infra

Escribe un JSONL nuevo en `results/`: una primera línea de metadatos
(`{"_meta": ...}`) y una línea por caso. Hace flush después de cada caso
para conservar una corrida interrumpida y rechaza sobrescribir un path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.catalog import resolve_scenarios  # noqa: E402
from eval.configs import get_config, resolve_configs  # noqa: E402
from eval.harness import (  # noqa: E402
    DEFAULT_MAX_TOOL_CALLS,
    DEFAULT_TIMEOUT_S,
    make_isolated_failure_record,
)

RESULTS_DIR = REPO_ROOT / "results"


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None


def _provider_info(dry_run: bool) -> dict[str, Any]:
    """Identifica el proveedor/modelo para que la corrida sea trazable."""
    if dry_run:
        return {"provider": "dry-run", "model": "LookOnceLLM"}
    import os

    # `from_env()` carga el .env recién en el primer caso; sin esto el meta
    # registraría el default del provider y no el modelo que realmente corrió.
    from mia_agents._env import load_env_files

    load_env_files()

    # MISMA precedencia que `LLMClient.from_env()`: OLLAMA_HOST primero.
    # Si acá se invierte, el meta miente sobre qué modelo produjo los números.
    if os.environ.get("OLLAMA_HOST"):
        return {
            "provider": "ollama",
            "model": os.environ.get("OLLAMA_MODEL", "llama3.1"),
            "host": os.environ["OLLAMA_HOST"],
        }
    if os.environ.get("BEDROCK_MODEL_ID"):
        return {
            "provider": "bedrock",
            "model": os.environ["BEDROCK_MODEL_ID"],
            "region": os.environ.get("AWS_REGION", "us-east-1"),
        }
    return {"provider": "unknown", "model": None}


def _worker_command(
    scenario_id: str,
    config_name: str,
    repeat: int,
    max_tool_calls: int,
    timeout_s: float,
    dry_run: bool,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "eval.case_worker",
        "--scenario",
        scenario_id,
        "--config",
        config_name,
        "--repeat",
        str(repeat),
        "--max-tool-calls",
        str(max_tool_calls),
        "--timeout",
        str(timeout_s),
    ]
    if dry_run:
        command.append("--dry-run")
    return command


def run_case_isolated(
    scenario_id: str,
    config_name: str,
    *,
    repeat: int,
    max_tool_calls: int,
    timeout_s: float,
    dry_run: bool,
) -> dict[str, Any]:
    """Ejecuta un caso en un proceso terminable por wall-clock."""
    command = _worker_command(
        scenario_id,
        config_name,
        repeat,
        max_tool_calls,
        timeout_s,
        dry_run,
    )
    t0 = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - t0
        return make_isolated_failure_record(
            scenario_id,
            config_name,
            repeat=repeat,
            status="budget_timeout",
            error=f"Presupuesto de wall-clock agotado ({timeout_s}s).",
            latency_s=elapsed,
        )

    elapsed = time.perf_counter() - t0
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "worker sin detalle").strip()
        return make_isolated_failure_record(
            scenario_id,
            config_name,
            repeat=repeat,
            status="crash",
            error=f"Worker terminó con código {completed.returncode}: {detail[-1200:]}",
            latency_s=elapsed,
        )

    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        record = json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        return make_isolated_failure_record(
            scenario_id,
            config_name,
            repeat=repeat,
            status="crash",
            error=f"Worker no devolvió un registro JSON válido: {exc}",
            latency_s=elapsed,
        )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval/run.py")
    parser.add_argument(
        "--scenarios",
        default="all",
        help="'all', una dificultad, un id, un path, o varios separados por comas.",
    )
    parser.add_argument(
        "--config",
        default="baseline",
        help="Nombre(s) de configuración o suite (exp_a, exp_b, exp_c).",
    )
    parser.add_argument("--repeats", type=int, default=1, help="Repeticiones por caso.")
    parser.add_argument("--out", default=None, help="Ruta del JSONL de salida.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Usa un LLM falso: valida la infraestructura sin proveedor ni tokens.",
    )
    parser.add_argument(
        "--max-tool-calls", type=int, default=DEFAULT_MAX_TOOL_CALLS,
        help="Presupuesto duro de tool calls por caso.",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S,
        help="Presupuesto duro de wall-clock por caso, en segundos.",
    )
    args = parser.parse_args(argv)

    if args.repeats < 1:
        parser.error("--repeats debe ser >= 1.")
    if args.max_tool_calls < 1:
        parser.error("--max-tool-calls debe ser >= 1.")
    if args.timeout <= 0:
        parser.error("--timeout debe ser > 0.")

    scenarios = resolve_scenarios(args.scenarios)
    config_names = resolve_configs(args.config)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else RESULTS_DIR / f"run-{stamp}.jsonl"
    if out_path.exists():
        raise SystemExit(
            f"La salida ya existe y no se sobrescribirá: {out_path}. "
            "Elegí otro --out."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    meta = {
        "_meta": {
            "timestamp_utc": stamp,
            "git_sha": _git_sha(),
            "python": sys.version.split()[0],
            "scenarios": [sc.id for sc in scenarios],
            "configs": {name: get_config(name) for name in config_names},
            "repeats": args.repeats,
            "max_tool_calls": args.max_tool_calls,
            "timeout_s": args.timeout,
            "dry_run": args.dry_run,
            **_provider_info(args.dry_run),
        }
    }

    total = len(scenarios) * len(config_names) * args.repeats
    print(f"# {total} casos -> {out_path}", file=sys.stderr)

    n_ok = 0
    t_start = time.perf_counter()
    with out_path.open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
        fh.flush()

        i = 0
        for config_name in config_names:
            for sc in scenarios:
                for repeat in range(args.repeats):
                    i += 1
                    print(
                        f"[{i}/{total}] {config_name} :: {sc.id} (rep {repeat})",
                        end=" ",
                        file=sys.stderr,
                        flush=True,
                    )
                    record = run_case_isolated(
                        sc.id,
                        config_name,
                        repeat=repeat,
                        max_tool_calls=args.max_tool_calls,
                        timeout_s=args.timeout,
                        dry_run=args.dry_run,
                    )
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                    fh.flush()  # append-only real: nada se pierde si cortás
                    n_ok += int(record["goal_achieved"])
                    mark = "OK " if record["goal_achieved"] else "-- "
                    print(
                        f"{mark} {record['status']} "
                        f"calls={record['n_tool_calls']} "
                        f"{record['latency_s']}s",
                        file=sys.stderr,
                        flush=True,
                    )

    elapsed = time.perf_counter() - t_start
    print(
        f"\n# {n_ok}/{total} objetivos cumplidos en {elapsed:.1f}s -> {out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
