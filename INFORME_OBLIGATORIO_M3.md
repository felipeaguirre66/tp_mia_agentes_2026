# Informe obligatorio M3 — Evaluación sobre el problema de sala de escape

Fecha de cierre experimental: **23 de agosto de 2026**

Proveedor y modelo: **Ollama 0.31.1 / `qwen3.6`**

Checkpoint evaluado: **`210eb1fbbc52c20e90dbaccec6eb66b3f5890c53`**

Cohorte final: **120 casos reales**, 3 repeticiones por escenario y configuración.

## Resumen técnico

El M3 quedó implementado y evaluado sobre los ocho escenarios del mundo simulado. El sistema final usa el prompt especializado `escape_v1`, una ventana de 40 mensajes, 40 iteraciones y reparación de tool calls textuales activa. El ReAct clásico se conserva como la ablación `repair_off`; los módulos fijos `mia_agents/` y `mia_world/` no fueron modificados para esta entrega.

El baseline resolvió **14 de 24 casos** (`pass@1=0,58`) y al menos una de las tres repeticiones en **7 de 8 escenarios** (`pass@3=0,88`). En el conjunto completo de configuraciones hubo **51 éxitos de 120** (`pass@1=0,42`). La suite confirma que el prompt especializado, una memoria suficiente y el acceso informativo a `examine` son importantes. También muestra límites claros: 26 crashes del proveedor, 21 timeouts y un desempeño nulo en `extreme-archive`.

La evaluación cualitativa incluyó 10 trazas determinísticas. El acuerdo exacto juez-humano fue de **60% en exploración**, **40% en uso de evidencia** y **40% en recuperación**. El acuerdo dentro de ±1 fue 90%, 60% y 50%, respectivamente. Por lo tanto, la señal cualitativa es utilizable con cautela, especialmente en exploración, pero no debe presentarse como una medición objetiva en recuperación.

## 1. Sistema evaluado

### 1.1 Componentes reutilizados

El agente conserva los componentes desarrollados en M1 y M2:

- bucle ReAct de `MyAgent.run`;
- registro y ejecución de herramientas;
- reintento ante fallos transitorios;
- memoria de ventana deslizante;
- salida estructurada mediante `structured_call`.

Para M3, `build_agent` registra las herramientas del mundo (`look`, `examine`, `take`, `use` y `go`) cuando recibe una configuración con `world`. Fuera de ese modo mantiene el comportamiento anterior.

### 1.2 Especialización para la sala de escape

La configuración final `baseline` introduce:

- prompt de dominio `escape_v1`, que exige observar primero, utilizar los ids informados por las tools y confirmar el estado del mundo antes de declarar éxito;
- `max_history_messages=40`;
- `max_iterations=40`;
- reparación conservadora de tool calls emitidas como JSON textual.

La reparación permanece apagada por defecto en `MyAgent`, de modo que M1 y M2 no cambian. Solo se activa en las configuraciones experimentales de M3 que la requieren.

## 2. Diseño de evaluación

### 2.1 Integridad y aislamiento

Cada caso recarga el escenario desde disco, construye un mundo nuevo y se ejecuta en un subprocess. Esto evita heredar mutaciones entre repeticiones y permite terminar una llamada LLM bloqueada cuando vence `--timeout`. El presupuesto de tool calls se controla de forma independiente.

Los JSONL se crean de manera exclusiva: si `--out` ya existe, la ejecución falla en lugar de sobrescribirlo. Cada caso se escribe con flush inmediato para conservar resultados parciales.

Antes de generar un informe se validan:

- claves `(configuración, escenario, repetición)` únicas;
- ausencia de casos faltantes;
- ausencia de dry-runs;
- un único proveedor, modelo y SHA;
- cohortes comparables para los deltas experimentales.

### 2.2 Métricas

| Métrica | Definición |
|---|---|
| `pass@1` | Proporción de casos cuyo objetivo se cumple en el estado del mundo. |
| `pass@3` | Proporción de pares `(configuración, escenario)` con al menos un éxito en tres repeticiones. |
| Eficiencia | `optimal_calls / tool_calls`, solo en casos resueltos. |
| Overhead | `tool_calls - optimal_calls`, usando el óptimo-oráculo del enunciado. |
| Error de tools | Llamadas cuyo resultado representa un error, sobre el total de llamadas. |
| Latencia | Segundos de wall-clock por caso, incluida la llamada al proveedor. |

