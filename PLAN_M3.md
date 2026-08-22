# Plan paso a paso — Milestone 3

> **Actualización 2026-08-22.** Este documento conserva el plan de diseño
> original. La capa `eval/`, los cuatro experimentos, el judge, el reporte,
> el timeout aislado y sus tests ya están implementados. Lo pendiente es la
> corrida final con Ollama, la anotación humana y completar los resultados de
> `INFORME_OBLIGATORIO_M3.md`.

---

## Fase 0 — Preparación (≈30 min)

**0.1. Decidir el modelo y fijarlo.** El `.env` tiene Ollama (`llama3.1`) y
Bedrock (`nova-lite`). Elegí uno como *modelo principal* de todos los números
del informe y dejalo escrito. Recomendación: Bedrock nova-lite si tenés
credenciales estables (más determinista, tokens reportados), Ollama si querés
correr gratis muchas repeticiones. El segundo proveedor sirve como experimento
opcional "sensibilidad al modelo".

**0.2. Smoke test end-to-end.** Antes de construir nada:

```bash
python -m mia_world.cli list
python -m mia_world.cli run --scenario easy
```

Esto va a fallar o resolver mal, porque `build_agent()` no registra las tools
del mundo ni tiene un system prompt de sala de escape. Ese fallo es el punto
de partida — anotalo, es material para la sección "Aproximación" del informe.

**0.3. Crear el esqueleto de directorios.**

```
eval/
  run.py            # entrypoint único: python eval/run.py
  harness.py        # ejecuta 1 caso y devuelve un registro
  metrics.py        # métricas cuantitativas
  judge.py          # LLM-as-judge / rúbrica
  experiments.py    # configuraciones de los experimentos
  analysis.py       # agrega runs -> tablas del informe
results/            # JSONL crudos por corrida (gitignoreado si pesa)
reports/            # informe generado + tablas
```

---

## Fase 1 — Adaptar el agente al problema (≈1-2 h)

Clave: **no romper M1/M2**. `tests/conformance/test_m1.py` y `test_m2.py`
tienen que seguir pasando. Corré `pytest tests/` antes y después.

**1.1. `build_agent(config)` acepta las tools del mundo.** Hoy registra
calculator/file_reader/word_counter, que en un escenario de sala de escape son
ruido puro para el modelo (y encima el enunciado pide un experimento de
"sustituir una herramienta por un no-op"). Cambio mínimo y compatible:

- Si `config` trae `"world"`, registrar `make_world_tools(world)` y **no**
  registrar las tools de juguete.
- Si no, comportarse como hoy (los tests de conformidad siguen verdes).
- Exponer también en `config`: `system_prompt`, `max_iterations`,
  `max_history_messages`.

Ojo: el CLI (`mia_world/cli.py`) llama `build_agent()` sin config y registra
las tools él mismo — con el cambio de arriba, el agente terminaría con
calculator + look/examine/take/use. Para el eval no uses el CLI: usá tu propio
harness (paso 2.1) que construye el agente con `config={"world": world}`.

**1.2. System prompt especializado.** Es la especialización principal que vas a
reportar en la sección 1 del informe. Debe cubrir, como mínimo:

- Rol: estás en una sala de escape, objetivo = abrir `puerta_principal`.
- Protocolo: **siempre `look` primero**; usar los **ids** entre corchetes, no
  los nombres en prosa; `use <item_inventario> <target_sala>`.
- En multi-sala: recordar el mapa, las salidas y de qué sala venís.
- Regla anti-alucinación: nunca declares éxito sin que una tool lo confirme.
- Terminar con texto libre (sin tool_calls) cuando la puerta esté abierta.

Guardalo en `student_framework/prompts.py` con **al menos dos variantes**
(`BASELINE` genérico, `ESCAPE_V1` especializado) — eso ya es el Experimento A.

