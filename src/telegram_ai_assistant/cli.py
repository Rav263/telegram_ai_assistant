from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from collections.abc import Sequence
from typing import Callable, Mapping

from . import __version__
from .app_context import AppContext
from .config import Settings
from .env import load_environment
from .runtime import PROCESS_NAMES, offline_health_report, run_process


ContextFactory = Callable[[Mapping[str, str]], AppContext]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-ai-assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("process", choices=PROCESS_NAMES)

    health_parser = subparsers.add_parser("health")
    health_parser.add_argument("--offline", action="store_true")

    subparsers.add_parser("migrate")

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env_file: Path = Path(".env"),
    environ: Mapping[str, str] | None = None,
    context_factory: ContextFactory = AppContext.from_environment,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "run":
        environment = load_environment(env_file, os.environ if environ is None else environ)
        return run_process(args.process, Settings.from_env(environment))
    if args.command == "health":
        if not args.offline:
            raise NotImplementedError("online health checks are not wired yet")
        report = offline_health_report()
        print(
            json.dumps(
                {
                    "status": report.status.value,
                    "components": [
                        {
                            "name": component.name,
                            "status": component.status.value,
                            "details": dict(component.details or {}),
                        }
                        for component in report.components
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "migrate":
        try:
            environment = load_environment(env_file, os.environ if environ is None else environ)
            context = context_factory(environment)
            context.migrate()
        except Exception as exc:
            print(f"migration failed: {type(exc).__name__}")
            return 1
        print("migration applied")
        return 0
    raise ValueError(f"unknown command: {args.command}")
