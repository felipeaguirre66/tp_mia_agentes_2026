"""Chat interactivo mínimo: solo muestra el answer de cada turno.

Uso:
    python student_framework/test/chat.py

Salir con Ctrl+C o escribiendo "salir".
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite ejecutar este script desde cualquier directorio.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from student_framework import build_agent


def main() -> None:
    agent = build_agent()
    print("Chat listo. Ctrl+C o 'salir' para terminar.")

    try:
        while True:
            user_message = input("> ").strip()
            if not user_message:
                continue
            if user_message.lower() in ("salir", "exit", "quit"):
                break

            result = agent.run(user_message)
            print(result.answer)
            if result.error:
                print(f"[error] {result.error}")
    except (KeyboardInterrupt, EOFError):
        pass
    print("\nChau.")


if __name__ == "__main__":
    main()
