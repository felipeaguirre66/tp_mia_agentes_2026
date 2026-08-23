"""Tests de métricas, taxonomía de fallos e informe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.failures import classify
from eval.configs import get_config
from eval.fake_llm import LookOnceLLM, ScriptedLLM, WINNING_SCRIPTS
from eval.harness import run_case
from eval.judge import (
    RubricScore,
    _compare_files,
    _human_template,
    _score_payload,
    _write_json,
    build_prompt,
    compare_with_human,
    format_trace,
    select_human_sample,
)
from eval.metrics import compare_configs, enrich, failure_breakdown, load_run, summarize
from eval.report import build_report
from eval.validation import ResultValidationError, validate_result_files


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


def test_experiment_arms_change_only_the_declared_variable() -> None:
    baseline = get_config("baseline")
    assert baseline["repair_textual_tool_calls"] is True

    expected_diffs = {
        "prompt_baseline": {"prompt"},
        "mem_6": {"max_history_messages"},
        "mem_20": {"max_history_messages"},
        "mem_40": set(),
        "noop_examine": {"noop_tools"},
        "iters_10": {"max_iterations"},
        "iters_20": {"max_iterations"},
        "repair_off": {"repair_textual_tool_calls"},
    }
    for name, expected in expected_diffs.items():
        arm = get_config(name)
        keys = set(baseline) | set(arm)
        actual = {key for key in keys if baseline.get(key) != arm.get(key)}
        assert actual == expected, name


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


def test_empty_response_after_partial_trace_is_classified() -> None:
    c = classify(_case(answer="", trace=[{
        "index": 0, "tool": "look", "args": {}, "output": "sala", "is_error": False,
    }]))
    assert c["primary_failure"] == "empty_response"


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


def test_pass_at_k_never_merges_distinct_configs() -> None:
    records = enrich([
        _case(config="baseline", goal_achieved=False),
        _case(config="repair_off", goal_achieved=True),
    ])
    summary = summarize(records)
    assert summary["pass_at_1"] == 0.5
    assert summary["pass_at_k"] == 0.5


def test_action_efficiency_only_counts_solved_cases() -> None:
    records = enrich([
        _case(goal_achieved=True, n_tool_calls=3),   # óptimo -> 1.0
        _case(goal_achieved=True, n_tool_calls=6),   # el doble -> 0.5
        _case(goal_achieved=False, n_tool_calls=40),  # no cuenta
    ])
    assert records[0]["action_efficiency"] == 1.0
    assert records[2]["action_efficiency"] is None
    assert summarize(records)["action_efficiency"] == pytest.approx(0.75)


def test_oracle_overhead_keeps_initial_look_visible() -> None:
    record = run_case(
        "study-with-key",
        llm_client=ScriptedLLM([("look", {}), *WINNING_SCRIPTS["study-with-key"]]),
    )
    enriched = enrich([record])[0]
    assert enriched["goal_achieved"] is True
    assert enriched["action_efficiency"] == 0.75
    assert enriched["excess_tool_calls"] == 1


def test_config_comparison_uses_scenario_intersection() -> None:
    records = enrich([
        _case(scenario="easy", config="baseline", goal_achieved=True),
        _case(scenario="medium", difficulty="medium", config="baseline", goal_achieved=False),
        _case(scenario="medium", difficulty="medium", config="mem_6", goal_achieved=True),
    ])
    comparison = compare_configs(records, "baseline", "mem_6")
    assert comparison["scenarios"] == ["medium"]
    assert comparison["control_summary"]["pass_at_1"] == 0.0
    assert comparison["treatment_summary"]["pass_at_1"] == 1.0
    assert comparison["delta"]["pass_at_1"] == 1.0


# --- integración con el harness ----------------------------------------------


def test_end_to_end_report_from_real_records(tmp_path: Path) -> None:
    won = run_case("study-with-key", llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]))
    lost = run_case("color-locks", repeat=0, llm_client=LookOnceLLM())

    path = tmp_path / "run.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {
            "model": "test", "provider": "fake", "git_sha": "abc",
            "scenarios": ["study-with-key", "color-locks"], "repeats": 1,
            "configs": {"baseline": {}}, "dry_run": False,
        }}) + "\n")
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


def test_judge_sample_covers_repeat_zero_then_long_failures() -> None:
    scenarios = [
        ("easy", "easy"),
        ("medium-a", "medium"),
        ("medium-b", "medium"),
        ("hard-a", "hard"),
        ("hard-b", "hard"),
        ("extreme-a", "extreme"),
        ("extreme-b", "extreme"),
        ("extreme-c", "extreme"),
    ]
    records = []
    for scenario, difficulty in scenarios:
        records.append(_case(scenario=scenario, difficulty=difficulty, repeat=0))
        records.append(_case(
            scenario=scenario,
            difficulty=difficulty,
            repeat=1,
            n_tool_calls=20 if scenario == "hard-a" else 2,
        ))
    selected = select_human_sample(records, 10)
    assert len(selected) == 10
    assert {(r["scenario"], r["repeat"]) for r in selected[:8]} == {
        (scenario, 0) for scenario, _ in scenarios
    }
    assert (selected[8]["scenario"], selected[8]["repeat"]) == ("hard-a", 1)


def test_persisted_judge_and_human_artifacts_compare(tmp_path: Path) -> None:
    class FakeJudge:
        def structured_call(self, _prompt, _schema):
            return RubricScore(
                exploracion=4,
                uso_evidencia=3,
                recuperacion=5,
                justificacion="Traza consistente.",
            )

    record = _case(config="baseline", goal_achieved=True)
    validation = {"provider": "fake", "model": "fake", "git_sha": "abc"}
    judged_payload = _score_payload(validation, [record], FakeJudge())
    human_payload = _human_template(validation, [record])
    for axis, value in zip(("exploracion", "uso_evidencia", "recuperacion"), (4, 4, 5)):
        human_payload["scores"][0][axis] = value

    judged_path = tmp_path / "judge.json"
    human_path = tmp_path / "human.json"
    _write_json(judged_path, judged_payload)
    _write_json(human_path, human_payload)
    compared = _compare_files(judged_path, human_path)
    assert compared["agreement"]["exploracion"]["exact_agreement"] == 1.0
    assert compared["agreement"]["uso_evidencia"]["within_1"] == 1.0


# --- experimento D: reparación de tool calls textuales ------------------------


def test_repair_off_is_the_ablation_and_baseline_repairs() -> None:
    """El sistema final repara; repair_off conserva el ReAct clásico."""
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

    off = run_case("study-with-key", "repair_off", llm_client=TextualLLM())
    assert off["n_tool_calls"] == 0, "sin reparación no debe ejecutarse ninguna tool"
    assert off["goal_achieved"] is False
    assert off["repaired_tool_calls"] == 0
    assert classify(off)["primary_failure"] == "text_tool_call"

    on = run_case("study-with-key", "baseline", llm_client=TextualLLM())
    assert on["repaired_tool_calls"] == 3
    assert [e["tool"] for e in on["trace"]] == ["examine", "take", "use"]
    assert on["goal_achieved"] is True, "con reparación, la misma corrida gana"


def test_repair_does_not_fire_on_plain_prose() -> None:
    """Conservador: prosa que menciona tools no debe inventar acciones."""
    from mia_agents.types import LLMResponse

    class ProseLLM:
        def chat(self, messages, tools=None, system=None, temperature=0.2, response_format=None):
            return LLMResponse(content="Usé examine sobre la alfombra y tomé la llave. Ya está.")

    rec = run_case("study-with-key", "baseline", llm_client=ProseLLM())
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
        fh.write(json.dumps({"_meta": {
            "dry_run": True, "model": "LookOnceLLM", "provider": "dry-run",
            "git_sha": "abc", "scenarios": ["study-with-key"], "repeats": 1,
            "configs": {"baseline": {}},
        }}) + "\n")
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
        fh.write(json.dumps({"_meta": {
            "dry_run": False, "model": "x", "provider": "y", "git_sha": "abc",
            "scenarios": ["study-with-key"], "repeats": 1,
            "configs": {"baseline": {}},
        }}) + "\n")
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    assert "pass@1" in build_report([path])


def test_report_cli_reconfigures_windows_stdout_to_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import eval.report as report_module

    rec = run_case("study-with-key", llm_client=LookOnceLLM())
    path = tmp_path / "real.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {
            "dry_run": False, "model": "x", "provider": "y", "git_sha": "abc",
            "scenarios": ["study-with-key"], "repeats": 1,
            "configs": {"baseline": {}, "prompt_baseline": {}},
        }}) + "\n")
        for config in ("baseline", "prompt_baseline"):
            fh.write(json.dumps({**rec, "config": config}, ensure_ascii=False) + "\n")

    class Cp1252Stdout:
        encoding = "cp1252"

        def __init__(self) -> None:
            self.parts: list[str] = []

        def reconfigure(self, *, encoding: str) -> None:
            self.encoding = encoding

        def write(self, value: str) -> int:
            assert self.encoding == "utf-8"
            self.parts.append(value)
            return len(value)

        def flush(self) -> None:
            pass

    stdout = Cp1252Stdout()
    monkeypatch.setattr(report_module.sys, "stdout", stdout)
    out = tmp_path / "report.md"
    assert report_module.main([str(path), "-o", str(out)]) == 0
    assert stdout.encoding == "utf-8"
    assert "# Informe de evaluación — M3" in "".join(stdout.parts)
    assert out.is_file()


def test_report_reads_persisted_qualitative_artifacts(tmp_path: Path) -> None:
    rec = run_case("study-with-key", llm_client=ScriptedLLM(WINNING_SCRIPTS["study-with-key"]))
    path = tmp_path / "real.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {
            "dry_run": False, "model": "x", "provider": "y", "git_sha": "abc",
            "scenarios": ["study-with-key"], "repeats": 1,
            "configs": {"baseline": {}},
        }}) + "\n")
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    judge_path = tmp_path / "judge.json"
    agreement_path = tmp_path / "agreement.json"
    _write_json(judge_path, {"scores": [{
        "scenario": "study-with-key", "repeat": 0, "goal_achieved": True,
        "exploracion": 4, "uso_evidencia": 5, "recuperacion": 4,
        "justificacion": "Bien.", "judge_error": None,
    }]})
    _write_json(agreement_path, {"agreement": {
        "exploracion": {"n": 1, "exact_agreement": 1.0, "within_1": 1.0, "mean_abs_diff": 0.0}
    }})
    report = build_report(
        [path],
        judge_scores_path=judge_path,
        judge_agreement_path=agreement_path,
    )
    assert "Dimensión cualitativa (artefacto persistido)" in report
    assert "Acuerdo juez-humano" in report


def test_validation_rejects_mixed_identity(tmp_path: Path) -> None:
    rec = run_case("study-with-key", llm_client=LookOnceLLM())
    paths = []
    for index, model in enumerate(("a", "b")):
        config = "baseline" if index == 0 else "repair_off"
        file_record = {**rec, "config": config}
        path = tmp_path / f"run-{index}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"_meta": {
                "dry_run": False, "model": model, "provider": "ollama", "git_sha": "abc",
                "scenarios": ["study-with-key"], "repeats": 1,
                "configs": {config: {}},
            }}) + "\n")
            fh.write(json.dumps(file_record, ensure_ascii=False) + "\n")
        paths.append(path)
    with pytest.raises(ResultValidationError, match="incompatible"):
        validate_result_files(paths)


def test_validation_rejects_duplicate_case_across_files(tmp_path: Path) -> None:
    rec = run_case("study-with-key", llm_client=LookOnceLLM())
    paths = []
    for index in range(2):
        path = tmp_path / f"duplicate-{index}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"_meta": {
                "dry_run": False, "model": "x", "provider": "ollama", "git_sha": "abc",
                "scenarios": ["study-with-key"], "repeats": 1,
                "configs": {"baseline": {}},
            }}) + "\n")
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        paths.append(path)
    with pytest.raises(ResultValidationError, match="repite casos"):
        validate_result_files(paths)


def test_validation_rejects_missing_case(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_meta": {
            "dry_run": False, "model": "x", "provider": "ollama", "git_sha": "abc",
            "scenarios": ["study-with-key"], "repeats": 2,
            "configs": {"baseline": {}},
        }}) + "\n")
    with pytest.raises(ResultValidationError, match="cohorte incompleta"):
        validate_result_files([path])
