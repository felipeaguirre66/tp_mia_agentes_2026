# Informe M3 — Evaluación sobre el problema de sala de escape

> **Estado actual: corrida completa con señal real.** Los números de este
> informe provienen de una corrida real con Ollama (no `--dry-run`) sobre los
> 8 escenarios del dataset, `baseline` + 4 experimentos, 3 repeticiones por
> celda (120 casos). A diferencia de una corrida anterior (descartada, ver
> nota abajo) que había dado 0/120 con `hermes3:8b`, esta corrida con
> `qwen2.5:7b-instruct` sí resuelve una fracción no trivial de los casos
> (pass@1 global 0,24; 1,00 en `easy`) y los experimentos muestran diferencias
> direccionales entre brazos.

Modelo de todos los números: `qwen2.5:7b-instruct` vía Ollama.
Corrida principal: `results/suite-20260823T224137Z/*.jsonl` (baseline-a/b/c +
exp-a/b/c/d). Informes generados: `reports/suite-20260823T224137Z.md`
(métricas) y `reports/suite-20260823T224137Z-judged.md` (+ rúbrica LLM,
12 trazas).

*Nota histórica*: una corrida anterior con `hermes3:8b` y otra con `llama:3.1` sobre`results/validate.jsonl` y un suite previo dio 0 objetivos cumplidos en
todos los brazos. Se descarta como número a citar (el modelo no sostenía ni
la disciplina básica de tool-calling) pero se mantiene como evidencia de que
el harness discrimina entre modelos: el mismo código, con otro LLM, pasó de
0% a resolver `easy` al 100% y partes de `medium`/`extreme`.

---

## 1. Aproximación

**Qué se reusó sin tocar.** El núcleo de M1+M2 resolvió el problema sin
modificaciones: el bucle ReAct de `MyAgent.run`, el reintento de fallos
transitorios (`_call_with_retry`) y la memoria de ventana deslizante
(`_trim_messages`). `structured_call` **no** interviene en la resolución de
escenarios — el agente que juega usa exclusivamente `run()`, tool-calling
plano — pero sí se reusa, sin modificar, como motor del juez cualitativo
(`eval/judge.py`, §2.2): ahí es donde M2 se reaprovecha, en la
infraestructura de evaluación, no en el agente que resuelve la sala.

**Qué se especializó.** Tres cosas, todas por configuración, ninguna
rompiendo el contrato de M1/M2:

1. **`build_agent` con modo mundo.** Si `config` trae `"world"`, registra
   los verbos de `mia_world.make_world_tools(world)`. Sin `"world"`, el
   comportamiento es exactamente el de M2: los 124 tests de conformidad no
   se enteran del cambio.
2. **System prompt de dominio** (`student_framework/prompts.py`,
   `ESCAPE_V1`): protocolo de exploración (`look` primero, `examine` sobre
   contenedores), uso obligatorio de los ids entre corchetes, memoria del
   mapa en escenarios multi-sala, respeto del orden en goals compuestos, y
   la regla anti-alucinación de no declarar éxito sin confirmación de una
   herramienta. Se conserva `BASELINE` (el prompt genérico de M2) como
   brazo de control del experimento A.
3. **Presupuestos.** Los defaults de M2 (`max_iterations=10`,
   `max_history_messages=10`) hacen imposible el dataset: `vault-combination`
   necesita 21 tool calls óptimas. El modo mundo usa 40/40. `max_iterations`
   limita **rondas de `chat()`** en `MyAgent.run` (el `for _ in
   range(self._max_iterations)` de `agent.py`), no llamadas a tools
   directamente: si el LLM devuelve varios `tool_calls` en una misma
   respuesta, esa ronda cuenta una sola vez contra el presupuesto aunque
   ejecute varias tools. Si se agotan las rondas sin una respuesta final,
   el bucle sale por el `else` del `for` y registra
   `error="Se alcanzó el máximo de iteraciones"` — es la causa del 89/91 de
   los fallos etiquetados `max_iterations` en §3.4.

**Qué se construyó nuevo.** El paquete `eval/`: harness, presupuestos duros,
trazado, métricas, taxonomía de fallos, LLM-as-judge e informe. Es
infraestructura de evaluación.

**Una modificación al agente**, gateada y apagada por defecto:
`repair_textual_tool_calls` (ver experimento D). El baseline corre con el
bucle ReAct clásico.

