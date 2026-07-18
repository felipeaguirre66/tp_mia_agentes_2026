# Informe M2

## 1. Estrategia de memoria

Implementamos una estrategia de memoria de tipo sliding window dentro del agente. En cada llamada a `run(...)`, el historial previo se conserva en memoria de instancia (`self._history`), se agrega el nuevo mensaje del usuario y se recorta para no superar `max_history_messages`.

La política de recorte prioriza:
- Mantener siempre el mensaje de usuario más reciente (invariante de recencia del enunciado): se fija al frente de la ventana si el recorte lo dejaría afuera, y con presupuesto 1 es lo único que viaja.
- Mantener los max_history_messages-1 mensajes más recientes. Estos son probablemente los más relevantes para la conversación actual.
- Mantener el primer mensaje del usuario (suele ser el más importante), siempre que entre sin desalojar al más reciente.

Además, la ventana nunca arranca con mensajes `role: "tool"` cuyo assistant con `tool_calls` quedó recortado: esos mensajes referencian un `tool_call_id` inexistente y un proveedor real puede rechazar el historial como incoherente, así que se descartan aunque quede presupuesto sin usar (el contrato es `<=`, no `==`).

Limitación asumida: con presupuestos muy chicos (`max_history_messages < 3`) el uso de herramientas se degrada, porque no entran a la vez el mensaje del usuario, el tool_call del assistant y su resultado; el modelo no llega a ver los resultados y el bucle corta por `max_iterations`. Asumimos presupuestos realistas.

## 2. Salida estructurada

`structured_call(prompt, schema, max_repair_attempts)` usa la herramienta sintética `final_result` como única vía de cierre:

- En cada llamada a `chat` se ofrece **una sola tool**: `final_result_tool_schema(schema)`, el JSON Schema derivado del modelo Pydantic recibido. No se exponen las tools reales del agente: `structured_call` es un paso de formateo, no de resolución.
- La conversación de este método es **local** (no toca `self._history`): es una consulta puntual con contrato propio, no un turno de la conversación del usuario.
- El método termina únicamente cuando llega un `tool_call` a `final_result` cuyos `arguments` parsean como JSON y validan con `schema.model_validate(...)`; en ese caso devuelve la instancia tipada.

**Validación y reparación.** Se distinguen tres modos de fallo, cada uno con su mensaje de reparación:

1. *Texto libre* (el modelo no invocó la tool): se agrega su respuesta al historial local y un mensaje `user` indicando que debe responder únicamente invocando `final_result`.
2. *Argumentos no parseables como JSON*.
3. *Argumentos que no validan contra el schema*: en ambos casos se copia el tool_call fallido al historial y se responde con un mensaje `role: "tool"` (linkeado por `tool_call_id`) que incluye el error concreto de parseo/validación de Pydantic, para que el modelo sepa qué campo corregir.

**Reintentos y fallo.** Se hacen como máximo `1 + max_repair_attempts` llamadas al LLM (intento inicial + reparaciones). Si se agotan sin una respuesta válida, se levanta `ValueError` con el último error registrado; nunca se devuelve `None` ni una instancia parcial.

## 3. Errores en herramientas

Principio general: ante un error recuperable, la herramienta **no lanza excepciones** — devuelve un string que nombra el parámetro que falló, el valor recibido, la regla violada y qué valores serían válidos. Ese string llega al LLM como mensaje `role: "tool"` dentro del bucle de `run`, de modo que el modelo puede corregir los argumentos y reintentar en la misma conversación, sin intervención del usuario. Los mensajes empiezan con "Error recuperable:" cuando un reintento con argumentos corregidos tiene sentido, y con "Error:" a secas cuando no (para no invitar a reintentar lo imposible).

### Calculadora

| Error | Mensaje devuelto al LLM |
|---|---|
| Operando no numérico | Nombra el parámetro (`left_operand`/`right_operand`), el valor recibido y pide un número |
| Operador no soportado | Muestra el valor recibido y lista los permitidos: `+`, `-`, `*`, `%` |
| Módulo por cero | Explica la restricción: `right_operand` debe ser distinto de 0 |

