# Informe M3 — Evaluación sobre el problema de sala de escape

> **ESTADO: esqueleto.** Todo lo que no depende de números está escrito.
> Los bloques marcados `⟨PENDIENTE⟩` se completan con la salida de
> `python eval/report.py results/*.jsonl` una vez corrida la evaluación
> real. **No copiar números de una corrida `--dry-run`**: el generador de
> informes los rechaza por defecto, precisamente porque un informe hecho
> con el mock se ve idéntico a uno real.

Modelo de todos los números: `qwen3.6` vía Ollama.
Corridas incluidas: `⟨PENDIENTE⟩`. Git SHA: `⟨PENDIENTE⟩`.

---

## 1. Aproximación

**Qué se reusó sin tocar.** El núcleo de M1+M2 resolvió el problema sin
modificaciones: el bucle ReAct de `MyAgent.run`, el reintento de fallos
transitorios (`_call_with_retry`), la memoria de ventana deslizante
(`_trim_messages`) y `structured_call`. Que el core no necesitara cambios
para pasar de "calculadora y lector de archivos" a "sala de escape
multi-sala con dependencias profundas" es, en sí, el resultado de diseño
más fuerte de la entrega.

**Qué se especializó.** Tres cosas, todas por configuración, ninguna
rompiendo el contrato de M1/M2:

1. **`build_agent` con modo mundo.** Si `config` trae `"world"`, registra
   los verbos de `mia_world.make_world_tools(world)` en lugar de las tools
   de juguete (que en una sala de escape son ruido que compite por la
   atención del modelo) y sube los presupuestos. Sin `"world"`, el
   comportamiento es exactamente el de M2: los 78 tests de conformidad no
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
   necesita 21 tool calls óptimas. El modo mundo usa 40/40.

**Qué se construyó nuevo.** El paquete `eval/`: harness, presupuestos duros,
trazado, métricas, taxonomía de fallos, LLM-as-judge e informe. Es
infraestructura de evaluación, no de agente.

**Una modificación al agente**, gateada y apagada por defecto en el contrato
M1/M2: `repair_textual_tool_calls` (ver experimento D). La configuración final
`baseline` la activa; `repair_off` conserva el bucle ReAct clásico como
ablación. Así los experimentos A–C cambian una sola variable sin quedar
dominados por un fallo de formato ya conocido.

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
  wall-clock por caso. Cada caso corre en un subprocess terminable, por lo
  que el timeout también cubre una llamada LLM bloqueada; el presupuesto de
  tools conserva la excepción `BaseException` para atravesar el loop.

---

## 2. Métricas

### 2.1 Cuantitativas

| Métrica | Definición | Por qué esta |
|---|---|---|
| **pass@1** | `check_goal(world, goal)` promediado sobre casos | Se computa sobre el **estado del mundo**, no sobre el texto del agente. Ver §5: tenemos casos donde el agente declara haber escapado con la puerta cerrada. |
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

**Validación del juez.** ⟨PENDIENTE: puntuar 8–10 trazas a mano y correr
`eval.judge.compare_with_human`. Reportar acuerdo exacto y ±1 por eje.⟩
Sin este número, los scores del juez no son citables.

---

## 3. Resultados

⟨PENDIENTE: pegar las tablas de `reports/m3-<stamp>.md`⟩

- Global y por dificultad
- Por escenario (con óptimo y eficiencia)
- Modo de fallo principal × dificultad

### 3.1 Análisis de errores

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

⟨PENDIENTE: 2–3 trazas comentadas como casos de estudio.⟩

---

## 4. Experimentos

Cada experimento cambia **una** variable respecto de `baseline`, con la
configuración registrada por nombre en `eval/configs.py` para que la corrida
sea reproducible. Hipótesis fijadas antes de correr.

