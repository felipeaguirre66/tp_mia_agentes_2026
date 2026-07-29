"""Tests propios del grupo para resiliencia M2."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel, Field

from mia_agents.testing import MockLLMClient
from mia_agents.tool_schema import FINAL_RESULT_TOOL_NAME
from mia_agents.types import LLMResponse, ToolCall

from student_framework import build_agent
from student_framework.agent import is_transient_error


def test_is_transient_error_classifies_timeouts_and_rate_limits() -> None:
    assert is_transient_error(TimeoutError("llm timed out"))
    assert is_transient_error(ConnectionError("connection reset by peer"))
    assert is_transient_error(RuntimeError("HTTP 429 Too Many Requests"))
    assert is_transient_error(RuntimeError("Service Unavailable (503)"))
    assert not is_transient_error(ValueError("schema inválido"))


def test_transient_timeout_is_retried_and_run_succeeds() -> None:
    mock = MockLLMClient(
        [
            TimeoutError("simulated provider timeout"),
            TimeoutError("simulated provider timeout again"),
            LLMResponse(content="recuperado tras timeout"),
        ]
    )
    agent = build_agent(
        {
            "llm_client": mock,
            "max_transient_retries": 3,
            "transient_retry_delay": 0.0,
        }
    )

    result = agent.run("hola")

    assert result.answer == "recuperado tras timeout"
    assert result.error is None
    assert mock.call_count == 3


def test_non_transient_error_is_not_retried() -> None:
    mock = MockLLMClient([ValueError("fallo permanente del proveedor")])
    agent = build_agent(
        {
            "llm_client": mock,
            "max_transient_retries": 5,
            "transient_retry_delay": 0.0,
        }
    )

    with pytest.raises(ValueError, match="fallo permanente"):
        agent.run("hola")

    assert mock.call_count == 1


def test_exhausted_transient_retries_raise_cleanly() -> None:
    mock = MockLLMClient(
        [
            TimeoutError("t1"),
            TimeoutError("t2"),
            TimeoutError("t3"),
        ]
    )
    agent = build_agent(
        {
            "llm_client": mock,
            "max_transient_retries": 2,
            "transient_retry_delay": 0.0,
        }
    )

    with pytest.raises(TimeoutError, match="t3"):
        agent.run("hola")

    assert mock.call_count == 3


def test_structured_call_repairs_deliberately_broken_output() -> None:
    class Answer(BaseModel):
        result: int = Field(description="número entero")
        comment: str = Field(description="comentario corto")

    mock = MockLLMClient(
        [
            LLMResponse(content="acá va texto libre en vez de la tool"),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="fr-bad",
                        name=FINAL_RESULT_TOOL_NAME,
                        arguments=json.dumps(
                            {"result": "cuarenta y dos", "comment": "mal"}
                        ),
                    )
                ],
            ),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="fr-ok",
                        name=FINAL_RESULT_TOOL_NAME,
                        arguments=json.dumps({"result": 42, "comment": "ok"}),
                    )
                ],
            ),
        ]
    )
    agent = build_agent({"llm_client": mock, "transient_retry_delay": 0.0})

    parsed = agent.structured_call(
        prompt="dame un objeto",
        schema=Answer,
        max_repair_attempts=2,
    )

    assert parsed.result == 42
    assert parsed.comment == "ok"
    assert mock.call_count == 3
