from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
import os
from pathlib import Path
from typing import Callable, Mapping

from . import __version__
from .app_context import AppContext
from .config import LOG_LEVELS, Settings
from .env import load_environment
from .logging_config import configure_logging
from .runtime import PROCESS_NAMES, offline_health_report, run_process


ContextFactory = Callable[[Mapping[str, str]], AppContext]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telegram-ai-assistant")
    parser.add_argument("--log-level", choices=sorted(LOG_LEVELS), default=None, type=str.upper)
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
    runners: Mapping[str, Callable[[Settings], int]] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        configure_logging(args.log_level or "INFO")
        print(__version__)
        return 0
    if args.command == "run":
        environment = _load_environment(args.log_level, env_file, environ)
        settings = Settings.from_env(environment)
        configure_logging(settings.log_level)
        return run_process(args.process, settings, runners=runners)
    if args.command == "health":
        if args.offline:
            environment = _load_environment(args.log_level, env_file, environ)
            configure_logging(environment.get("LOG_LEVEL", "INFO"))
            report = offline_health_report()
        else:
            try:
                environment = _load_environment(args.log_level, env_file, environ)
                configure_logging(environment.get("LOG_LEVEL", "INFO"))
                report = context_factory(environment).online_health_report()
            except Exception as exc:
                print(f"health check failed: {type(exc).__name__}")
                return 1
        print(json.dumps(_health_report_payload(report), sort_keys=True))
        return 0
    if args.command == "migrate":
        try:
            environment = _load_environment(args.log_level, env_file, environ)
            configure_logging(environment.get("LOG_LEVEL", "INFO"))
            context = context_factory(environment)
            context.migrate()
        except Exception as exc:
            print(f"migration failed: {type(exc).__name__}")
            return 1
        print("migration applied")
        return 0
    raise ValueError(f"unknown command: {args.command}")


def _load_environment(
    log_level_override: str | None,
    env_file: Path,
    environ: Mapping[str, str] | None,
) -> Mapping[str, str]:
    environment = dict(load_environment(env_file, os.environ if environ is None else environ))
    if log_level_override is not None:
        environment["LOG_LEVEL"] = log_level_override
    return environment


def _health_report_payload(report):
    return {
        "status": report.status.value,
        "components": [
            {
                "name": component.name,
                "status": component.status.value,
                "details": dict(component.details or {}),
            }
            for component in report.components
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
