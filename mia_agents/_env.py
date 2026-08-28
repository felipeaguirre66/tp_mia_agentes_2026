"""Carga de variables de entorno desde un archivo `.env` (sin dependencias).

`mia_agents` usa esto para que `LLMClient.from_env()` levante la
configuración de Bedrock/Ollama de un `.env` sin que el usuario tenga que
exportar variables a mano.

Política de seguridad (ver reglas del repo):
  - **No** se pisan variables ya presentes en el entorno: si corrés con
    `op run --env-file=.env -- ...`, los valores resueltos por 1Password
    ganan y este loader no los toca.
  - Los valores que son referencias `op://...` **sin resolver** se
    ignoran: nunca se inyecta un literal `op://` como si fuera un secreto.
    Para resolverlos, usá `op run --env-file=.env -- <comando>`.

Búsqueda del `.env` (primer match gana por clave, sin pisar):
  1. La ruta en `MIA_ENV_FILE`, si está definida.
  2. `.env` en el cwd y hasta 4 directorios hacia arriba.
  3. `.env` en la raíz del scaffold (el directorio padre de este paquete).
"""

from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = os.environ.get("MIA_ENV_FILE")
    if explicit:
        paths.append(Path(explicit))
    cwd = Path.cwd()
    for directory in [cwd, *list(cwd.parents)[:4]]:
        paths.append(directory / ".env")
    # Raíz del scaffold: padre del paquete mia_agents. Garantiza que el
    # `.env` se encuentre aunque el proceso corra desde otro directorio
    # (p. ej. el runner de eval en implementacion_ejemplo/M3).
    paths.append(Path(__file__).resolve().parent.parent / ".env")

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        try:
            resolved = resolved.resolve()
        except OSError:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].lstrip()
    if "=" not in line:
        return None
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()
    if value and value[0] in ("'", '"'):
        # Valor entre comillas: cortar en la comilla de cierre y descartar
        # cualquier comentario `# ...` que venga después (si no, queda
        # pegado al valor, p. ej. `"llama3.1"  # opcional` -> valor roto).
        end = value.find(value[0], 1)
        value = value[1:end] if end != -1 else value[1:]
    else:
        # Sin comillas: un `#` a un espacio de distancia es un comentario.
        for marker in (" #", "\t#"):
            idx = value.find(marker)
            if idx != -1:
                value = value[:idx]
        value = value.strip()
    if not key:
        return None
    return key, value


def load_env_files(force: bool = False) -> None:
    """Carga el primer `.env` encontrado en `os.environ` (idempotente)."""
    global _LOADED
    if _LOADED and not force:
        return
    _LOADED = True

    for path in _candidate_paths():
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw_line in content.splitlines():
            parsed = _parse_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            if key in os.environ:
                continue  # el entorno real (o `op run`) tiene prioridad
            if value.startswith("op://"):
                continue  # referencia 1Password sin resolver: la resuelve `op run`
            os.environ[key] = value
