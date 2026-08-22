"""Infraestructura de evaluación del Milestone 3.

Entrypoint reproducible::

    python eval/run.py --scenarios all --config baseline --repeats 3

Módulos:
  - `catalog`  — metadatos de los escenarios (óptimos, orden, resolución de ids).
  - `tracing`  — envoltorio de tools que registra la traza y aplica presupuestos.
  - `harness`  — ejecuta UN caso (escenario × config × semilla) y lo serializa.
  - `configs`  — registro de configuraciones nombradas (baseline + brazos).
  - `fake_llm` — clientes LLM falsos para testear la infra sin gastar tokens.
  - `run`      — CLI que orquesta la matriz de casos y escribe JSONL.
"""
