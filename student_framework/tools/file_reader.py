from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field

from mia_agents.types import ToolSchema

# Directorio raíz del que la herramienta no puede salir.
_SANDBOX = (Path(__file__).resolve().parent.parent / "test").resolve()


def _list_entries(directory: Path) -> str:
    """Nombres del directorio, con '/' final para subdirectorios."""
    entries = sorted(
        entry.name + ("/" if entry.is_dir() else "")
        for entry in directory.iterdir()
    )
    return ", ".join(entries) if entries else "(directorio vacío)"


def file_reader(
    path: Annotated[
        str,
        Field(description="Ruta relativa al sandbox del archivo a leer, p. ej. 'data.txt'."),
    ],
) -> str:
    """Lee un archivo de texto UTF-8 del sandbox y devuelve su contenido completo.

    Las rutas se interpretan relativas al sandbox de la herramienta; no se
    aceptan rutas absolutas ni que salgan de él.
    """
    if not path or not path.strip():
        return (
            "Error recuperable: la ruta está vacía. Enviá una ruta relativa "
            "al sandbox, por ejemplo 'data.txt'. Archivos disponibles: "
            f"{_list_entries(_SANDBOX)}."
        )

    candidate = Path(path.strip())
    if candidate.is_absolute():
        return (
            f"Error recuperable: {path!r} es una ruta absoluta y no está "
            "permitida. Usá una ruta relativa al sandbox, por ejemplo 'data.txt'."
        )

    target = (_SANDBOX / candidate).resolve()
    if not target.is_relative_to(_SANDBOX):
        return (
            f"Error recuperable: {path!r} escapa del sandbox (p. ej. con '..'). "
            "Usá una ruta relativa que quede dentro del sandbox, "
            "por ejemplo 'data.txt'."
        )

    if target.is_dir():
        return (
            f"Error recuperable: {path!r} es un directorio, no un archivo. "
            f"Su contenido: {_list_entries(target)}. Elegí un archivo de esa lista."
        )

    if not target.exists():
        parent = target.parent
        if parent.is_dir() and parent.is_relative_to(_SANDBOX):
            return (
                f"Error recuperable: el archivo {path!r} no existe. "
                f"Archivos disponibles en ese directorio: {_list_entries(parent)}."
            )
        return (
            f"Error recuperable: ni el archivo {path!r} ni su directorio "
            f"existen. Archivos disponibles en el sandbox: {_list_entries(_SANDBOX)}."
        )

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return (
            f"Error: {path!r} existe pero no es texto UTF-8 legible "
            "(¿archivo binario?). Esta herramienta solo lee archivos de texto."
        )
    except OSError as exc:
        return f"Error leyendo {path!r}: {exc}"


file_reader_schema = ToolSchema.from_callable(file_reader)