| # | Qué cambia | Hipótesis | Resultado |
|---|---|---|---|
| **A** | `ESCAPE_V1` → `BASELINE` (prompt genérico) | El prompt especializado sube pass@1 en medium/hard y baja `hallucinated_id` | ⟨PENDIENTE⟩ |
| **B** | `max_history_messages` ∈ {6, 20, 40} | La ventana corta destruye `apartment-keys` y `backtracking-vault` (hay que recordar el mapa) y es indiferente en `study-with-key`. Mide el valor de M2 sobre *este* problema | ⟨PENDIENTE⟩ |
| **C** | `examine` → no-op (mismo esquema, sin información); `max_iterations` ∈ {10, 20, 40} | Sin `examine` colapsa todo lo que dependa de contenedores. El barrido de iteraciones separa "no sabe" de "no le alcanzó el presupuesto" | ⟨PENDIENTE⟩ |
| **D** | `baseline` (reparación ON) → `repair_off` | Recuperar tool calls emitidas como texto sube pass@1 en todas las dificultades y hace caer `text_tool_call` y `premature_stop` | ⟨PENDIENTE⟩ |

**Sobre el experimento D.** Surgió de la primera corrida real, no del
diseño previo: `qwen3.6` puede emitir la siguiente acción como JSON dentro
de `content` en vez de como `tool_call` estructurada. El bucle ReAct ve
`tool_calls == []`, concluye que el modelo terminó y corta el episodio justo
cuando el agente se estaba corrigiendo. La reparación
(`student_framework/repair.py`) detecta ese JSON y lo reinyecta; es
conservadora: solo repara si el objeto nombra una herramienta *registrada*,
para no inventar acciones a partir de prosa. Es el experimento que toca el
bucle en vez del prompt, y por eso el más directo sobre "qué partes del
framework importan".

**Advertencia estadística.** Con `⟨PENDIENTE: n⟩` casos por brazo, las
diferencias observadas **no son estadísticamente significativas**. Se
reportan como direccionales, no como efectos medidos.

---

## 5. Limitaciones y qué construiríamos a continuación

**Limitaciones**

- **N chico.** 8 escenarios × 3 repeticiones por brazo. Alcanza para
  direcciones, no para afirmaciones.
- **Un solo modelo.** Todos los números son de `qwen3.6`. Buena
  parte de los fallos observados son de disciplina de tool-calling, que es
  precisamente donde un modelo de 8B es más frágil: no se puede separar
  "límite del framework" de "límite del modelo" sin un segundo proveedor.
- **Juez sin validar a fondo.** ⟨PENDIENTE: acuerdo con humano⟩. Un score de
  LLM-as-judge sin acuerdo medido no es evidencia.
- **`extreme-archive` sin estrategia dedicada.** El agente lo ataca con el
  mismo bucle que todo lo demás; el escenario está diseñado para no caber en
  contexto.
- **Clasificador de fallos heurístico.** Las categorías se detectan por
  patrones en la traza; los casos ambiguos caen en `unclassified` y requieren
  lectura manual.

**Qué construiríamos**

1. **Memoria por hechos, no por mensajes.** Un scratchpad de observaciones
   (ids vistos, contenedores ya examinados, mapa de salidas) en vez de una
   ventana de mensajes. La ventana recorta por posición, que no correlaciona
   con relevancia: en `backtracking-vault` el dato crítico se observa al
   principio y se necesita al final.
2. **Sub-agente de búsqueda para `extreme-archive`.** Delegar el barrido de
   los 20 expedientes a un sub-agente con su propio contexto, que devuelva
   solo el hallazgo. Es la respuesta natural a un escenario diseñado para no
   caber.
3. **Planner explícito para goals `sequence`.** Un pre-paso con
   `structured_call` que devuelva la lista ordenada de sub-objetivos antes de
   actuar. `office-sequence` premia planificar sobre reaccionar, y el
   enunciado sugiere el contraste planner vs ReAct puro.

---

## Reproducibilidad

```bash
python -m pytest tests/ -q          # 163 tests antes de la corrida final
REPEATS=3 bash eval/run_all.sh       # 120 casos + informe cuantitativo
python -m eval.judge score results/final-*/*.jsonl --limit 10 \
  --out reports/judge-scores.json --human-template reports/human-scores.json
```
