# Informe M2

## 1. Estrategia de memoria

Implementamos una estrategia de memoria de tipo sliding window dentro del agente. En cada llamada a `run(...)`, el historial previo se conserva en memoria de instancia (`self._history`), se agrega el nuevo mensaje del usuario y se recorta para no superar `max_history_messages`.

La política de recorte prioriza:
- Mantener siempre el primer mensaje del usuario (suele ser el más importante).
- Mantener los max_history_messages-1 mensajes más recientes. Estos son probablemente los más relevantes para la conversación actual.

### Problemas encontrados

No hubieron problemas significativos más que la decisión de qué mensajes conservar. Podríamos haber dejado algunos mensajes del comienzo (como la primera respuesta del agente), o implementar una estrategua de resumir mensajes antiguos.