### Decisiones de diseño del harness que condicionan los números

- **El mundo se recarga de disco en cada caso.** Las tools mutan el `World`
  en sitio y `Scenario.initial_world` es una instancia única, no una
  plantilla. Reutilizarla entre repeticiones daría éxitos gratis heredados
  de la corrida anterior — un bug silencioso que solo infla hacia arriba y
  que contaminaría también la comparación entre brazos experimentales.
  `run_case` llama `fresh_scenario()` siempre, incluso si recibe un
  `Scenario` ya cargado: la API no se puede usar mal.
- **La tasa de error de tools no se lee de `AgentStep.error`.** Las tools de
  `mia_world` no lanzan excepciones: ante un id inexistente devuelven un
  string `"Error: ..."`. `AgentStep.error` queda en `None` aunque el agente
  esté alucinando ids sin parar. El tracer detecta el fallo por el prefijo
  del output.
- **Presupuestos duros además de `max_iterations`**: tope de tool calls y
  wall-clock por caso, implementados con una excepción que hereda de
  `BaseException` para que el `except Exception` del bucle del agente no la
  degrade a un tool error cualquiera.

---

## 2. Métricas

### 2.1 Cuantitativas

| Métrica | Definición | Por qué esta |
|---|---|---|
| **pass@1** | `check_goal(world, goal)` promediado sobre casos | Se computa sobre el **estado del mundo**, no sobre el texto del agente: un agente podría declarar éxito en prosa sin haber abierto nada, y esa afirmación no debe contar (el clasificador de `premature_stop` en `eval/failures.py` existe justamente para detectar ese caso, aunque no se disparó en esta corrida). |
| **pass@k** | ¿resolvió el escenario en *alguna* de sus k repeticiones? | La brecha `pass@k − pass@1` mide **inconsistencia**. 1/3 y 3/3 no son el mismo agente aunque el promedio los mezcle. |
| **Eficiencia de acciones** | `optimal_calls / tool_calls`, solo sobre casos resueltos | Separa "resolvió" de "resolvió bien". Resolver en 30 calls algo de óptimo 3 es estar a un `max_iterations` del fracaso. Los óptimos son los tabulados en el enunciado. |
| **Tool-error rate** | tool calls con output de error / total | Proxy directo de disciplina de tool-calling: ids inventados, objetos no visibles, argumentos mal nombrados. |
| **Coste y latencia** | tokens in/out y segundos por caso | Imprescindible para argumentar sobre `extreme-archive`, cuyo diseño es no caber en contexto. |

Todo se reporta **por dificultad**, no solo agregado: un promedio que mezcla
un `easy` al 100% con un `extreme` al 0% no describe a ninguno de los dos.

### 2.2 Cualitativa — rúbrica vía LLM-as-judge

Dos casos con `goal_achieved=False` pueden ser radicalmente distintos: uno a
una acción del éxito, otro repitiendo `look` veinte veces. La métrica binaria
los iguala. La rúbrica puntúa el **proceso**, en tres ejes de 1 a 5:

1. `exploracion` — ¿observa antes de actuar y explora sistemáticamente?
2. `uso_evidencia` — ¿actúa sobre ids que las herramientas reportaron, o inventa?
3. `recuperacion` — tras un error, ¿corrige o insiste con lo mismo?

Implementado con `structured_call` de M2 (`eval/judge.py`): el juez no es
infraestructura nueva, es M2 aplicado a un problema de evaluación.

**Corrida del juez.** `python eval/report.py results/suite-20260823T224137Z/*.jsonl
--judge --judge-limit 12 -o reports/suite-20260823T224137Z-judged.md` puntuó
las primeras 12 trazas del suite (las 3 repeticiones de `study-with-key`,
`apartment-keys` y `color-locks`, más 3 de `library-search`; 12/12 sin error
del juez). Separando por si el caso cumplió el goal o no:

| Grupo | n | exploración | uso_evidencia | recuperación |
|---|---:|---:|---:|---:|
| Casos resueltos | 8 | 4,50 | 4,63 | 4,00 |
| Casos fallidos | 4 | 3,25 | 2,25 | 1,50 |

