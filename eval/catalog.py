"""Metadatos del dataset de escenarios.

Los óptimos están tabulados en `ENUNCIADO_M3.md` (columna "Optimal"). Los
guardamos acá para poder computar eficiencia de acciones sin hardcodearlos
en el análisis.
"""

from __future__ import annotations

from pathlib import Path

from mia_world import Scenario, list_scenarios, load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = REPO_ROOT / "scenarios"

#: id de escenario -> número mínimo de tool calls para resolverlo.
OPTIMAL_CALLS: dict[str, int] = {
    "study-with-key": 3,
    "color-locks": 11,
    "apartment-keys": 7,
    "library-search": 7,
    "office-sequence": 13,
    "extreme-archive": 4,
    "vault-combination": 21,
    "backtracking-vault": 18,
}

#: Peor caso de una búsqueda exhaustiva (columna "Brute-force peor caso").
BRUTE_FORCE_CALLS: dict[str, int | None] = {
    "study-with-key": 3,
    "color-locks": 11,
    "apartment-keys": 7,
    "library-search": 13,
    "office-sequence": 13,
    "extreme-archive": None,  # no cabe en 16K tokens de contexto
    "vault-combination": 21,
    "backtracking-vault": 18,
}

DIFFICULTY_ORDER = ["easy", "medium", "hard", "extreme"]


def all_scenarios(scenarios_dir: Path | None = None) -> list[Scenario]:
    """Todos los escenarios del dataset, ordenados por dificultad."""
    scenarios = list_scenarios(scenarios_dir or SCENARIOS_DIR)
    return sorted(
        scenarios,
        key=lambda sc: (
            DIFFICULTY_ORDER.index(sc.difficulty)
            if sc.difficulty in DIFFICULTY_ORDER
            else len(DIFFICULTY_ORDER),
            sc.id,
        ),
    )


def resolve_scenarios(spec: str, scenarios_dir: Path | None = None) -> list[Scenario]:
    """Resuelve `spec` a una lista de escenarios.

    Acepta ``"all"``, una dificultad (``"easy"``, ``"extreme"``, ...), un id
    concreto, un path a un JSON, o varios de estos separados por comas.
    A diferencia del CLI de `mia_world`, una dificultad devuelve **todos**
    los escenarios de esa dificultad, no solo el primero.
    """
    directory = scenarios_dir or SCENARIOS_DIR
    available = all_scenarios(directory)
    by_id = {sc.id: sc for sc in available}

    selected: list[Scenario] = []
    seen: set[str] = set()

    for token in (t.strip() for t in spec.split(",") if t.strip()):
        if token == "all":
            matches = available
        elif token in by_id:
            matches = [by_id[token]]
        elif token in DIFFICULTY_ORDER:
            matches = [sc for sc in available if sc.difficulty == token]
        elif Path(token).is_file():
            matches = [load_scenario(Path(token))]
        else:
            opciones = ", ".join(sorted(by_id))
            raise SystemExit(
                f"No se encontró el escenario {token!r}. Disponibles: {opciones}, "
                f"o una dificultad ({', '.join(DIFFICULTY_ORDER)}), o 'all'."
            )
        for sc in matches:
            if sc.id not in seen:
                seen.add(sc.id)
                selected.append(sc)

    if not selected:
        raise SystemExit(f"La selección {spec!r} no coincide con ningún escenario.")
    return selected


def fresh_scenario(scenario_id: str, scenarios_dir: Path | None = None) -> Scenario:
    """Recarga un escenario desde disco.

    Cada caso necesita un `World` virgen: las tools mutan el mundo en sitio,
    así que reutilizar la misma instancia entre repeticiones contaminaría los
    resultados (la puerta ya abierta de la corrida anterior).
    """
    directory = scenarios_dir or SCENARIOS_DIR
    for path in sorted(directory.glob("*.json")):
        sc = load_scenario(path)
        if sc.id == scenario_id:
            return sc
    raise KeyError(f"No existe el escenario {scenario_id!r} en {directory}.")