**1.3. Subir `max_iterations` y `max_history_messages`.** Los defaults (10 y
10) no alcanzan: `vault-combination` necesita 21 tool calls óptimas.
Usá `max_iterations≈40` y `max_history_messages≈40` como base del run
principal, y dejá ambos parametrizables — son la palanca del Experimento C.

**Riesgo conocido a documentar:** tu `_trim_messages` puede cortar un
`assistant` con `tool_calls` dejando su `tool` huérfano (lo mitigás con
`_drop_leading_orphan_tools`, pero solo al frente). En horizontes de 20+ pasos
esto se va a activar. Verificalo explícitamente — es un hallazgo de primera
para el análisis de errores.

---

## Fase 2 — Infraestructura de evaluación (≈2-3 h)

**2.1. `eval/harness.py::run_case(scenario, config) -> dict`.** Un caso =
un escenario × una configuración × una semilla. Debe:

1. `load_scenario(path)` → `world = scenario.initial_world` (mundo fresco por
   caso; **nunca** reusar un `World` entre casos).
2. `agent = build_agent({"world": world, ...config})`.
3. Envolver cada tool con un *wrapper de traza* que registre
   `(n, nombre, args, output, error, timestamp)` — no confíes solo en
   `result.steps`, querés también los timings y el estado del mundo.
4. `t0 = perf_counter()`, `result = agent.run(scenario.user_message)`.
5. `achieved, reason = check_goal(world, scenario.goal)`.
6. Devolver un registro plano y serializable: scenario_id, difficulty, config
   name, seed, `goal_achieved`, `goal_reason`, `n_tool_calls`, `n_tool_errors`,
   `optimal_calls`, latencia total, `input_tokens`/`output_tokens`,
   `agent.answer`, la traza completa, y `error` del `AgentResult`.
7. **Try/except alrededor de todo**: una excepción del proveedor no puede
   tumbar la corrida entera; se registra como caso fallido con
   `failure="crash"`.

**2.2. Presupuesto duro por caso.** Además de `max_iterations`, poné un
timeout de wall-clock (p. ej. 300 s) y un tope de tool calls. Sin esto, un
loop en `extreme-archive` te come la tarde.

**2.3. `eval/run.py`.** Entrypoint reproducible sin pasos manuales
(requisito explícito del enunciado). Flags:
`--scenarios all|easy|...`, `--config baseline|...`, `--repeats N`,
`--out results/<timestamp>.jsonl`, `--dry-run` (con un mock LLM, para testear
el harness sin gastar tokens ni tiempo). Escribí **JSONL append-only**: si
crashea a mitad, no perdés lo corrido. Guardá en el header del archivo:
modelo, git SHA, fecha, config completa.

**2.4. Test del harness con el mock.** Usá `mia_agents/testing/mock_llm.py`
para un test que scriptee la secuencia ganadora de `study-with-key` y verifique
que el harness reporta `goal_achieved=True`, 3 tool calls y traza completa.
Esto valida la infra antes de gastar en LLM real.

---

## Fase 3 — Métricas (≈1-2 h)

**3.1. Cuantitativas** (justificá cada una en el informe):

- **Task success rate / pass@k** sobre `check_goal`. Es *la* métrica: el
  enunciado subraya que la meta se mide sobre el estado del mundo, no sobre el
  texto. Con `--repeats k` reportás `pass@1` (media) y `pass@k` (¿resolvió
  alguna vez?) — la brecha entre ambos mide la **inconsistencia** del agente,
  que es información distinta del promedio.
- **Eficiencia de acciones** = `optimal_calls / tool_calls_usadas` (los óptimos
  están tabulados en el enunciado). Distingue "resolvió" de "resolvió bien":
  un agente que hace 30 calls para un óptimo de 3 está a un `max_iterations`
  de fallar.
- **Coste/latencia**: tokens in/out por caso (ya los acumula tu `AgentResult`)
  y segundos. Necesarios para el escenario `extreme-archive`, cuyo argumento
  central es que no cabe en contexto.