La brecha es mayor en `uso_evidencia` y `recuperacion` que en `exploracion`:
el agente explora razonablemente incluso cuando pierde (3,25/5), pero en los
casos fallidos actúa sobre evidencia más floja y, sobre todo, no corrige tras
un error (1,50/5 vs 4,00/5). Esto es consistente con la taxonomía de fallos
de §3.1, donde `loop` (repetir la misma llamada fallida) aparece en 80 de
91 casos fallidos: la rúbrica cualitativa y el clasificador automático
apuntan al mismo síntoma por dos caminos independientes.

---

## 3. Resultados

Corrida completa: `results/suite-20260823T224137Z/` — `baseline` (los 8
escenarios, 3 repeticiones) + 4 experimentos (`prompt_baseline`, `mem_6`,
`mem_20`, `noop_examine`, `iters_10`, `iters_20`, `repair_on`), 120 casos en
total. Informe completo: `reports/suite-20260823T224137Z.md`.

### 3.1 Global y por dificultad

| grupo | n | pass@1 | pass@k | eficiencia | err. tools | calls (mediana) | latencia s | tokens in | tokens out |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **todo** | 120 | 0,24 | 0,62 | 0,56 | 0,32 | 24 | 99,2 | 67 782 | 4 364 |
| easy | 6 | 1,00 | 1,00 | 0,75 | 0,00 | 4 | 5,0 | 6 437 | 145 |
| medium | 48 | 0,38 | 1,00 | 0,57 | 0,22 | 19 | 34,9 | 51 252 | 8 145 |
| hard | 48 | 0,04 | 0,50 | 0,35 | 0,41 | 28 | 117,8 | 73 765 | 1 797 |
| extreme | 18 | 0,17 | 0,33 | 0,24 | 0,46 | 29 | 163,8 | 116 359 | 2 534 |

El agregado global (pass@1 = 0,24) es engañoso por sí solo, tal como advierte
§2.1: describe un punto intermedio entre un `easy` que satura (1,00) y un
`hard` casi en cero (0,04). El patrón por dificultad es monótono en pass@1 y
eficiencia salvo por `extreme` (0,17), que queda por encima de `hard` — el
responsable es `extreme-archive` (ver por-escenario abajo), no una mejora
real de la dificultad `extreme` en su conjunto. El costo de tokens de entrada
escala con la dificultad de forma mucho más pronunciada que la latencia
mediana de tool calls (6,4 K en `easy` vs 116 K en `extreme`, ~18×): es la
evidencia cuantitativa de que `extreme-archive` está diseñado para presionar
la ventana de contexto, tal como pide el enunciado.

### 3.2 Por configuración

| config | n | pass@1 | pass@k | eficiencia | err. tools | calls (mediana) | latencia s |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 24 | 0,46 | 0,62 | 0,52 | 0,36 | 24 | 138,4 |
| prompt_baseline | 12 | 0,58 | 0,75 | 0,50 | 0,33 | 27,5 | 77,7 |
| mem_6 | 12 | 0,00 | 0,00 | — | 0,21 | 40 | 45,0 |
| mem_20 | 12 | 0,17 | 0,25 | 0,76 | 0,43 | 31 | 102,4 |
| noop_examine | 12 | 0,00 | 0,00 | — | 0,15 | 26 | 142,9 |
| iters_10 | 12 | 0,00 | 0,00 | — | 0,26 | 10 | 11,0 |
| iters_20 | 12 | 0,17 | 0,50 | 0,58 | 0,28 | 18,5 | 33,8 |
| repair_on | 24 | 0,29 | 0,38 | 0,61 | 0,40 | 25 | 146,7 |

(Análisis de cada fila en la §4, junto con la hipótesis que la motivó.)

### 3.3 Por escenario

| escenario | dif. | óptimo | n | pass@1 | pass@k | eficiencia | err. tools | calls (mediana) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| study-with-key | easy | 3 | 6 | 1,00 | 1,00 | 0,75 | 0,00 | 4 |
| color-locks | medium | 11 | 24 | 0,50 | 1,00 | 0,64 | 0,18 | 17 |
| apartment-keys | medium | 7 | 24 | 0,25 | 1,00 | 0,43 | 0,25 | 19 |
| library-search | hard | 7 | 24 | 0,00 | 0,00 | — | 0,50 | 26 |
| office-sequence | hard | 13 | 24 | 0,08 | 1,00 | 0,35 | 0,32 | 30 |
| extreme-archive | extreme | 4 | 6 | 0,50 | 1,00 | 0,24 | 0,48 | 19,5 |
| backtracking-vault | extreme | 18 | 6 | 0,00 | 0,00 | — | 0,44 | 30,5 |
| vault-combination | extreme | 21 | 6 | 0,00 | 0,00 | — | 0,45 | 36,5 |

