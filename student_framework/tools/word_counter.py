

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from mia_agents.types import ToolSchema


def count_words(
    text: Annotated[str, Field(description="El texto a contar las palabras.")],
) -> str:
    """Toma un texto y devuelve la cantidad de palabras que contiene."""
    return str(len(text.split()))



count_words_schema = ToolSchema.from_callable(count_words)
