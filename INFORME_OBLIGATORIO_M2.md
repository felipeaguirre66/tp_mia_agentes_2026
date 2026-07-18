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

*(Pendiente: manejo de errores recuperables en calculadora y lector de archivos, con un ejemplo concreto de recuperación de cada una.)*

## 4. Modos de fallo dentro y fuera del alcance

*(Pendiente: completar junto con los reintentos ante fallos transitorios del cliente LLM. Ya asumido: presupuestos de memoria < 3 degradan el tool use — ver sección 1.)*
