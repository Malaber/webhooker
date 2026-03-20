# AGENTS.md

## Scope
These instructions apply to the entire repository.

## Project goals
- Keep the trust boundary strict: the API only validates GitHub webhook requests and signals reconciliation.
- The worker is the only component allowed to talk to GitHub, decide desired state, or invoke Docker Compose.
- Target Python 3.14 for development, CI, and container images.
- Support both review deployments and production deployments.

## Development guidelines
- Prefer standard library plus the dependencies declared in `pyproject.toml`; do not add ad-hoc compatibility shims for missing packages.
- Keep modules small, typed, and directly testable.
- Use `subprocess.run([...], check=True)` only. Never use `shell=True`.
- Format code with Black.
- When adding config or runtime behavior, update `README.md`, `config/`, and tests together.
- Keep tests deterministic and isolated from network and Docker by mocking external calls.

## Useful commands
- `python3.14 -m venv .venv`
- `.venv/bin/python -m pip install -e '.[dev]'`
- `.venv/bin/python -m black webhooker tests scripts`
- `.venv/bin/python -m black --check .`
- `.venv/bin/python -m pytest --cov=webhooker --cov-report=term-missing`
- `.venv/bin/python -m mypy webhooker`

## Local validation workflow
- Use Python 3.14 in a local virtualenv for all development and release validation.
- Install dependencies with `.venv/bin/python -m pip install -e '.[dev]'`.
- Run Black in fix mode on project sources first with `.venv/bin/python -m black webhooker tests scripts`.
- Then run the production gates with `.venv/bin/python -m black --check .`, `.venv/bin/python -m mypy webhooker`, and `.venv/bin/python -m pytest`.
- Keep local virtualenv directories ignored and outside formatter scope so `black --check .` only validates repository code.