`study-with-key` (óptimo 3) satura. `apartment-keys` (multi-sala) queda muy
por debajo de `color-locks` (cadena de cofres en una sola sala) pese a tener
menor óptimo (7 vs 11): confirma la advertencia del enunciado de que navegar
y recordar el mapa es una carga aparte de la profundidad del puzzle.
`office-sequence` (goal `sequence`) resuelve pass@k = 1,00 pero pass@1 = 0,08:
alguna corrida cumplió el orden correcto, pero es la excepción, no la regla —
consistente con que planificar sub-objetivos ordenados es justamente lo que
el enunciado señala como difícil para un ReAct puro. `library-search` es el
único escenario con pass@1 = pass@k = 0,00: ninguna repetición, en ningún
brazo, lo resolvió jamás — junto con `backtracking-vault` y
`vault-combination`, ninguno de los tres escenarios de backtracking/multi-item
se resolvió una sola vez. `extreme-archive` (0,50 pass@1) es el escenario
`extreme` que mejor le va al agente, pese a estar diseñado para no caber en
contexto: su óptimo es corto (4 calls) y no requiere backtracking, así que
cuando el agente da con el expediente correcto temprano evita el problema de
ventana que motiva el escenario.

### 3.4 Análisis de errores

Taxonomía implementada en `eval/failures.py` (clasificador heurístico sobre
la traza; los casos sin categoría quedan como `unclassified` para revisión
manual). Un caso puede llevar varias etiquetas; `primary_failure` elige una
por prioridad para que la tabla sume 100%.

| Categoría | Señal en la traza |
|---|---|
| `crash` | Excepción no controlada del proveedor o de una tool |
| `budget_timeout` / `budget_tool_calls` | Presupuesto duro agotado |
| `max_iterations` | El bucle llegó al tope de iteraciones |
| `text_tool_call` | Emitió la acción como JSON en `content`; el bucle la tomó por respuesta final |
| `bad_tool_args` | Argumentos que no matchean la firma (`TypeError`) |
| `hallucinated_id` | Actuó sobre un id inexistente |
| `not_visible` | Objeto existente pero no accesible desde donde estaba |
| `loop` | Misma llamada con mismos argumentos 3+ veces |
| `no_exploration` | `use`/`take` sin explorar antes |
| `navigation_lost` | `go` a dirección inexistente o bloqueada |
| `wrong_order` | Abrió la puerta antes de tener el documento (`office-sequence`) |
| `premature_stop` | Cerró en prosa declarando el final sin cumplir el goal |
| `no_tool_calls` | No invocó ninguna herramienta y nada más lo explica |

Nota de diseño: `no_tool_calls` va casi al final de la prioridad. Es una
observación estructural, no un diagnóstico: cuando la traza está vacía, lo
informativo es *por qué* (`text_tool_call`, `premature_stop`), no el hecho.

Casos de estudio (leídos de la traza de `reports/suite-20260823T224137Z-judged.md`):

1. En `library-search`, el agente examinó sistemáticamente varios libros y la
   caja fuerte, pero repitió llamadas fallidas sobre la misma cerradura en
   lugar de probar la combinación deducida de otro objeto — el juez le da
   `recuperacion=1-2/5` en las 3 trazas puntuadas, y el escenario terminó en
   0/24 en todo el suite.
2. En `apartment-keys` (rep. 0, fallida), el agente examinó la puerta
   principal pero no exploró el resto de la sala antes de intentar usar la
   llave — `no_exploration` combinado con `navigation_lost` (etiqueta con 40
   apariciones en todo el dataset, casi siempre en escenarios multi-sala).
3. En `color-locks` (rep. exitosa), el agente exploró el sótano, tomó la
   llave plateada y encadenó correctamente `use` sobre el cofre — el mismo
   patrón (`look` → `examine` → `take` → `use` en orden) que en
   `study-with-key`, escalado a una cadena más larga.

Casos fallidos: **91 de 120** (76%). Modo de fallo principal (uno por caso,
por prioridad):

| modo | casos | % |
|---|---:|---:|
| `max_iterations` | 89 | 97,8% |
| `budget_timeout` | 2 | 2,2% |

