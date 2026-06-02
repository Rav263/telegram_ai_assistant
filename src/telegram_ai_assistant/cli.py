from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from . import __version__
from .config import Settings
from .runtime import PROCESS_NAMES, run_process


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-ai-assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("process", choices=PROCESS_NAMES)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "run":
        return run_process(args.process, Settings.from_env(os.environ))
    raise ValueError(f"unknown command: {args.command}")
