"""Validación estructural de artefactos JSONL de evaluación.

Un reporte solo es comparable si todos sus archivos pertenecen al mismo
modelo, proveedor y commit, y si cada archivo contiene exactamente el
producto cartesiano que declara en su metadata.
"""

from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any

from eval.metrics import load_run


class ResultValidationError(ValueError):
    """Los resultados no son una cohorte completa y comparable."""


def _case_key(record: dict[str, Any]) -> tuple[str, str, int]:
    try:
        return (
            str(record["config"]),
            str(record["scenario"]),
            int(record["repeat"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultValidationError(
            f"Registro sin clave (config, scenario, repeat): {record!r}"
        ) from exc


def validate_result_files(
    paths: list[str | Path],
    *,
    allow_dry_run: bool = False,
) -> dict[str, Any]:
    """Valida metadata, completitud y unicidad de uno o más JSONL."""
    if not paths:
        raise ResultValidationError("No se proporcionaron archivos de resultados.")

    identities: dict[str, set[Any]] = {
        "provider": set(),
        "model": set(),
        "git_sha": set(),
    }
    global_keys: set[tuple[str, str, int]] = set()
    files: list[dict[str, Any]] = []

    for raw_path in paths:
        path = Path(raw_path)
        meta, records = load_run(path)
        if not meta:
            raise ResultValidationError(f"{path}: falta la línea _meta.")
        if meta.get("dry_run") and not allow_dry_run:
            raise ResultValidationError(f"{path}: es una corrida --dry-run.")

        for field, values in identities.items():
            value = meta.get(field)
            if value is not None:
                values.add(value)

        scenarios = [str(x) for x in (meta.get("scenarios") or [])]
        configs = [str(x) for x in (meta.get("configs") or {}).keys()]
        repeats = meta.get("repeats")
        if not scenarios or not configs or not isinstance(repeats, int) or repeats < 1:
            raise ResultValidationError(
                f"{path}: metadata incompleta; requiere scenarios, configs y repeats>=1."
            )

        expected = {
            (config, scenario, repeat)
            for config, scenario, repeat in product(configs, scenarios, range(repeats))
        }
        actual_list = [_case_key(record) for record in records]
        actual = set(actual_list)
        if len(actual) != len(actual_list):
            raise ResultValidationError(f"{path}: contiene casos duplicados.")
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing or unexpected:
            raise ResultValidationError(
                f"{path}: cohorte incompleta; faltan={missing[:5]}, "
                f"inesperados={unexpected[:5]}."
            )

        overlap = global_keys & actual
        if overlap:
            raise ResultValidationError(
                f"{path}: repite casos presentes en otro archivo: {sorted(overlap)[:5]}."
            )
        global_keys.update(actual)
        files.append(
            {
                "path": str(path),
                "n_records": len(records),
                "configs": configs,
                "scenarios": scenarios,
                "repeats": repeats,
                "dry_run": bool(meta.get("dry_run")),
            }
        )

    mixed = {field: sorted(values, key=str) for field, values in identities.items() if len(values) > 1}
    if mixed:
        raise ResultValidationError(f"Metadata incompatible entre archivos: {mixed}.")

    identity = {
        field: next(iter(values), None) for field, values in identities.items()
    }
    return {
        **identity,
        "n_files": len(files),
        "n_cases": len(global_keys),
        "files": files,
    }
