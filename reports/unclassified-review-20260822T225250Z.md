# Revisión manual de casos inicialmente `unclassified`

Fuente: `results/final-20260822T225250Z/`. Revisión realizada después de completar los 120 casos; los JSONL crudos no fueron modificados.

Los tres casos comparten el mismo modo de fallo: el LLM devolvió una respuesta vacía, sin tool call estructurada ni texto, después de una exploración parcial. El bucle terminó con `status=ok`, respuesta `""` y el goal incumplido. Se incorporó la categoría automática `empty_response` para reflejar esta causa.

| configuración | escenario | repetición | llamadas | última acción | clasificación manual |
|---|---|---:|---:|---|---|
| `baseline` | `extreme-archive` | 0 | 2 | `examine(estanteria_archivo)` | `empty_response` |
| `baseline` | `extreme-archive` | 2 | 5 | `examine(expediente_1042)` | `empty_response` |
| `repair_off` | `extreme-archive` | 2 | 2 | `examine(estanteria_archivo)` | `empty_response` |

En los tres registros la razón del goal es `puerta principal está cerrada`; no hubo excepción del proveedor, `agent_error` ni respuesta textual reparable. Por eso no corresponden a `crash`, `max_iterations`, `text_tool_call` ni `premature_stop` con prosa.
