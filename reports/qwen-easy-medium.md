# Informe de evaluación — M3

Generado: 2026-08-23 21:56 UTC

## Corridas incluidas

| archivo | modelo | proveedor | git | casos | dry-run |
|---|---|---|---|---|---|
| qwen-easy-medium.jsonl | qwen2.5:7b-instruct | ollama | 8452f80 | 90 | False |

## Resultados

### Global

| grupo | n | pass@1 | pass@k | eficiencia | err. tools | calls (mediana) | latencia s |
|---|---|---|---|---|---|---|---|
| todo | 90 | 0.50 | 1.00 | 0.70 | 0.18 | 14.50 | 24.10 |

### Por dificultad

| grupo | n | pass@1 | pass@k | eficiencia | err. tools | calls (mediana) | latencia s |
|---|---|---|---|---|---|---|---|
| easy | 30 | 0.80 | 1.00 | 0.75 | 0.06 | 4.00 | 4.81 |
| medium | 60 | 0.35 | 1.00 | 0.64 | 0.23 | 17.00 | 32.20 |

### Por configuración

| grupo | n | pass@1 | pass@k | eficiencia | err. tools | calls (mediana) | latencia s |
|---|---|---|---|---|---|---|---|
| baseline | 9 | 0.67 | 1.00 | 0.72 | 0.18 | 14.00 | 20.20 |
| goal_gate_off | 9 | 0.44 | 0.67 | 0.76 | 0.13 | 11.00 | 16.47 |
| iters_10 | 9 | 0.33 | 0.33 | 0.75 | 0.09 | 10.00 | 8.33 |
| iters_20 | 9 | 0.44 | 0.67 | 0.76 | 0.19 | 15.00 | 21.54 |
| mem_20 | 9 | 0.89 | 1.00 | 0.66 | 0.16 | 14.00 | 24.44 |
| mem_40 | 9 | 0.67 | 0.67 | 0.72 | 0.20 | 14.00 | 25.52 |
| mem_6 | 9 | 0.00 | 0.00 | — | 0.27 | 40.00 | 54.62 |
| noop_examine | 9 | 0.00 | 0.00 | — | 0.14 | 23.00 | 155.68 |
| prompt_baseline | 9 | 0.89 | 1.00 | 0.62 | 0.20 | 15.00 | 20.65 |
| repair_on | 9 | 0.67 | 1.00 | 0.69 | 0.22 | 14.00 | 23.15 |

### Por escenario

| escenario | dif. | óptimo | n | pass@1 | pass@k | eficiencia | err. tools | calls (mediana) |
|---|---|---|---|---|---|---|---|---|
| study-with-key | easy | 3 | 30 | 0.80 | 1.00 | 0.75 | 0.06 | 4.00 |
| apartment-keys | medium | 7 | 30 | 0.20 | 1.00 | 0.38 | 0.33 | 20.00 |
| color-locks | medium | 11 | 30 | 0.50 | 1.00 | 0.74 | 0.14 | 14.50 |

## Análisis de errores

Casos fallidos: **45** de 90.

### Modo de fallo principal

| modo | casos | % | descripción |
|---|---|---|---|
| max_iterations | 40 | 88.90 | El bucle del agente alcanzó max_iterations. |
| hallucinated_id | 4 | 8.90 | Actuó sobre un id de objeto que no existe en el mundo. |
| unclassified | 1 | 2.20 | Fallo sin categoría automática: requiere revisión manual. |

### Todas las etiquetas (un caso puede tener varias)

| etiqueta | apariciones |
|---|---|
| max_iterations | 40 |
| loop | 36 |
| hallucinated_id | 32 |
| not_visible | 19 |
| navigation_lost | 12 |
| premature_stop | 4 |
| bad_tool_args | 1 |
| unclassified | 1 |

### Modo principal × dificultad

| dificultad | max_iterations | hallucinated_id | unclassified |
|---|---|---|---|
| easy | 6 | 0 | 0 |
| medium | 34 | 4 | 1 |

## Chequeos de invariantes

- Máximo de mensajes en una sola llamada al LLM: **40** (presupuestos configurados: [6, 20, 40]). Debe ser `<=` al presupuesto en todos los casos.
- Tool calls recuperadas de texto (experimento D): **0**. En los brazos con reparación apagada debe ser 0.

