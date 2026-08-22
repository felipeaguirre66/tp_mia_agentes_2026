"""Tests del runner aislado y la durabilidad de resultados."""

from __future__ import annotations

import sys
import time

import pytest

import eval.run as eval_run


def test_isolated_timeout_kills_a_slow_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        eval_run,
        "_worker_command",
        lambda *_args, **_kwargs: [
            sys.executable,
            "-c",
            "import time; time.sleep(5)",
        ],
    )
    started = time.perf_counter()
    record = eval_run.run_case_isolated(
        "study-with-key",
        "baseline",
        repeat=0,
        max_tool_calls=60,
        timeout_s=0.05,
        dry_run=True,
    )
    elapsed = time.perf_counter() - started
    assert record["status"] == "budget_timeout"
    assert record["partial_trace_unavailable"] is True
    assert elapsed < 1.0


def test_isolated_dry_run_returns_json_record() -> None:
    record = eval_run.run_case_isolated(
        "study-with-key",
        "baseline",
        repeat=0,
        max_tool_calls=60,
        timeout_s=10,
        dry_run=True,
    )
    assert record["status"] == "ok"
    assert record["n_tool_calls"] == 1
    assert record["config"] == "baseline"


def test_runner_refuses_to_overwrite_output(tmp_path) -> None:
    output = tmp_path / "existing.jsonl"
    output.write_text("preservar\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no se sobrescribirá"):
        eval_run.main(["--dry-run", "--scenarios", "easy", "--out", str(output)])
    assert output.read_text(encoding="utf-8") == "preservar\n"