El óptimo oficial no incluye necesariamente el `look` inicial exigido por el protocolo. Por eso el overhead esperado no se interpreta automáticamente como desperdicio.

### 2.3 Cohorte ejecutada

La suite final contiene siete archivos y exactamente 120 casos:

| Bloque | Casos |
|---|---:|
| Baseline easy + medium | 9 |
| Baseline hard | 6 |
| Baseline extreme | 9 |
| Experimento A: prompt | 12 |
| Experimento B: memoria | 24 |
| Experimento C: no-op y presupuesto | 36 |
| Experimento D: reparación apagada | 24 |
| **Total** | **120** |

## 3. Resultados cuantitativos

### 3.1 Resultado global y por dificultad

| Grupo | n | pass@1 | pass@3 | Eficiencia | Overhead mediano | Error tools | Calls medianas | Latencia mediana |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Todos los casos | 120 | 0,42 | 0,55 | 0,63 | 5,0 | 0,04 | 10,0 | 121,48 s |
| Easy | 6 | 1,00 | 1,00 | 0,72 | 1,0 | 0,00 | 4,0 | 34,88 s |
| Medium | 48 | 0,50 | 0,62 | 0,70 | 3,0 | 0,04 | 10,0 | 99,29 s |
| Hard | 48 | 0,27 | 0,38 | 0,42 | 11,0 | 0,03 | 5,0 | 160,77 s |
| Extreme | 18 | 0,44 | 0,67 | 0,68 | 9,5 | 0,05 | 23,0 | 314,72 s |

La categoría extreme supera a hard en el agregado porque no contiene los mismos brazos experimentales y porque `backtracking-vault` resultó mucho más resoluble que `extreme-archive`. No corresponde interpretar esa diferencia como una escala de dificultad invertida.

### 3.2 Resultado por configuración

| Configuración | n | pass@1 | pass@3 | Eficiencia | Overhead mediano |
|---|---:|---:|---:|---:|---:|
| `baseline` | 24 | 0,58 | 0,88 | 0,63 | 5,0 |
| `prompt_baseline` | 12 | 0,50 | 0,75 | 0,70 | 3,0 |
| `mem_6` | 12 | 0,08 | 0,25 | 0,33 | 14,0 |
| `mem_20` | 12 | 0,58 | 0,75 | 0,59 | 7,0 |
| `noop_examine` | 12 | 0,00 | 0,00 | — | — |
| `iters_10` | 12 | 0,00 | 0,00 | — | — |
| `iters_20` | 12 | 0,75 | 0,75 | 0,57 | 5,0 |
| `repair_off` | 24 | 0,58 | 0,62 | 0,67 | 6,0 |

### 3.3 Resultado por escenario

| Escenario | Dificultad | Óptimo | n | pass@1 | pass@k | Eficiencia | Overhead mediano |
|---|---|---:|---:|---:|---:|---:|---:|
| `study-with-key` | easy | 3 | 6 | 1,00 | 1,00 | 0,72 | 1,0 |
| `apartment-keys` | medium | 7 | 24 | 0,42 | 0,62 | 0,65 | 3,0 |
| `color-locks` | medium | 11 | 24 | 0,58 | 0,62 | 0,74 | 3,5 |
| `library-search` | hard | 7 | 24 | 0,50 | 0,62 | 0,40 | 11,0 |
| `office-sequence` | hard | 13 | 24 | 0,04 | 0,12 | 0,72 | 5,0 |
| `backtracking-vault` | extreme | 18 | 6 | 0,83 | 1,00 | 0,69 | 8,0 |
| `extreme-archive` | extreme | 4 | 6 | 0,00 | 0,00 | — | — |
| `vault-combination` | extreme | 21 | 6 | 0,50 | 1,00 | 0,65 | 13,0 |

## 4. Experimentos

Cada delta usa exactamente la intersección de escenarios entre el brazo y su baseline. Los valores están expresados en puntos porcentuales de `pass@1`.