Casi todos los fallos son "se quedó sin presupuesto", no "crasheó" o "emitió
texto en vez de tool call" (`text_tool_call` solo aparece 2 veces en todo el
dataset). Pero `max_iterations` es la causa *terminal*, no la raíz: todas las
etiquetas que puede llevar un mismo caso, en orden de frecuencia, muestran
dónde se gasta ese presupuesto:

| etiqueta | apariciones | interpretación |
|---|---:|---|
| `loop` | 80 | repite la misma llamada (mismos args) 3+ veces sin que el estado cambie |
| `hallucinated_id` | 49 | actúa sobre un id que ninguna tool reportó |
| `navigation_lost` | 40 | `go` a una dirección inexistente/bloqueada, o no vuelve a la sala de la puerta |
| `not_visible` | 36 | actúa sobre un objeto real pero no accesible desde donde está |
| `bad_tool_args` | 3 | argumentos que no matchean la firma de la tool |
| `budget_timeout` | 2 | agotó el wall-clock del caso |
| `text_tool_call` | 2 | emitió la acción como JSON en `content`, no como tool call |

`loop` en 80/91 casos fallidos (88%) es el hallazgo dominante: el agente no
se queda sin ideas por falta de exploración (`no_exploration` no aparece en
el top), se queda sin ideas porque **repite una acción que ya falló** en vez
de ajustar el argumento o probar otra cosa. Esto coincide exactamente con el
eje peor puntuado por el juez (`recuperacion`, §2.2). Por dificultad, el modo
principal se concentra en `hard` (46 de 91) más que en `medium` (28) o
`extreme` (15) — consistente con que `hard` es también la dificultad con
menor pass@1 (0,04) pese a tener menos tokens de entrada que `extreme`: no es
un problema de contexto, es un problema de no saber salir de un error.

---

## 4. Experimentos

Cada experimento cambia **una** variable respecto de `baseline`
(`prompt=escape_v1`, `max_iterations=40`, `max_history_messages=40`), con la
configuración registrada por nombre en `eval/configs.py` para que la corrida
sea reproducible. Hipótesis fijadas antes de correr; resultado real después.

| # | Qué cambia | Hipótesis | Resultado real |
|---|---|---|---|
| **A** | `ESCAPE_V1` → `BASELINE` (prompt genérico), `prompt_baseline` | El prompt especializado sube pass@1 en medium/hard y baja `hallucinated_id` | **Rechazada.** `prompt_baseline` (0,58 pass@1) superó a `baseline` (0,46) en el mismo subconjunto medium/hard. El prompt especializado *no* ganó. |
| **B** | `max_history_messages` ∈ {6, 20, 40 (=baseline)} | La ventana corta destruye `apartment-keys` y escenarios de horizonte largo | **Confirmada en dirección.** `mem_6`: 0,00 pass@1, 40 calls de mediana (satura `max_iterations` sin resolver nada). `mem_20`: 0,17, con la mayor eficiencia de acciones del suite (0,76) cuando sí resuelve. |
| **C** | `examine`→no-op; `max_iterations` ∈ {10, 20, 40 (=baseline)} | Sin `examine` colapsa todo lo que dependa de contenedores; menos iteraciones baja pass@1 monótonamente | **Confirmada.** `noop_examine`: 0,00 pass@1 (el menor error de tools del suite, 0,15, porque casi no actúa — evidencia indirecta de que sin poder inspeccionar contenedores el agente ni siquiera intenta acciones inválidas). `iters_10`: 0,00; `iters_20`: 0,17. Monótono con el presupuesto. |
| **D** | `repair_textual_tool_calls` on/off, mismo dataset completo que `baseline` | Recuperar tool calls emitidas como texto sube pass@1 | **No concluyente.** `repair_on`: 0,29 pass@1, por debajo de `baseline` (0,46) sobre el mismo dataset. El invariante de diseño sí se cumplió (4 tool calls recuperadas de texto, 0 en los brazos con reparación apagada), pero con `temperature=0,2` y sin `seed` fijo (ver nota abajo) `baseline` y `repair_on` son dos corridas independientes y ruidosas, no un mismo episodio repetido con/sin el parche: de los 24 casos de `repair_on`, la reparación solo intervino en 4, así que los otros 20 son simplemente una muestra distinta del mismo modelo estocástico. No se puede atribuir la caída de 0,46 a 0,29 al mecanismo de reparación en sí. |

