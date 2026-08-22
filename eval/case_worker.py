"""Worker aislado para ejecutar exactamente un caso de M3.

`eval.run` lo lanza como subprocess para que `--timeout` cubra también una
llamada LLM bloqueada. El único contenido de stdout es el registro JSON.
"""

from __future__ import annotations

import argparse
import json
import sys

from eval.harness import run_case


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.case_worker")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--repeat", required=True, type=int)
    parser.add_argument("--max-tool-calls", required=True, type=int)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    llm_client = None
    if args.dry_run:
        from eval.fake_llm import LookOnceLLM

        llm_client = LookOnceLLM()

    record = run_case(
        args.scenario,
        args.config,
        repeat=args.repeat,
        llm_client=llm_client,
        max_tool_calls=args.max_tool_calls,
        timeout_s=args.timeout,
    )
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