| Experimento | Baseline comparable | Brazo | Delta | Lectura |
|---|---:|---:|---:|---|
| A — prompt genérico | 0,67 | 0,50 | −16,7 pp | El prompt especializado mejora la tasa de éxito en esta cohorte. |
| B — memoria 6 | 0,67 | 0,08 | −58,4 pp | La ventana corta pierde información necesaria y eleva el overhead. |
| B — memoria 20 | 0,67 | 0,58 | −8,4 pp | Veinte mensajes se acercan al baseline, pero no lo igualan en consistencia. |
| C — `examine` no-op | 0,67 | 0,00 | −66,7 pp | Sin observaciones informativas de contenedores, ningún caso comparable se resolvió. |
| C — 10 iteraciones | 0,67 | 0,00 | −66,7 pp | El presupuesto de M2 es insuficiente para esta cohorte. |
| C — 20 iteraciones | 0,67 | 0,75 | +8,3 pp | Logra mayor `pass@1`, pero menor `pass@k` (0,75 frente a 1,00); el resultado es inestable y de n pequeño. |
| D — reparación apagada | 0,58 | 0,58 | 0,0 pp | Empata en `pass@1`, pero baja de 0,88 a 0,62 en `pass@3`. |

El experimento D no demuestra por sí solo un efecto causal de la reparación: la suite final registró **0 tool calls reparadas** y los brazos sufrieron crashes XML del proveedor. La reparación queda activa como defensa conservadora observada durante el desarrollo, mientras que el resultado final se reporta como empate en `pass@1` y diferencia direccional en consistencia.

Con solo tres repeticiones por escenario, ningún delta se interpreta como significancia estadística.

## 5. Fallos observados

Hubo **69 fallos en 120 casos**.

| Causa primaria | Casos | Porcentaje de fallos |
|---|---:|---:|
| `crash` | 26 | 37,7% |
| `budget_timeout` | 21 | 30,4% |
| `max_iterations` | 14 | 20,3% |
| `loop` | 5 | 7,2% |
| `empty_response` | 3 | 4,3% |

Los crashes provienen principalmente de respuestas HTTP 500 de Ollama al parsear XML de tool calls generado por `qwen3.6`: `element <function> closed by </parameter>`. El harness conserva el fallo y continúa con el caso siguiente, pero estas interrupciones afectan la comparabilidad entre repeticiones.

Los tres casos inicialmente `unclassified` fueron revisados. En los tres el modelo devolvió una respuesta vacía, sin tool call ni texto, después de una exploración parcial de `extreme-archive`; se incorporó la categoría `empty_response` y no quedaron fallos sin clasificar.

### 5.1 Casos de estudio

**Éxito corto — `study-with-key`, baseline, repetición 0.** El agente ejecutó `look`, examinó la alfombra, tomó `llave_oro` y abrió la puerta en 4 llamadas. El óptimo oficial es 3; la única llamada extra es el `look` inicial exigido por el protocolo. Es un ejemplo del overhead esperado que no representa una búsqueda errática.

**Bucle después de reunir evidencia — `vault-combination`, baseline, repetición 2.** El agente consiguió los tres núcleos en 21 llamadas, pero luego navegó repetidamente entre taller, depósito y biblioteca, volvió a usar puertas y contenedores ya abiertos y agotó las 40 iteraciones sin regresar al panel final. El caso muestra que explorar y recordar objetos no garantiza convertir la evidencia en el último subobjetivo.

**Cierre vacío — `extreme-archive`, baseline, repetición 0.** Después de `look` y `examine(estanteria_archivo)`, el LLM devolvió una respuesta vacía. No hubo excepción ni texto reparable; el mundo quedó con la puerta cerrada. Esta traza motivó la categoría `empty_response`.

## 6. Evaluación cualitativa y acuerdo humano

El judge puntuó una muestra determinística de 10 trazas: una repetición 0 de cada escenario y dos fallos baseline de mayor cantidad de llamadas. Los ejes fueron exploración, uso de evidencia y recuperación, todos en escala de 1 a 5.