- **Tool-error rate** = tool calls con `error` / total. Proxy directo de
  disciplina de tool-calling (ids inventados, args mal formados).

Reportá siempre **por dificultad**, no solo el agregado: el promedio global
oculta que easy es 100% y extreme 0%.

**3.2. Cualitativa (rúbrica + LLM-as-judge).** Sugerencia: **calidad del
proceso de razonamiento**, sobre la traza, 1-5 en 3 ejes:

- *Sistematicidad de la exploración* (¿`look` antes de actuar, examina
  contenedores en orden, o prueba al azar?).
- *Uso de la evidencia* (¿usa lo que la tool le devolvió, o inventa ids?).
- *Recuperación de errores* (tras un error de tool, ¿corrige o repite igual?).

Por qué esta dimensión: dos corridas con el mismo `goal_achieved=False` pueden
ser radicalmente distintas (una a un paso del éxito, otra en loop). El binario
no lo distingue.

Implementación: `eval/judge.py` con `agent.structured_call(prompt, RubricSchema)`
— reusás la salida estructurada de M2, lo cual es un buen argumento para el
informe ("el judge no es infra nueva, es M2 aplicado"). Definí un
`RubricScore(pydantic.BaseModel)` con los 3 ejes + `justification: str`.
**Validá el judge**: puntuá a mano 8-10 trazas y reportá el acuerdo con el
judge. Sin eso, un número de LLM-as-judge no vale nada, y decirlo es un punto
a favor en "Limitaciones".

---

## Fase 4 — Corrida principal (≈1-2 h de cómputo)

8 escenarios × 3 repeticiones × config baseline. Corré primero
`easy`+`medium` para validar, después el resto. Guardá los JSONL.
Espera razonable: easy/medium alto, hard mixto, extreme mayormente fallo —
y eso está bien, el enunciado espera que `extreme-archive` no entre.

---

## Fase 5 — Análisis de errores (≈1-2 h)

**5.1. Taxonomía de fallos.** Etiquetá cada caso fallido con una categoría
(mecánicamente donde se pueda, a mano donde no). Punto de partida esperable
en este mundo:

| Categoría | Señal en la traza |
|---|---|
| `context_overflow` | Prompt excede la ventana / degradación tras N tokens (extreme-archive) |
| `history_truncation` | Perdió un hecho ya observado y lo re-descubre o lo contradice |
| `hallucinated_id` | `examine`/`take` sobre un id que ninguna tool devolvió |
| `no_exploration` | Intenta `use` sin `look`/`examine` previos |
| `loop` | Misma (tool, args) ≥3 veces sin cambio de estado |
| `wrong_order` | Abrió `puerta_principal` sin el documento (office-sequence) |
| `navigation_lost` | `go` a dirección inexistente, o no vuelve a la sala de la puerta |
| `premature_stop` | Devolvió texto final declarando éxito con `check_goal=False` |
| `budget_exhausted` | `max_iterations` alcanzado con progreso real |
| `crash` | Excepción del proveedor / tool |

Escribí un clasificador heurístico en `analysis.py` (detectar loops e ids
inventados es trivial y automatizable) y revisá manualmente el resto.

**5.2. Salida:** tabla categoría × dificultad + 2-3 trazas comentadas como
casos de estudio. `premature_stop` es especialmente jugoso: es exactamente la
diferencia entre medir el texto y medir el estado del mundo.

---

## Fase 6 — Experimentos (≈2-3 h) — mínimo 2, hacé 3

Cada uno: hipótesis escrita **antes** de correr, mismo harness, misma semilla,
solo cambia una variable.

- **A. Prompting: genérico vs especializado.** `BASELINE` (el system prompt
  actual de `MyAgent`) vs `ESCAPE_V1`. Hipótesis: el especializado sube el
  success rate en medium/hard y baja `hallucinated_id`. Es el experimento de
  mayor señal esperada y el más barato.
