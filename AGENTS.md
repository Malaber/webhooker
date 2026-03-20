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
- `python3.14 -m pip install -e .[dev]`
- `python3.14 -m black .`
- `python3.14 -m pytest --cov=webhooker --cov-report=term-missing`
- `python3.14 -m mypy webhooker`