**Sobre el experimento A.** Es el resultado más contraintuitivo del suite: el
prompt genérico superó al especializado. Con solo 12 casos por brazo la
diferencia (0,58 vs 0,46, calculados sobre el subconjunto medium/hard) no es
estadísticamente robusta, pero tampoco corrobora la hipótesis de diseño. Una
lectura plausible: `ESCAPE_V1` es más largo (protocolo de 6+ reglas) y compite
por atención con la ventana de contexto ya ajustada por `max_history_messages`,
mientras que `qwen2.5:7b-instruct` parece seguir el formato de tool-calling
razonablemente bien incluso con un prompt neutro. Esto no dice que el prompt
especializado sea inútil — dice que, con este modelo y este N, no se puede
afirmar que ayude.

**Sobre el experimento C (`noop_examine`).** El mecanismo no quita la
herramienta: `noop_pair` en `student_framework/__init__.py` conserva el
`ToolSchema` de `examine` tal cual (mismo nombre, misma firma; el modelo la
sigue viendo y puede seguir invocándola) pero reemplaza su cuerpo por una
función que siempre devuelve `"No observás nada especial."`, sin tocar el
mundo. Así se aísla el valor de la **información** que aporta `examine`
(qué contiene un cofre, qué dice un cartel) del valor de que la tool exista:
si el colapso a pass@1 = 0,00 se debiera solo a que el agente ve una tool de
menos en el prompt, alcanzaría con sacarla del registro; en cambio, dejarla
presente pero muda es la forma de probar que es el *contenido* de la
respuesta, no la lista de tools, lo que el agente necesita para progresar.

**Sobre el experimento D.** Surgió de una corrida real anterior, no del
diseño previo: el modelo emite a veces la siguiente acción como JSON dentro
de `content` en vez de como `tool_call` estructurada. El bucle ReAct ve
`tool_calls == []`, concluye que el modelo terminó y corta el episodio justo
cuando el agente se estaba corrigiendo. La reparación
(`student_framework/repair.py`) detecta ese JSON y lo reinyecta; es
conservadora: solo repara si el objeto nombra una herramienta *registrada*,
para no inventar acciones a partir de prosa. El invariante de diseño se
verificó (4 recuperos, 0 fuera del brazo tratado), pero **no se puede leer
`repair_on` (0,29) < `baseline` (0,46) como que reparar empeora las cosas**:
solo 4 de los 24 episodios de `repair_on` activaron la reparación; el resto
son corridas ordinarias del mismo agente sin ninguna intervención del parche.
Con `temperature=0,2` y sin `seed` fijo (ver más abajo), dos corridas de 24
casos del mismo sistema estocástico pueden diferir en varios éxitos por puro
muestreo, sin que medie ninguna causa. El experimento está mal diseñado para
responder su propia pregunta: para aislar el efecto de la reparación habría
que fijar un `seed` (si el proveedor lo soporta) o comparar **solo** los
episodios donde la reparación efectivamente disparó, contra un
contrafáctico de esos mismos episodios con el parche apagado — no dos
muestras independientes del dataset completo.

**Nota sobre reproducibilidad estocástica.** Ambos hallazgos anteriores
(A y D "perdiendo" contra su brazo de control) comparten la misma causa
raíz: `LLMClient` usa `temperature=0,2` por defecto
(`mia_agents/llm_client.py`) y ninguna corrida fija un `seed`. Dos
ejecuciones del *mismo* config sobre el *mismo* escenario pueden no
coincidir. Esto no invalida B y C, donde el efecto (ablar `examine`,
recortar memoria o iteraciones) es tan grande y monótono que domina el
ruido de muestreo, pero sí exige leer A y D como no concluyentes en vez de
como refutaciones firmes de la hipótesis original.

**Advertencia estadística.** N por brazo es 12-24 casos. Las diferencias
reportadas arriba son direccionales, no significativas en sentido
estadístico estricto (no se corrió un test de hipótesis formal). B y C sí
muestran un patrón monótono y coherente con la mecánica del mundo (menos
memoria/menos exploración → peor), mientras que A y D producen el resultado
*opuesto* al hipotetizado sin que se pueda descartar que sea ruido de
muestreo — ver la nota de reproducibilidad estocástica arriba.

---

## 5. Limitaciones y qué construiríamos a continuación

**Limitaciones**

