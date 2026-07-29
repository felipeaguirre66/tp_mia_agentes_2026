from __future__ import annotations

import json
import sys
from pathlib import Path

# Permite ejecutar este script desde cualquier directorio.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from student_framework import build_agent


def main() -> None:
    agent = build_agent()
    turn = 1

    print("Multi-turn chat ready. Press Ctrl+C to exit.")

    try:
        while True:
            user_message = input(f"you[{turn}]> ").strip()
            if not user_message:
                continue

            result = agent.run(user_message)

            print(f"assistant[{turn}]> {result.answer}")
            print(f"final_response[{turn}]> {result.answer}")
            if result.error:
                print(f"error[{turn}]> {result.error}")

            history_length = len(agent._history)  # type: ignore[attr-defined]
            print(f"messages_length[{turn}]> {history_length}")
            print("messages>")
            print(
                json.dumps(
                    agent._history,  # type: ignore[attr-defined]
                    indent=2,
                    ensure_ascii=False,
                )
            )
            turn += 1
    except (KeyboardInterrupt, EOFError):
        print("\nExiting chat.")


if __name__ == "__main__":
    main()
