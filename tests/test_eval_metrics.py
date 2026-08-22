"""Tests de métricas, taxonomía de fallos e informe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.failures import classify
from eval.fake_llm import LookOnceLLM, ScriptedLLM, WINNING_SCRIPTS
from eval.harness import run_case
from eval.judge import RubricScore, build_prompt, compare_with_human, format_trace
from eval.metrics import enrich, failure_breakdown, load_run, summarize
from eval.report import build_report


def _case(**over):
    base = {
        "scenario": "study-with-key",
        "difficulty": "easy",
        "config": "baseline",
        "repeat": 0,
        "status": "ok",
        "goal_achieved": False,
        "goal_reason": "cerrada",
        "n_tool_calls": 1,
        "n_tool_errors": 0,
        "tool_error_rate": 0.0,
        "latency_s": 1.0,
        "optimal_calls": 3,
        "answer": "",
        "agent_error": None,
        # Una traza no vacía y coherente con n_tool_calls: si se deja en []
        # dispara `no_tool_calls`, que tiene mayor prioridad y tapa lo que
        # cada test quiere aislar.
        "trace": [{"index": 0, "tool": "look", "args": {}, "output": "Estás en X.", "is_error": False}],
        "goal": {"type": "item_open", "item": "puerta_principal"},
        "final_state": {"event_log": []},
        "agent_config": {"max_history_messages": 40},
    }
    base.update(over)
    return base


# --- taxonomía ----------------------------------------------------------------


def test_success_has_no_failure_label() -> None:
    assert classify(_case(goal_achieved=True))["primary_failure"] is None


def test_textual_tool_call_is_detected_and_wins_over_premature_stop() -> None:
    answer = 'No puedo. {"name": "examine", "parameters": {"target": "escritorio"}}'
    c = classify(_case(answer=answer))
    assert "text_tool_call" in c["labels"]
    # Son mutuamente excluyentes: si emitió una tool call, no "decidió terminar".
    assert "premature_stop" not in c["labels"]
    assert c["primary_failure"] == "text_tool_call"


def test_premature_stop_when_answer_is_plain_prose() -> None:
    c = classify(_case(answer="Ya escapé de la sala, misión cumplida."))
    assert c["primary_failure"] == "premature_stop"


def test_loop_needs_three_identical_calls() -> None:
    two = [{"index": i, "tool": "look", "args": {}, "output": "ok", "is_error": False} for i in range(2)]
    assert "loop" not in classify(_case(trace=two, n_tool_calls=2))["labels"]
    three = two + [{"index": 2, "tool": "look", "args": {}, "output": "ok", "is_error": False}]
    assert "loop" in classify(_case(trace=three, n_tool_calls=3))["labels"]


def test_hallucinated_id_and_bad_args() -> None:
    trace = [
        {"index": 0, "tool": "take", "args": {"item": "dragon"},
         "output": "Error: no existe ningún objeto con id 'dragon'.", "is_error": True},
        {"index": 1, "tool": "take", "args": {"target": "x"}, "output": "Error: la herramienta falló",
         "is_error": True, "exception": "TypeError: take_impl() got an unexpected keyword argument 'target'"},
    ]
    labels = classify(_case(trace=trace, n_tool_calls=2))["labels"]
    assert "hallucinated_id" in labels and "bad_tool_args" in labels


def test_wrong_order_on_sequence_goal() -> None:
    c = classify(_case(
        goal={"type": "sequence", "goals": []},
        final_state={"event_log": ["enter:oficina", "open:puerta_principal", "take:documento_confidencial"]},
    ))
    assert "wrong_order" in c["labels"]


def test_priority_is_deterministic() -> None:
    c = classify(_case(status="crash", error="boom", answer="listo"))
    assert c["primary_failure"] == "crash"


# --- métricas -----------------------------------------------------------------


def test_pass_at_k_differs_from_pass_at_1() -> None:
    records = enrich([
        _case(repeat=0, goal_achieved=True, n_tool_calls=3),
        _case(repeat=1, goal_achieved=False),
        _case(repeat=2, goal_achieved=False),
    ])
    s = summarize(records)
    assert s["pass_at_1"] == pytest.approx(1 / 3, abs=1e-3)
    assert s["pass_at_k"] == 1.0, "pass@k debe capturar que lo resolvió alguna vez"


def test_action_efficiency_only_counts_solved_cases() -> None:
    records = enrich([
        _case(goal_achieved=True, n_tool_calls=3),   # óptimo -> 1.0
        _case(goal_achieved=True, n_tool_calls=6),   # el doble -> 0.5
        _case(goal_achieved=False, n_tool_calls=40),  # no cuenta
    ])
    assert records[0]["action_efficiency"] == 1.0
    assert records[2]["action_efficiency"] is None
    assert summarize(records)["action_efficiency"] == pytest.approx(0.75)


# --- integración con el harness ----------------------------------------------


def test_end_to_end_report_from_real_records(tmp_path: Path) -> None:
    won = run_case("study-with-key", llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]))
    lost = run_case("color-locks", repeat=0, llm_client=LookOnceLLM())

    path = tmp_path / "run.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {"model": "test", "provider": "fake", "scenarios": ["a"], "repeats": 1, "configs": {}}}) + "\n")
        for rec in (won, lost):
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta, records = load_run(path)
    assert meta["model"] == "test"
    records = enrich(records)
    s = summarize(records)
    assert s["n"] == 2 and s["pass_at_1"] == 0.5

    report = build_report([path])
    assert "# Informe de evaluación — M3" in report
    assert "study-with-key" in report and "color-locks" in report
    assert "Casos fallidos: **1** de 2" in report


# --- juez ---------------------------------------------------------------------


def test_judge_prompt_includes_trace_and_truncates() -> None:
    record = run_case("study-with-key", llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]))
    prompt = build_prompt(record)
    assert "examine" in prompt and "llave_oro" in prompt
    assert "final_result" in prompt
    long_trace = _case(trace=[
        {"index": i, "tool": "look", "args": {}, "output": "x" * 900, "is_error": False}
        for i in range(80)
    ])
    formatted = format_trace(long_trace)
    assert "truncadas" in formatted
    assert "…" in formatted


def test_rubric_schema_rejects_out_of_range() -> None:
    with pytest.raises(Exception):
        RubricScore(exploracion=9, uso_evidencia=3, recuperacion=3, justificacion="x")


def test_human_agreement_reports_exact_and_within_1() -> None:
    judged = [{"scenario": "s", "repeat": 0, "exploracion": 4, "uso_evidencia": 2, "recuperacion": 5}]
    human = {"s#0": {"exploracion": 4, "uso_evidencia": 3, "recuperacion": 1}}
    out = compare_with_human(judged, human)
    assert out["exploracion"]["exact_agreement"] == 1.0
    assert out["uso_evidencia"]["exact_agreement"] == 0.0
    assert out["uso_evidencia"]["within_1"] == 1.0
    assert out["recuperacion"]["within_1"] == 0.0


# --- experimento D: reparación de tool calls textuales ------------------------


def test_repair_is_off_by_default_and_stops_the_episode() -> None:
    """El baseline debe seguir cortando: es el brazo de control."""
    from mia_agents.types import LLMResponse

    class TextualLLM:
        """Emite la acción como texto en vez de como tool_call."""

        def __init__(self):
            self.n = 0

        def chat(self, messages, tools=None, system=None, temperature=0.2, response_format=None):
            self.n += 1
            if self.n == 1:
                return LLMResponse(content='{"name": "examine", "parameters": {"target": "alfombra"}}')
            if self.n == 2:
                return LLMResponse(content='{"name": "take", "parameters": {"item": "llave_oro"}}')
            if self.n == 3:
                return LLMResponse(content='{"name": "use", "parameters": {"item": "llave_oro", "target": "puerta_principal"}}')
            return LLMResponse(content="Listo, salí.")

    off = run_case("study-with-key", "baseline", llm_client=TextualLLM())
    assert off["n_tool_calls"] == 0, "sin reparación no debe ejecutarse ninguna tool"
    assert off["goal_achieved"] is False
    assert off["repaired_tool_calls"] == 0
    assert classify(off)["primary_failure"] == "text_tool_call"

    on = run_case("study-with-key", "repair_on", llm_client=TextualLLM())
    assert on["repaired_tool_calls"] == 3
    assert [e["tool"] for e in on["trace"]] == ["examine", "take", "use"]
    assert on["goal_achieved"] is True, "con reparación, la misma corrida gana"


def test_repair_does_not_fire_on_plain_prose() -> None:
    """Conservador: prosa que menciona tools no debe inventar acciones."""
    from mia_agents.types import LLMResponse

    class ProseLLM:
        def chat(self, messages, tools=None, system=None, temperature=0.2, response_format=None):
            return LLMResponse(content="Usé examine sobre la alfombra y tomé la llave. Ya está.")

    rec = run_case("study-with-key", "repair_on", llm_client=ProseLLM())
    assert rec["repaired_tool_calls"] == 0
    assert rec["n_tool_calls"] == 0
    assert classify(rec)["primary_failure"] == "premature_stop"


# --- salvaguarda contra informar sobre datos falsos --------------------------


def test_report_refuses_dry_run_results(tmp_path: Path) -> None:
    """Un informe hecho con el mock se ve idéntico a uno real. Debe fallar."""
    from eval.report import DryRunReportError

    rec = run_case("study-with-key", llm_client=LookOnceLLM())
    path = tmp_path / "dry.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {"dry_run": True, "model": "LookOnceLLM", "provider": "dry-run"}}) + "\n")
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with pytest.raises(DryRunReportError) as excinfo:
        build_report([path])
    assert "dry.jsonl" in str(excinfo.value)

    # Con el flag explícito sí, pero el informe lleva el aviso bien visible.
    report = build_report([path], allow_dry_run=True)
    assert "LLM falso" in report


def test_report_accepts_real_results(tmp_path: Path) -> None:
    rec = run_case("study-with-key", llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]))
    path = tmp_path / "real.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {"dry_run": False, "model": "x", "provider": "y"}}) + "\n")
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    assert "pass@1" in build_report([path])
