from __future__ import annotations

import argparse
import sys

import uvicorn

from webhooker.api import create_app
from webhooker.config import load_project_configs
from webhooker.logging_utils import configure_logging
from webhooker.worker import reconcile_project


def run_api() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()

    configure_logging()
    app = create_app(args.config_dir)
    uvicorn.run(app, host=args.host, port=args.port)


def run_worker() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", required=True)
    args = parser.parse_args()

    configure_logging()
    configs = load_project_configs(args.config_dir)
    had_error = False

    for config in configs:
        try:
            reconcile_project(config)
        except Exception as exc:  # pragma: no cover
            had_error = True
            print(f"[ERROR] project={config.project_id}: {exc}", file=sys.stderr)

    if had_error:
        raise SystemExit(1)
