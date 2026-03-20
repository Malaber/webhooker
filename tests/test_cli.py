from __future__ import annotations

from pathlib import Path

import pytest

from webhooker import cli


def test_run_api_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch, config_dir: Path) -> None:
    called: dict[str, object] = {}

    def fake_run(app, host: str, port: int) -> None:
        called["app"] = app
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli.uvicorn, "run", fake_run)
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: cli.argparse.Namespace(
            config_dir=str(config_dir),
            host="127.0.0.1",
            port=9100,
        ),
    )

    cli.run_api()

    assert called["host"] == "127.0.0.1"
    assert called["port"] == 9100


def test_run_worker_raises_exit_code_on_project_error(
    monkeypatch: pytest.MonkeyPatch,
    review_project_config,
) -> None:
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "load_project_configs", lambda _: [review_project_config])
    monkeypatch.setattr(
        cli, "reconcile_project", lambda _: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setattr(
        cli.argparse.ArgumentParser,
        "parse_args",
        lambda self: cli.argparse.Namespace(config_dir="/tmp"),
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.run_worker()

    assert excinfo.value.code == 1
