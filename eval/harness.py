"""Ejecución de UN caso de evaluación.

Un *caso* = escenario × configuración × repetición. `run_case` devuelve un
registro plano y serializable a JSON; nunca lanza: cualquier fallo (del
proveedor, de una tool, de presupuesto) se codifica en el registro con
`status` y `error`, para que una corrida de 24 casos no se caiga por uno.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from mia_world import check_goal, make_world_tools
from mia_world.state import Scenario

from eval.catalog import BRUTE_FORCE_CALLS, OPTIMAL_CALLS, fresh_scenario
from eval.configs import get_config
from eval.llm_probe import CountingLLM
from eval.tracing import BudgetExceeded, Tracer

#: Presupuestos duros por caso, además de `max_iterations` del agente.
DEFAULT_MAX_TOOL_CALLS = 60
DEFAULT_TIMEOUT_S = 300.0


def run_case(
    scenario: Scenario | str,
    config_name: str = "baseline",
    *,
    repeat: int = 0,
    llm_client: Any | None = None,
    build_agent: Callable[[dict[str, Any]], Any] | None = None,
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    scenarios_dir: Path | None = None,
    extra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ejecuta un caso y devuelve su registro.

    `scenario` puede ser un `Scenario` o un id; en ambos casos el mundo se
    **recarga desde disco** para que cada repetición arranque virgen (las
    tools mutan el `World` en sitio).
    """
    if build_agent is None:
        from student_framework import build_agent as _build_agent

        build_agent = _build_agent

    scenario_id = scenario if isinstance(scenario, str) else scenario.id
    sc = fresh_scenario(scenario_id, scenarios_dir)
    world = sc.initial_world

    config = get_config(config_name)
    if extra_config:
        config.update(extra_config)

    tracer = Tracer(world=world, max_tool_calls=max_tool_calls, timeout_s=timeout_s)

    # Orden de composición: tools del mundo -> no-op (si el brazo lo pide)
    # -> traza. El no-op va ANTES para que la traza registre también las
    # llamadas a la herramienta ablacionada (queremos saber cuántas veces
    # el agente insistió con una tool que no le devuelve nada).
    pairs = make_world_tools(world)
    noop_names = set(config.pop("noop_tools", None) or ())
    if noop_names:
        from student_framework import noop_pair

        pairs = [noop_pair(p) if p[1].name in noop_names else p for p in pairs]
    pairs = tracer.wrap_all(pairs)

    probe: CountingLLM | None = None

    record: dict[str, Any] = {
        "scenario": sc.id,
        "difficulty": sc.difficulty,
        "config": config_name,
        "repeat": repeat,
        "noop_tools": sorted(noop_names),
        "agent_config": {
            k: v for k, v in config.items() if k not in ("llm_client", "world", "tools")
        },
        "optimal_calls": OPTIMAL_CALLS.get(sc.id),
        "brute_force_calls": BRUTE_FORCE_CALLS.get(sc.id),
        "goal": sc.goal,
    }

    t0 = time.perf_counter()
    status = "ok"
    error: str | None = None
    result: Any = None
    agent: Any = None

    try:
        # Envolvemos SIEMPRE el cliente: si no nos dan uno, lo construimos
        # acá en vez de dejar que `build_agent` lo cree por dentro, porque un
        # cliente que el harness no ve es un cliente que no puede medir.
        # Va dentro del try porque `from_env()` falla si no hay proveedor
        # configurado, y eso es un caso fallido, no una excepción del runner.
        client = llm_client
        if client is None:
            from mia_agents.llm_client import LLMClient

            client = LLMClient.from_env()
        probe = CountingLLM(client)

        agent = build_agent(
            {**config, "world": world, "tools": pairs, "llm_client": probe, "goal": sc.goal}
        )
        result = agent.run(sc.user_message)
    except BudgetExceeded as exc:
        status = f"budget_{exc.kind}"
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 — un caso roto no tumba la corrida
        status = "crash"
        error = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc(limit=8)

    latency_s = time.perf_counter() - t0

    # El goal se evalúa SIEMPRE sobre el estado del mundo, incluso si el
    # agente crasheó: puede haber abierto la puerta y morir después.
    achieved, reason = check_goal(world, sc.goal)

    n_calls = tracer.n_calls
    record.update(
        {
            "status": status,
            "error": error,
            "goal_achieved": bool(achieved),
            "goal_reason": reason,
            "n_tool_calls": n_calls,
            "n_tool_errors": tracer.n_errors,
            "tool_error_rate": (tracer.n_errors / n_calls) if n_calls else None,
            "latency_s": round(latency_s, 3),
            "answer": getattr(result, "answer", None),
            "agent_error": getattr(result, "error", None),
            "input_tokens": getattr(result, "input_tokens", None),
            "output_tokens": getattr(result, "output_tokens", None),
            **(probe.stats() if probe else {}),
            "repaired_tool_calls": getattr(agent, "repaired_tool_calls", 0),
            "goal_gate_triggers": getattr(agent, "goal_gate_triggers", 0),
            "final_state": {
                "room": world.current_room,
                "inventory": list(world.inventory),
                "opened": sorted(
                    i for i, it in world.items.items() if it.open_state == "open"
                ),
                "event_log": list(world.event_log),
            },
            "trace": tracer.trace(),
            "steps": [asdict(s) for s in getattr(result, "steps", [])],
        }
    )
    return record