| Eje | Media judge | Media humana | Acuerdo exacto | Acuerdo ±1 | Diferencia absoluta media |
|---|---:|---:|---:|---:|---:|
| Exploración | 3,9 | 3,6 | 0,60 | 0,90 | 0,50 |
| Uso de evidencia | 4,3 | 3,7 | 0,40 | 0,60 | 1,00 |
| Recuperación | 4,3 | 4,0 | 0,40 | 0,50 | 1,30 |

El judge tiende a puntuar más alto que la anotación humana, especialmente en evidencia y recuperación. El acuerdo ±1 de exploración es alto, pero recuperación alcanza solo 50%. En consecuencia, los scores cualitativos sirven para describir casos y formular hipótesis, no para ordenar configuraciones con precisión.

## 7. Limitaciones

- **Muestra pequeña.** Tres repeticiones por escenario permiten describir direcciones, no estimar efectos estables.
- **Un solo modelo y proveedor.** Todos los casos usan `qwen3.6` sobre Ollama; no se separan límites del framework, del modelo y del parser del proveedor.
- **Mismo modelo como agente y judge.** `qwen3.6` puede compartir sesgos entre generación y evaluación. El acuerdo humano reduce, pero no elimina, ese riesgo.
- **Acuerdo cualitativo desigual.** La recuperación presenta una diferencia absoluta media de 1,3 puntos, demasiado alta para tratar el score del judge como verdad de referencia.
- **Crashes del proveedor.** Los 26 errores XML son fallos de infraestructura/modelo y no equivalen a una decisión incorrecta del agente, aunque sí forman parte de la confiabilidad end-to-end observada.
- **Timeouts sin traza parcial del subprocess.** Cuando el proceso es terminado, se registra `budget_timeout`, pero no siempre es posible recuperar la traza acumulada dentro del worker.
- **Óptimo de oráculo.** La eficiencia usa los óptimos del enunciado y penaliza acciones de descubrimiento como el `look` inicial; por eso también se informa el overhead explícito.
- **`extreme-archive` requiere otra estrategia.** El ReAct generalista no completó ninguna repetición de ese escenario.

## 8. Conclusiones y próximos pasos

El M3 demuestra que el framework de M1/M2 puede operar sobre un mundo multi-sala y que la configuración afecta materialmente el resultado. La evidencia más clara es el colapso con memoria 6, `examine` sin información y 10 iteraciones. El baseline alcanza buena cobertura de escenarios, pero su confiabilidad global sigue limitada por el proveedor, los timeouts y la falta de planificación en secuencias largas.

Las extensiones con mayor justificación empírica serían:

1. una memoria estructurada de hechos, ids, contenedores examinados y mapa de salas;
2. un planner explícito para objetivos secuenciales como `office-sequence`;
3. una estrategia de búsqueda o subagente acotado para `extreme-archive`;
4. repetir la evaluación con otro modelo o proveedor para separar errores del framework y del backend.

## 9. Reproducibilidad

```bash
# Suite de tests
python -m pytest -q

# Suite real: siete JSONL y 120 casos con REPEATS=3
REPEATS=3 bash eval/run_all.sh

# Puntuar las 10 trazas y crear la plantilla humana
python -m eval.judge score results/final-<stamp>/*.jsonl \
  --limit 10 \
  --out reports/judge-scores-<stamp>.json \
  --human-template reports/human-scores-<stamp>.json

# Calcular acuerdo después de la anotación manual
python -m eval.judge compare \
  --judge reports/judge-scores-<stamp>.json \
  --human reports/human-scores-<stamp>.json \
  --out reports/judge-agreement-<stamp>.json
```

Artefactos finales:

- `results/final-20260822T225250Z/`: siete JSONL y manifiesto con comandos, tamaños y SHA-256;
- `reports/m3-20260822T225250Z.md`: reporte regenerable desde los resultados;
- `reports/judge-scores-20260822T225250Z.json`: scores persistidos del judge;
- `reports/human-scores-20260822T225250Z.json`: anotación humana;
- `reports/judge-agreement-20260822T225250Z.json`: acuerdo exacto, ±1 y diferencia absoluta media;
- `reports/unclassified-review-20260822T225250Z.md`: revisión de los casos reclasificados.
