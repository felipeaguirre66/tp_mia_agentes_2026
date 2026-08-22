"""Configuraciones nombradas del agente.

Cada entrada es un dict que el harness fusiona sobre el `config` de
`build_agent`. `baseline` es la configuración de la corrida principal; el
resto son los brazos de los experimentos de la Fase 6. Mantenerlos acá
(y no como flags sueltos) garantiza que un experimento cambie **una sola**
variable respecto de `baseline` y que la corrida sea reproducible desde el
nombre.
"""

from __future__ import annotations

from typing import Any

CONFIGS: dict[str, dict[str, Any]] = {
    # --- corrida principal -------------------------------------------------
    "baseline": {
        "prompt": "escape_v1",
        "max_iterations": 40,
        "max_history_messages": 40,
        "repair_textual_tool_calls": True,
    },
    # --- experimento A: prompting genérico vs especializado ----------------
    "prompt_baseline": {
        "prompt": "baseline",
        "max_iterations": 40,
        "max_history_messages": 40,
        "repair_textual_tool_calls": True,
    },
    # --- experimento B: tamaño de la ventana de memoria --------------------
    "mem_6": {
        "prompt": "escape_v1",
        "max_iterations": 40,
        "max_history_messages": 6,
        "repair_textual_tool_calls": True,
    },
    "mem_20": {
        "prompt": "escape_v1",
        "max_iterations": 40,
        "max_history_messages": 20,
        "repair_textual_tool_calls": True,
    },
    "mem_40": {
        "prompt": "escape_v1",
        "max_iterations": 40,
        "max_history_messages": 40,
        "repair_textual_tool_calls": True,
    },
    # --- experimento C: ablación de herramientas y presupuesto -------------
    "noop_examine": {
        "prompt": "escape_v1",
        "max_iterations": 40,
        "max_history_messages": 40,
        "repair_textual_tool_calls": True,
        "noop_tools": ["examine"],
    },
    "iters_10": {
        "prompt": "escape_v1",
        "max_iterations": 10,
        "max_history_messages": 40,
        "repair_textual_tool_calls": True,
    },
    "iters_20": {
        "prompt": "escape_v1",
        "max_iterations": 20,
        "max_history_messages": 40,
        "repair_textual_tool_calls": True,
    },
    # --- experimento D: reparación de tool calls emitidas como texto -------
    # `baseline` es el sistema final (reparación ON); este es su ablación.
    "repair_off": {
        "prompt": "escape_v1",
        "max_iterations": 40,
        "max_history_messages": 40,
        "repair_textual_tool_calls": False,
    },
}

#: Agrupaciones cómodas para `python eval/run.py --config exp_a`.
SUITES: dict[str, list[str]] = {
    "exp_a": ["baseline", "prompt_baseline"],
    "exp_b": ["mem_6", "mem_20", "mem_40"],
    "exp_c": ["baseline", "noop_examine", "iters_10", "iters_20"],
    "exp_d": ["baseline", "repair_off"],
}


def resolve_configs(spec: str) -> list[str]:
    """Resuelve `spec` a una lista de nombres de configuración."""
    names: list[str] = []
    for token in (t.strip() for t in spec.split(",") if t.strip()):
        if token in SUITES:
            names.extend(SUITES[token])
        elif token in CONFIGS:
            names.append(token)
        else:
            opciones = ", ".join(sorted(CONFIGS))
            suites = ", ".join(sorted(SUITES))
            raise SystemExit(
                f"Configuración desconocida {token!r}. "
                f"Disponibles: {opciones}. Suites: {suites}."
            )
    # dedup preservando orden
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def get_config(name: str) -> dict[str, Any]:
    try:
        return dict(CONFIGS[name])
    except KeyError:
        opciones = ", ".join(sorted(CONFIGS))
        raise KeyError(f"Configuración desconocida {name!r}. Disponibles: {opciones}.") from None