- **N chico.** 8 escenarios × 3 repeticiones por brazo (12-24 casos por
  configuración). Alcanza para direcciones, no para afirmaciones
  estadísticamente robustas — visible en que A y D dan resultados opuestos a
  la hipótesis con este N.
- **Sin control de aleatoriedad entre corridas.** `LLMClient` usa
  `temperature=0,2` por defecto y ninguna corrida fija un `seed` de Ollama.
  Cada brazo experimental es una muestra independiente, no una repetición
  controlada del mismo episodio con una sola variable cambiada — lo que
  explica por qué A y D (§4) dan resultados opuestos a la hipótesis con la
  que se diseñaron.
- **Un solo modelo.** Todos los números son de `qwen2.5:7b-instruct` vía
  Ollama. No se puede separar "límite del framework" de "límite del modelo":
  el mismo harness con `hermes3:8b` y `llama:3.1` había dado 0/120 en una corrida anterior,
  así que buena parte de la varianza entre configuraciones podría no
  replicarse con otro proveedor.
- **Juez corrido pero no validado contra humano.** Se corrió `--judge` sobre
  12 trazas reales (§2.2) y el patrón (peor `recuperacion` en casos fallidos)
  es coherente con el clasificador automático, pero `compare_with_human` no
  se ejecutó sobre anotaciones manuales. El acuerdo direccional con la
  taxonomía heurística es la única validación indirecta disponible.
- **Tres escenarios en 0/pass@k.**
  `library-search`, `backtracking-vault` y `vault-combination` no se
  resolvieron **ni una vez** en 24+6+6 intentos combinados. El enunciado solo
  anticipa que `extreme-archive` no entre en contexto; los otros dos fallan
  por una razón distinta (backtracking profundo / combinación de ítems), que
  el agente ataca con el mismo bucle ReAct plano que todo lo demás.
- **Clasificador de fallos heurístico.** Las categorías se detectan por
  patrones en la traza; los casos ambiguos caen en `unclassified` y requieren
  lectura manual. `wrong_order` y `premature_stop`, en particular, no
  aparecieron en esta corrida — no está claro si el agente nunca los comete o
  si el clasificador no los detecta con este dataset.

**Qué construiríamos**

1. **Memoria por hechos, no por mensajes.** Un scratchpad de observaciones
   (ids vistos, contenedores ya examinados, mapa de salidas) en vez de una
   ventana de mensajes. La ventana recorta por posición, que no correlaciona
   con relevancia: en `backtracking-vault` el dato crítico se observa al
   principio y se necesita al final. Esto ataca directamente `loop`
   (80/91 fallos), el modo de fallo dominante de esta corrida: un agente que
   sabe qué ya intentó y con qué resultado no debería repetir la misma
   llamada fallida tres veces.
2. **Sub-agente de búsqueda para `extreme-archive`.** Delegar el barrido de
   los 20 expedientes a un sub-agente con su propio contexto, que devuelva
   solo el hallazgo. Es la respuesta natural a un escenario diseñado para no
   caber, y el único `extreme` que hoy resuelve razonablemente (0,50) podría
   subir más si el agente no gastara presupuesto en re-leer expedientes ya
   descartados.
3. **Planner explícito para goals `sequence` y backtracking.**
   `office-sequence` (pass@1 = 0,08 pese a pass@k = 1,00) y
   `backtracking-vault`/`vault-combination` (0/24 combinados) son los casos
   donde reaccionar paso a paso pierde contra planificar: un pre-paso con
   `structured_call` que devuelva la lista ordenada de sub-objetivos, o el
   grafo de dependencias entre salas/ítems, antes de actuar.
4. **Revisitar el experimento A con un prompt más corto.** Dado que
   `ESCAPE_V1` perdió contra el prompt genérico, valdría la pena probar una
   versión condensada (2-3 reglas en vez de 6+) antes de descartar el
   prompting especializado como palanca.

---

## Reproducibilidad

```bash
python -m pytest tests/ -q                                   # suite de tests
bash eval/run_all.sh                                          # baseline + 4 experimentos -> results/suite-<stamp>/
python eval/report.py results/suite-20260823T224137Z/*.jsonl -o reports/suite-20260823T224137Z.md
python eval/report.py results/suite-20260823T224137Z/*.jsonl \
  --judge --judge-limit 12 -o reports/suite-20260823T224137Z-judged.md
```
