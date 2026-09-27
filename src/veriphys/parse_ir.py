"""CLI for inspecting the Physics IR stage."""

from __future__ import annotations

import argparse
import json

from .parser import PhysicsParser


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse a physics problem into Physics IR")
    parser.add_argument("--problem", required=True)
    parser.add_argument("--answer")
    args = parser.parse_args()

    try:
        ir = PhysicsParser().parse(args.problem, args.answer)
    except Exception as exc:
        print(f"Status: ERROR\nReason: {exc}")
        return 1
    print(json.dumps(ir.model_dump(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
