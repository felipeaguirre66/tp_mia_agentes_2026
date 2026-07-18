# Guía M2 — v1 orientativa (pensás vos, esto solo dispara)

Fuente de verdad: `ENUNCIADO_M2.md` + `tests/conformance/test_m2.py`. Los tests
son el piso, no el techo: la corrección ejecuta más casos sobre el mismo contrato.

Correr en cualquier momento: `pytest tests/conformance/test_m2.py -v`

---

## Estado actual (commit 598eec0)

| Bloque | Estado |
|---|---|
| Statefulness (`self._history`) | ✅ hecho |
| Sliding window (`_trim_messages`) | ✅ hecho, con 2 flancos débiles (ver abajo) |
| Tracking de tokens | ✅ hecho (venía de M1) |
| `structured_call` + `final_result` | ❌ stub |
| Errores recuperables en calculator / file_reader | ❌ sin manejo |
| Reintentos ante fallos transitorios del LLM | ❌ no existe |
| Informe | ⚠️ solo sección 1 de 4 |

---

## Bloque 1 — Revisar la memoria que ya escribiste

- El enunciado tiene UNA invariante innegociable: *el mensaje de usuario más
  reciente siempre viaja en la siguiente llamada al LLM*. Agarrá tu
  `_trim_messages` y perseguí el caso borde: ¿qué devuelve con `budget=1` en una
  conversación de 5 turnos? ¿Qué mensaje de usuario sobrevive? ¿Es el correcto
  según la invariante?
- La ventana corta la lista en un punto arbitrario. ¿Qué pasa si el corte cae
  **entre** un mensaje `assistant` con `tool_calls` y sus mensajes `role: "tool"`?
  El mock no se queja... ¿y Ollama/Bedrock? ¿Qué regla simple garantiza que la
  ventana nunca arranque con un `tool` huérfano?
- Tu política conserva el *primer* mensaje del usuario. ¿Podés justificar eso en
  el informe, o es un supuesto que conviene repensar?

## Bloque 2 — `structured_call`

Disparadores para diseñarlo antes de escribir una línea:

- ¿Qué le pasás en `tools=` en cada `chat` de este método? (pista: hay un helper
  ya hecho en `mia_agents.tool_schema` — no armes el schema a mano).
- ¿Cuáles son los TRES modos de fallo de una respuesta del modelo acá? (texto
  libre, y dos formas distintas de que un tool_call a `final_result` esté mal).
- Cuando falla, ¿cómo se entera el modelo de QUÉ falló en el siguiente intento?
  ¿Qué mensajes agregás al historial local antes de reintentar?
- Aritmética exacta de intentos: con `max_repair_attempts=2`, ¿cuántas llamadas
  a `chat` hace tu método como máximo? El test lo cuenta con `call_count`.
- Al agotar reintentos: ¿qué levantás? ¿Qué está explícitamente prohibido
  devolver?
- ¿Este método comparte `self._history` con `run` o usa mensajes propios?
  Decidilo y justificalo en el informe.

## Bloque 3 — Errores recuperables en las tools de M1

La idea fuerza: la tool no crashea ni devuelve "error" a secas — devuelve un
string que le permita al LLM **corregir los argumentos y reintentar**.

Calculadora (`student_framework/tools/calculator.py`):
- Mirá tu código actual: ¿qué pasa hoy con `5 % 0`? ¿Y si el modelo manda
  `left_operand="abc"`? ¿Dónde muere y qué mensaje llega al LLM?
- Para cada caso del enunciado (operando no numérico, operador no soportado,
  módulo por cero): ¿qué información necesita el modelo para autocorregirse?
  (nombre del parámetro, valor recibido, valores permitidos...)

Lector de archivos (`student_framework/tools/file_reader.py`):
- Hoy lee CUALQUIER ruta del disco. ¿Cuál es tu sandbox? Definilo primero.
- Casos a cubrir: ruta vacía / absoluta / con `..` / que escapa del sandbox;
  archivo inexistente; la ruta es un directorio. Para los dos últimos el
  enunciado pide algo más que explicar: ¿qué listado le devolvés al modelo para
  que elija bien en el próximo intento?
- ¿Cómo verificás "escapa del sandbox" de forma robusta? (pista: `resolve()` y
  comparar rutas, no mirar el string).

## Bloque 4 — Resiliencia (reintentos al LLM)

- ¿Dónde envolvés la llamada? ¿Cada `self._llm.chat(...)` desnudo que tenés hoy
  debería seguir existiendo?
- ¿Qué excepciones son *transitorias* (reintentar) y cuáles no (aflorar limpio)?
  Armá tu lista y justificála.
- ¿Cuántos reintentos? ¿Con espera entre medio? ¿Cómo evitás que un test tarde
  minutos por culpa de los sleeps?
- ¿Cómo lo testeás sin red? Pista: el constructor de `MockLLMClient` acepta
  excepciones en la lista de respuestas, no solo `LLMResponse`.

## Bloque 5 — Cierre

- Conversación larga real (decenas de turnos, mensajes grandes) contra Ollama o
  Bedrock: ¿cada `run` sigue devolviendo `answer` no vacío? Tenés
  `student_framework/test/use_agent.py` como base.
- Tests propios: el enunciado pide en los criterios un prompt de salida
  estructurada "deliberadamente roto" en TU suite, y un timeout simulado que se
  recupera. Los tests de la cátedra no cubren eso por vos.
- Informe (`INFORME_OBLIGATORIO_M2.md`): faltan salida estructurada, errores en
  herramientas (con un ejemplo concreto de recuperación en cada tool) y modos de
  fallo dentro/fuera de alcance. La sección de memoria ya escrita: actualizala
  con lo que decidas en el Bloque 1.

## Checklist final (= criterios de aprobación del enunciado)

- [ ] Conversación que supera el presupuesto de contexto → el agente sigue sensato.
- [ ] Prompt estructurado roto → repara o falla limpio (test propio).
- [ ] Timeout simulado → se reintenta y termina con éxito (test propio).
- [ ] Calculadora y file_reader → mensajes claros y accionables.
- [ ] Tokens correctos en `AgentResult`.
- [ ] `pytest tests/conformance/test_m2.py` verde (y `test_m1.py` sigue verde).
- [ ] Informe completo.
