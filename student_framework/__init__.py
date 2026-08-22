"""Paquete propio del grupo.

`build_agent` es la única puerta de entrada pública de la entrega: la usan
el runner de la CLI, los tests de conformidad y la infraestructura de
evaluación de M3.

Modos de construcción
---------------------
- **Modo genérico (M1/M2)**: sin `config["world"]`. Registra las tools de
  juguete (calculator, file_reader, word_counter) y usa el system prompt
  por defecto del agente. Es el comportamiento histórico, intacto.
- **Modo mundo (M3)**: con `config["world"]`. Registra los verbos de
  `mia_world.make_world_tools(world)` en lugar de las tools de juguete
  (que en una sala de escape son ruido para el modelo) y aplica el system
  prompt especializado.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from mia_agents.llm_client import LLMClient
from mia_agents.protocols import Agent
from mia_agents.types import ToolSchema

from .agent import MyAgent
from .prompts import BASELINE, ESCAPE_V1, get_prompt
from .tools.calculator import calculator, calculator_schema
from .tools.file_reader import file_reader, file_reader_schema
from .tools.word_counter import count_words, count_words_schema

ToolPair = tuple[Callable[..., str], ToolSchema]

#: Defaults del modo mundo. Los del constructor de `MyAgent` (10/10) no
#: alcanzan para M3: `vault-combination` necesita 21 tool calls óptimas,
#: así que un tope de 10 iteraciones garantiza el fallo por presupuesto.
WORLD_DEFAULTS: dict[str, Any] = {
    "max_iterations": 40,
    "max_history_messages": 40,
}

#: Mensaje que devuelve una tool convertida en no-op (experimento C).
NOOP_MESSAGE = "No observás nada especial."


def noop_pair(pair: ToolPair) -> ToolPair:
    """Devuelve la misma tool con el cuerpo vaciado, conservando el esquema.

    El modelo sigue viendo la herramienta y puede invocarla; simplemente
    deja de recibir información. Así el experimento aísla el valor de la
    *información* que aporta la tool, no el de su presencia en el prompt.
    """
    _, schema = pair

    def noop(**_kwargs: Any) -> str:
        return NOOP_MESSAGE

    return noop, schema


def build_agent(config: dict[str, Any] | None = None) -> Agent:
    """Construye y configura el agente.

    Claves reconocidas en `config` (todas opcionales):

    ``llm_client``
        Cliente LLM a usar. Si falta, se construye desde el entorno.
    ``world``
        Instancia de `mia_world.World`. Activa el modo mundo.
    ``tools``
        Iterable de pares ``(callable, ToolSchema)`` que reemplaza por
        completo el set de tools. Tiene prioridad sobre ``world``.
    ``noop_tools``
        Lista de nombres de tools a registrar como no-op conservando su
        esquema (experimento de ablación de herramientas).
    ``system_prompt`` / ``prompt``
        System prompt literal, o el nombre de una variante de
        `student_framework.prompts` (``"baseline"`` / ``"escape_v1"``).
    ``max_iterations``, ``max_history_messages``,
    ``max_transient_retries``, ``transient_retry_delay``
        Se pasan tal cual al constructor de `MyAgent`.
    """

    config = config or {} #NO CAMBIAR
    llm = config.get("llm_client") or LLMClient.from_env() #NO CAMBIAR
    kwargs: dict[str, Any] = {"llm_client": llm} #NO CAMBIAR

    world = config.get("world")
    explicit_tools: Iterable[ToolPair] | None = config.get("tools")
    world_mode = world is not None or explicit_tools is not None

    # --- presupuestos -----------------------------------------------------
    for key in (
        "max_iterations",
        "max_history_messages",
        "max_transient_retries",
        "transient_retry_delay",
        "repair_textual_tool_calls",
    ):
        if key in config:
            kwargs[key] = config[key]
        elif world_mode and key in WORLD_DEFAULTS:
            kwargs[key] = WORLD_DEFAULTS[key]

    # --- system prompt ----------------------------------------------------
    if "system_prompt" in config:
        kwargs["system_prompt"] = config["system_prompt"]
    elif "prompt" in config:
        kwargs["system_prompt"] = get_prompt(config["prompt"])
    elif world_mode:
        kwargs["system_prompt"] = ESCAPE_V1

    agent = MyAgent(**kwargs)

    # --- tools ------------------------------------------------------------
    if explicit_tools is not None:
        pairs: list[ToolPair] = list(explicit_tools)
    elif world is not None:
        from mia_world import make_world_tools

        pairs = list(make_world_tools(world))
    else:
        pairs = [
            (calculator, calculator_schema),
            (file_reader, file_reader_schema),
            (count_words, count_words_schema),
        ]

    noop_names = set(config.get("noop_tools") or ())
    unknown = noop_names - {schema.name for _, schema in pairs}
    if unknown:
        raise ValueError(
            f"noop_tools nombra herramientas no registradas: {sorted(unknown)}."
        )

    for pair in pairs:
        fn, schema = noop_pair(pair) if pair[1].name in noop_names else pair
        agent.register_tool(fn, schema)

    return agent


__all__ = ["MyAgent", "build_agent", "BASELINE", "ESCAPE_V1", "get_prompt", "NOOP_MESSAGE", "noop_pair"]
