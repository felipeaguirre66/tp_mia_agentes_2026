"""Tests de la infraestructura de evaluación de M3.

Validan el harness **sin** proveedor LLM: si la infra miente (no detecta un
caso ganador, reutiliza el mundo entre repeticiones, no corta un loop), no
tiene sentido gastar tokens en la corrida real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from eval.catalog import OPTIMAL_CALLS, resolve_scenarios
from eval.fake_llm import LookOnceLLM, ScriptedLLM, WINNING_SCRIPTS
from eval.harness import run_case
from eval.tracing import is_tool_error
from mia_agents.types import LLMResponse, ToolCall


class LoopLLM:
    """Llama siempre a la misma tool: simula un agente en loop infinito."""

    def __init__(self) -> None:
        self.call_count = 0

    def chat(self, messages, tools=None, system=None, temperature=0.2, response_format=None):
        self.call_count += 1
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id=f"c{self.call_count}", name="look", arguments="{}")],
        )


class BrokenLLM:
    """Proveedor que revienta: el harness debe registrarlo, no propagarlo."""

    def chat(self, messages, tools=None, system=None, temperature=0.2, response_format=None):
        raise RuntimeError("boom del proveedor")


# --- caso ganador -------------------------------------------------------------


def test_winning_case_is_reported_as_achieved() -> None:
    record = run_case(
        "study-with-key",
        llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]),
    )
    assert record["goal_achieved"] is True
    assert record["status"] == "ok"
    assert record["n_tool_calls"] == OPTIMAL_CALLS["study-with-key"] == 3
    assert record["n_tool_errors"] == 0
    assert [e["tool"] for e in record["trace"]] == ["examine", "take", "use"]
    assert record["final_state"]["opened"] == ["puerta_principal"]
    assert "llave_oro" in record["final_state"]["inventory"]


def test_record_is_json_serializable() -> None:
    record = run_case("study-with-key", llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]))
    json.dumps(record, ensure_ascii=False)  # no debe lanzar


# --- aislamiento entre casos --------------------------------------------------


def test_world_is_fresh_between_repeats() -> None:
    """Un caso ganador no puede contaminar al siguiente."""
    won = run_case("study-with-key", llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]))
    assert won["goal_achieved"] is True

    lost = run_case("study-with-key", repeat=1, llm_client=LookOnceLLM())
    assert lost["goal_achieved"] is False, "el mundo se reusó entre repeticiones"
    assert lost["final_state"]["opened"] == []


# --- presupuestos -------------------------------------------------------------


def test_tool_call_budget_stops_a_loop() -> None:
    record = run_case(
        "study-with-key",
        llm_client=LoopLLM(),
        max_tool_calls=5,
        extra_config={"max_iterations": 1000},
    )
    assert record["status"] == "budget_tool_calls"
    assert record["n_tool_calls"] == 5
    assert record["goal_achieved"] is False


def test_timeout_budget_is_enforced() -> None:
    record = run_case(
        "study-with-key",
        llm_client=LoopLLM(),
        timeout_s=0.0,
        extra_config={"max_iterations": 1000},
    )
    assert record["status"] == "budget_timeout"


# --- robustez -----------------------------------------------------------------


def test_provider_crash_is_recorded_not_raised() -> None:
    record = run_case("study-with-key", llm_client=BrokenLLM())
    assert record["status"] == "crash"
    assert "boom del proveedor" in record["error"]
    assert record["goal_achieved"] is False
    assert "traceback" in record


def test_tool_errors_are_detected_from_output_string() -> None:
    """Las tools del mundo devuelven 'Error: ...' en vez de lanzar."""
    record = run_case(
        "study-with-key",
        llm_client=ScriptedLLM([("take", {"item": "unicornio"})]),
    )
    assert record["n_tool_calls"] == 1
    assert record["n_tool_errors"] == 1
    assert record["tool_error_rate"] == 1.0
    # El agente NO ve una excepción: AgentStep.error queda en None.
    assert record["steps"][0]["error"] is None
    assert is_tool_error(record["trace"][0]["output"])


# --- ablación de herramientas -------------------------------------------------


def test_noop_tool_keeps_schema_but_returns_nothing() -> None:
    record = run_case(
        "study-with-key",
        "noop_examine",
        llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]),
    )
    assert record["noop_tools"] == ["examine"]
    assert record["trace"][0]["tool"] == "examine"
    assert "No observás nada especial" in record["trace"][0]["output"]
    # Sin examine no se revela la llave: la secuencia ganadora deja de ganar.
    assert record["goal_achieved"] is False


# --- catálogo -----------------------------------------------------------------


def test_every_scenario_has_an_optimal_and_runs() -> None:
    scenarios = resolve_scenarios("all")
    assert len(scenarios) == 8
    for sc in scenarios:
        assert sc.id in OPTIMAL_CALLS, f"falta el óptimo de {sc.id}"
        record = run_case(sc.id, llm_client=LookOnceLLM())
        assert record["status"] == "ok"
        assert record["n_tool_calls"] == 1
        assert record["difficulty"] == sc.difficulty