Los operandos se normalizan con `float(...)` antes de operar, así los valores que llegan como string numérico (`"17"`) se calculan correctamente en vez de concatenarse o fallar. Las anotaciones `Literal`/`Annotated` de la firma generan el schema que guía al modelo, pero no se confía en ellas como validación: el LLM puede mandar cualquier cosa en `arguments`.

**Ejemplo de recuperación (ejecución real, Ollama/qwen3.6).** Pedido: *"calculá 10 módulo 0"*. El modelo invocó `calculator(10, "%", 0)` y recibió `"Error recuperable: módulo por cero — right_operand debe ser distinto de 0."`. Con ese contexto respondió al usuario explicando que la operación es matemáticamente imposible y por qué, en lugar de crashear o responder un error genérico. (Para este error no existe reintento con argumentos válidos; la "recuperación" es degradar con una explicación sensata.)

### Lector de archivos

La herramienta opera dentro de un **sandbox** (`student_framework/test/`), anclado a la ubicación del código (no al cwd). Chequeos en orden, del más barato al más caro:

| Error | Mensaje devuelto al LLM |
|---|---|
| Ruta vacía | Regla + ejemplo de ruta válida + listado de archivos del sandbox |
| Ruta absoluta | Regla violada + cómo se ve una ruta válida (relativa al sandbox) |
| Ruta que escapa del sandbox (`..`, symlinks) | Regla violada + ejemplo válido |
| La ruta es un directorio | Lo indica + lista su contenido para que el modelo elija un archivo |
| Archivo inexistente | Si el directorio contenedor existe, **lista los archivos disponibles** ahí; si no, lista la raíz del sandbox |

El chequeo de escape no busca el substring `".."` (daría falsos positivos con nombres como `data..txt` y es evadible): se resuelve la ruta con `Path.resolve()` — que colapsa `..` y symlinks — y se verifica el destino final con `is_relative_to(sandbox)`. Importa dónde cae la ruta, no cómo está escrita.

**Ejemplo de recuperación (ejecución real, Ollama/qwen3.6).** Pedido: *"leé el archivo dta.txt"* (typo deliberado). Turno 1: el modelo invocó `file_reader("dta.txt")` y recibió `"Error recuperable: el archivo 'dta.txt' no existe. Archivos disponibles en ese directorio: chat.py, comands.md, data.txt, use_agent.py."`. Turno 2: el modelo dedujo el typo por el listado, invocó `file_reader("data.txt")` y obtuvo el contenido, que devolvió al usuario aclarando la corrección. Recuperación completa sin intervención humana.

## 4. Modos de fallo dentro y fuera del alcance

**Dentro del alcance (manejados):**
- Argumentos inválidos en herramientas (no numéricos, operador no soportado, módulo por cero, rutas malformadas o fuera del sandbox): mensaje accionable y reintento del LLM en el mismo bucle.
- Salida estructurada malformada (texto libre, JSON roto, schema inválido): reparación con contexto del error, tope de reintentos, excepción limpia al agotarlos.
- Historial que excede el presupuesto de contexto: sliding window con invariante de recencia y limpieza de mensajes `tool` huérfanos.

**Fuera del alcance (deliberadamente):**
- Archivos existentes pero no legibles como texto UTF-8 (binarios) o sin permisos: se devuelve un mensaje claro pero no se considera recuperable — ningún argumento corregido lo arregla.
- Presupuestos de memoria `< 3`: degradan el tool use porque no entran a la vez el mensaje del usuario, el tool_call y su resultado (ver sección 1).
- Respuestas del modelo con formato válido pero semánticamente incorrectas (p. ej. un número equivocado que valida contra el schema): la validación garantiza forma, no verdad.
- Contextos que exceden la ventana del propio proveedor aun respetando `max_history_messages` (mensajes individuales enormes).

*(Pendiente: reintentos ante fallos transitorios del cliente LLM — timeouts, 5xx, rate limits; al implementarlos, mover ese punto a "dentro del alcance".)*