- **B. Memoria: ventana corta vs larga.** `max_history_messages` ∈ {6, 20, 40}.
  Hipótesis: en `apartment-keys` y `backtracking-vault` la ventana corta
  destruye el desempeño (hay que recordar el mapa a lo largo de decenas de
  mensajes), mientras que en `study-with-key` es indiferente. Esto mide
  directamente el valor de tu trabajo de M2 sobre *este* problema.
- **C. Tool no-op / presupuesto.** Dos variantes baratas: (i) reemplazar
  `examine` por un no-op que devuelve "no ves nada especial" — debería
  colapsar todo lo que dependa de contenedores; (ii) `max_iterations` ∈
  {10, 20, 40} para separar "no sabe" de "no le alcanzó el presupuesto".

- **D. Reparación de tool calls textuales.** *(Añadido tras la primera corrida
  real.)* `llama3.1:8b` emite a veces la siguiente acción como JSON dentro de
  `content` en vez de como `tool_call` estructurada; el bucle ve
  `tool_calls == []`, lo toma por respuesta final y corta. El brazo de control
  es el agente actual; el brazo tratado detecta ese JSON en `content` y lo
  re-inyecta como tool call. Hipótesis: sube el success rate en todas las
  dificultades y hace caer `text_tool_call` y `premature_stop`. Es el
  experimento más directo sobre "qué parte de tu framework importa", porque
  toca el bucle, no el prompt.

**Extra de bajo costo y alto rédito**, si te queda tiempo: el enunciado
sugiere explícitamente *planner explícito vs ReAct puro* en `office-sequence`.
Un pre-paso con `structured_call` que devuelva un plan de sub-objetivos
ordenado, inyectado en el prompt, contra el ReAct puro. Ahí es donde el goal
`sequence` premia planificar.

Reportá cada experimento con Δ absoluto, no solo "mejoró": N es chico (8
escenarios × 3 repeticiones), así que **decí explícitamente que las
diferencias no son estadísticamente significativas** y tratá los resultados
como direccionales. Eso vale más que un número inflado.

---

## Fase 7 — Informe (≈2 h)

`INFORME_OBLIGATORIO_M3.md`, siguiendo las 5 secciones exigidas:

1. **Aproximación** — qué de M1+M2 se reusó tal cual (loop ReAct, retries
   transitorios, sliding window, `structured_call`), qué se especializó
   (system prompt, registro de tools del mundo, presupuestos) y qué se
   construyó nuevo (harness, judge). Sé explícito en que el core del framework
   no se tocó — es un argumento de calidad de diseño.
2. **Métricas** — las de la Fase 3, con la justificación de cada elección y
   cómo se computa (fórmula + dónde vive el código).
3. **Resultados** — tabla principal por escenario y por dificultad; tabla de
   modos de fallo; scores de rúbrica; el acuerdo judge-vs-humano.
4. **Experimentos** — hipótesis / cambio / resultado / conclusión, uno por
   bloque, con la advertencia sobre N.
5. **Limitaciones** — N chico, un solo modelo (y chico: `llama3.1:8b`), judge
   no validado a fondo, sin resumen jerárquico para `extreme-archive`.
   *(Nota: la sospecha inicial de que `_trim_messages` rompía pares
   tool_call/tool se verificó y es infundada — el recorte es un corte de
   sufijo, así que los huérfanos solo aparecen al frente y
   `_drop_leading_orphan_tools` los limpia. No la listes como limitación.)* Y qué construirías: memoria con resumen
   (scratchpad de hechos observados en vez de ventana de mensajes),
   sub-agente de búsqueda para el archivo de 20 expedientes, planner explícito.

---

## Orden de ejecución recomendado

Fase 0 → 1 → 2 → **2.4 (test con mock)** → 3 → 4 (corrida chica: easy+medium) →
verificar que las métricas salen bien → 4 completo → 5 → 6 → 7.

El error más común acá es construir todo el eval y descubrir recién al final
que el agente no registra bien las tools o que el harness reusa el `World`
entre casos. Por eso 2.4 va antes de gastar en la corrida real.
