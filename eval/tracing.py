"""Traza de herramientas y presupuestos duros por caso.

Por qué una traza propia y no `AgentResult.steps`:

1. `steps` no lleva timestamps, y queremos latencia por llamada.
2. Las tools del mundo **no lanzan excepciones**: ante un id inexistente o
   un objeto no visible devuelven un string que empieza con ``"Error:"``.
   Es decir, `AgentStep.error` es casi siempre `None` aunque el agente esté
   fallando sistemáticamente. La tasa de error hay que leerla del *output*.
3. Queremos el estado del mundo después de cada acción (sala, inventario,
   items abiertos) para reconstruir el progreso real y detectar loops.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from mia_agents.types import ToolSchema
from mia_world.state import World

ToolPair = tuple[Callable[..., str], ToolSchema]

#: Prefijo con el que las tools de `mia_world` marcan un fallo recuperable.
ERROR_PREFIX = "Error:"


class BudgetExceeded(BaseException):
    """Corta la ejecución de un caso al agotarse un presupuesto.

    Hereda de `BaseException` **a propósito**: el bucle de `MyAgent` captura
    `Exception` alrededor de cada tool call y convertiría un corte de
    presupuesto en un simple `tool_error`, dejando al agente iterar hasta
    `max_iterations`. Al no ser una `Exception`, esta señal atraviesa el
    agente y llega al harness, que la registra como fallo de presupuesto con
    la traza parcial intacta.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def is_tool_error(output: str | None) -> bool:
    """True si el string devuelto por una tool del mundo reporta un fallo."""
    return bool(output) and output.lstrip().startswith(ERROR_PREFIX)


@dataclass
class ToolEvent:
    """Una invocación de herramienta, con su efecto sobre el mundo."""

    index: int
    tool: str
    args: dict[str, Any]
    output: str
    is_error: bool
    duration_s: float
    elapsed_s: float
    room: str
    inventory: list[str]
    opened: list[str]
    exception: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tool": self.tool,
            "args": self.args,
            "output": self.output,
            "is_error": self.is_error,
            "duration_s": round(self.duration_s, 4),
            "elapsed_s": round(self.elapsed_s, 3),
            "room": self.room,
            "inventory": list(self.inventory),
            "opened": list(self.opened),
            "exception": self.exception,
        }


@dataclass
class Tracer:
    """Envuelve las tools de un mundo para registrar cada llamada.

    También aplica los dos presupuestos duros del caso: número máximo de
    tool calls y wall-clock. Ambos se chequean **antes** de ejecutar la
    herramienta, de modo que el corte queda registrado como el intento que
    lo disparó y no como una acción consumada.
    """

    world: World
    max_tool_calls: int = 60
    timeout_s: float = 300.0
    events: list[ToolEvent] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)

    # --- snapshots del mundo ------------------------------------------------

    def _opened(self) -> list[str]:
        return sorted(
            item_id
            for item_id, item in self.world.items.items()
            if item.open_state == "open"
        )

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at

    # --- presupuestos -------------------------------------------------------

    def _check_budget(self) -> None:
        if len(self.events) >= self.max_tool_calls:
            raise BudgetExceeded(
                "tool_calls",
                f"Presupuesto de tool calls agotado ({self.max_tool_calls}).",
            )
        elapsed = self.elapsed()
        if elapsed >= self.timeout_s:
            raise BudgetExceeded(
                "timeout",
                f"Presupuesto de tiempo agotado ({elapsed:.1f}s / {self.timeout_s}s).",
            )

    # --- envoltorio ---------------------------------------------------------

    def wrap(self, pair: ToolPair) -> ToolPair:
        fn, schema = pair

        def traced(**kwargs: Any) -> str:
            self._check_budget()
            t0 = time.perf_counter()
            exception: str | None = None
            try:
                output = fn(**kwargs)
            except Exception as exc:  # noqa: BLE001 — lo registramos y re-lanzamos
                exception = f"{type(exc).__name__}: {exc}"
                output = f"Error: la herramienta falló ({exception})."
                raise
            finally:
                self.events.append(
                    ToolEvent(
                        index=len(self.events),
                        tool=schema.name,
                        args=dict(kwargs),
                        output=output if exception is None else output,
                        is_error=exception is not None or is_tool_error(output),
                        duration_s=time.perf_counter() - t0,
                        elapsed_s=self.elapsed(),
                        room=self.world.current_room,
                        inventory=list(self.world.inventory),
                        opened=self._opened(),
                        exception=exception,
                    )
                )
            return output

        return traced, schema

    def wrap_all(self, pairs: list[ToolPair]) -> list[ToolPair]:
        return [self.wrap(p) for p in pairs]

    # --- lectura ------------------------------------------------------------

    def trace(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.events]

    @property
    def n_calls(self) -> int:
        return len(self.events)

    @property
    def n_errors(self) -> int:
        return sum(1 for e in self.events if e.is_error)
