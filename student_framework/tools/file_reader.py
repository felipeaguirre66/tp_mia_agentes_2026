from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from mia_agents.types import ToolSchema


def file_reader(
    path: Annotated[str, Field(description="Ruta del archivo de texto a leer.")],
) -> str:
    """Lee un archivo de texto UTF-8 y devuelve su contenido completo."""
    return Path(path).read_text(encoding="utf-8")


file_reader_schema = ToolSchema.from_callable(file_reader)