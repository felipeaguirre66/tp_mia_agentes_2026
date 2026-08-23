# Reporte de situación actual — Milestone 3

Fecha de cierre experimental: **2026-08-23**

Rama: **`m3-new-avances-en-harness`**

Checkpoint evaluado: **`210eb1fbbc52c20e90dbaccec6eb66b3f5890c53`**

Proveedor/modelo: **Ollama / `qwen3.6`**

## Resumen ejecutivo

El M3 está implementado y su suite experimental real terminó. Se conservaron **120 casos únicos** en siete JSONL, sin dry-runs, todos con el mismo modelo, proveedor y SHA. La infraestructura valida integridad, evita sobrescrituras, aplica timeout al caso completo mediante subprocess, calcula cohortes comparables y genera resultados cuantitativos y cualitativos reproducibles.

La suite de código queda en **165 tests verdes** y el dry-run recorrió **8/8 escenarios** sin crash. El baseline real resolvió **14/24 casos** (`pass@1=0,58`, `pass@3=0,88`). En el conjunto completo de brazos hubo **51/120 éxitos** (`pass@1=0,42`).

La anotación humana de las 10 trazas está completa y el acuerdo quedó persistido. El judge obtuvo acuerdo exacto de **60%/40%/40%** y acuerdo ±1 de **90%/60%/50%** en exploración, evidencia y recuperación. El informe obligatorio ya incorpora estos resultados y no conserva placeholders.

## Estado por componente

| Componente | Estado | Evidencia |
|---|---|---|
| Mundo y dataset de 8 escenarios | Completo | Dry-run 8/8 y tests de conformidad verdes. |
| Baseline final | Completo | Prompt especializado, memoria 40, 40 iteraciones y reparación textual activa. |
| Ablación de reparación | Completa | `repair_off`, misma configuración con reparación apagada. |
| Timeout real | Completo | Cada caso corre en subprocess; se observaron y persistieron timeouts reales a 300/600 s sin abortar la suite. |
| Presupuesto de tool calls | Completo | Permanece independiente del wall-clock. |
| Protección contra sobrescritura | Completa | `--out` usa creación exclusiva y conserva flush por caso. |
| `pass@k` y deltas | Completo | Agrupación por `(config, scenario)` y comparación sobre intersección exacta de escenarios. |
| Eficiencia/oráculo | Completo | Se conserva el óptimo oficial y se reporta `excess_tool_calls`; el overhead de `look` queda explícito. |
| Validación de JSONL | Completa | Rechaza duplicados, faltantes, dry-runs e identidades mezcladas. |
| Judge reproducible | Completo | Muestra determinística de 10 trazas y scores persistidos, sin reinvocar al generar el reporte. |
| Acuerdo humano | Completo | 30 scores válidos y comparación persistida en `reports/judge-agreement-20260822T225250Z.json`. |
| Resultados y manifiesto | Completo | Siete JSONL, comandos, tamaños y SHA-256 en `results/final-20260822T225250Z/`. |
| Informe obligatorio | Completo | Resultados, experimentos, trazas comentadas, acuerdo y limitaciones incorporados sin pendientes. |

## Resultados principales

### Baseline

| Dificultad/bloque | Éxitos | Casos |
|---|---:|---:|
| easy + medium | 7 | 9 |
| hard | 4 | 6 |
| extreme | 3 | 9 |
| **total** | **14** | **24** |

### Deltas contra baseline comparable

| Brazo | pass@1 brazo | pass@1 control | Delta |
|---|---:|---:|---:|
| Prompt genérico | 0,50 | 0,67 | −16,7 pp |
| Memoria 6 | 0,08 | 0,67 | −58,4 pp |
| Memoria 20 | 0,58 | 0,67 | −8,4 pp |
| `examine` no-op | 0,00 | 0,67 | −66,7 pp |
| 10 iteraciones | 0,00 | 0,67 | −66,7 pp |
| 20 iteraciones | 0,75 | 0,67 | +8,3 pp |
| Reparación apagada, 8 escenarios | 0,58 | 0,58 | 0,0 pp |

Los deltas son direccionales: cada brazo tiene tres repeticiones por escenario y no permite inferencia estadística fuerte. El experimento de reparación quedó especialmente afectado por errores XML del proveedor; aunque empató en pass@1, bajó de `pass@3=0,88` a `0,62`.

## Qué falló en las corridas reales

Hubo **69 fallos** en 120 casos:

| Causa primaria | Casos | Porcentaje de fallos |
|---|---:|---:|
| `crash` | 26 | 37,7 % |
| `budget_timeout` | 21 | 30,4 % |
| `max_iterations` | 14 | 20,3 % |
| `loop` | 5 | 7,2 % |
| `empty_response` | 3 | 4,3 % |

Los 26 crashes comparten principalmente un fallo de Ollama 0.31.1 al parsear XML de tool calls generado por `qwen3.6`: `element <function> closed by </parameter> (status code: 500)`. El harness los capturó y continuó, pero son una amenaza a la validez porque afectan de forma desigual las repeticiones.

Los 3 casos inicialmente `unclassified` fueron revisados manualmente. Todos eran respuestas vacías del LLM después de exploración parcial en `extreme-archive`; ahora se clasifican como `empty_response`. La evidencia está en `reports/unclassified-review-20260822T225250Z.md`.

## Artefactos

- Resultados crudos y manifiesto: `results/final-20260822T225250Z/`
- Reporte cuantitativo y cualitativo: `reports/m3-20260822T225250Z.md`
- Scores del judge: `reports/judge-scores-20260822T225250Z.json`
- Anotación humana: `reports/human-scores-20260822T225250Z.json`
- Acuerdo juez-humano: `reports/judge-agreement-20260822T225250Z.json`
- Revisión manual de fallos: `reports/unclassified-review-20260822T225250Z.md`

## Estado de cierre

El M3 está cerrado: implementación, 120 corridas reales, clasificación manual, evaluación cualitativa, acuerdo humano e informe obligatorio están completos. La suite local mantiene 165 tests verdes.
