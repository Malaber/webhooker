# webhooker

`webhooker` is a reusable Python 3.14 service that manages per-pull-request preview deployments for Docker Compose applications. It splits responsibilities into a minimal public webhook API and a privileged worker so incoming requests can only wake reconciliation, never control what gets deployed.

## What webhooker does

- Loads one or more project definitions from YAML.
- Polls GitHub for open pull requests for each configured project.
- Computes the desired image tag for every PR from trusted configuration and GitHub state.
- Reconciles local preview deployments with `docker compose` using one Compose project name per PR.
- Removes stale deployments when PRs close or merge.
- Persists deployment state locally.
- Supports seeded SQLite preview environments with fresh data on redeploy.
- Exposes a tiny FastAPI wake endpoint that validates GitHub HMAC signatures and only touches a wake file.

## Architecture

```text
GitHub webhook
    |
    v
webhooker-api (FastAPI)
    - validate X-Hub-Signature-256
    - verify event type and repository
    - touch wake file
    - return 202 Accepted

systemd timer / manual execution
    |
    v
webhooker-worker
    - load project configs
    - query GitHub API for open PRs
    - compute desired state
    - run docker compose up/down per PR
    - reset preview data and seed SQLite if configured
    - persist state
```

## Repository layout

```text
webhooker/
├── AGENTS.md
├── Dockerfile
├── pyproject.toml
├── README.md
├── webhooker/
│   ├── __init__.py
│   ├── api.py
│   ├── cli.py
│   ├── config.py
│   ├── deployer.py
│   ├── github_client.py
│   ├── logging_utils.py
│   ├── models.py
│   ├── paths.py
│   ├── security.py
│   ├── state.py
│   ├── wake.py
│   └── worker.py
├── config/
│   └── example.project.yaml
├── systemd/
│   ├── webhooker-api.service
│   ├── webhooker-worker.service
│   └── webhooker-worker.timer
├── scripts/
│   └── bootstrap.sh
├── tests/
└── .github/workflows/ci.yml
```

## Configuration reference

Each application managed by `webhooker` gets one YAML project file.

- `project_id`: stable routing identifier used in `/github/<project_id>/wake`.
- `github`: repository owner/name, token env var, webhook secret env var, and allowed event types.
- `deployment`: compose file path, working directory, compose binary, project name prefix, and hostname template.
- `image`: registry/repository and tag template, for example `pr-{pr}-{sha7}`.
- `preview`: per-PR preview base directory, SQLite path template, reset behavior, and an optional seed command.
- `reconcile`: worker polling and redeploy behavior.
- `traefik`: optional router/service label inputs and cert resolver.
- `state`: JSON file path for persisted deployment state.
- `wake`: wake file path touched by the webhook.

See `config/example.project.yaml` for the full example.

## Target app compose file requirements

The target application owns its static preview compose file. `webhooker` reuses that file and supplies runtime environment variables.

Expected variables:

- `APP_IMAGE`
- `APP_HOSTNAME`
- `APP_DATA_DIR`
- `APP_SQLITE_PATH`
- `TRAEFIK_ROUTER`
- `TRAEFIK_SERVICE`
- `TRAEFIK_CERTRESOLVER`

Because Docker Compose isolates deployments by project name, the same preview compose file can be launched repeatedly as `listerine-pr-12`, `listerine-pr-18`, and so on.

## Security model

### What the webhook is allowed to do

- Verify `X-Hub-Signature-256`.
- Validate the configured `project_id`.
- Filter allowed event types.
- Verify the repository identity.
- Touch a wake file.

### What the webhook is not allowed to do

- Accept an image URL.
- Accept a compose file path.
- Accept a command to execute.
- Accept a PR number to deploy.
- Talk to Docker directly.

### What the worker does

- Talks to the GitHub API.
- Computes desired preview state.
- Runs `docker compose`.
- Removes stale previews.
- Resets preview data and optionally seeds SQLite.
- Persists deployment state.

## Local development

### Install

```bash
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
```

### Run tests and checks

```bash
python -m ruff check .
python -m mypy webhooker
python -m pytest
```

## Running the services

### API

```bash
webhooker-api --config-dir /etc/webhooker/projects --host 127.0.0.1 --port 9100
```

### Worker

```bash
webhooker-worker --config-dir /etc/webhooker/projects
```

## Systemd setup

Use the files in `systemd/` and enable the timer-driven worker:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now webhooker-api.service
sudo systemctl enable --now webhooker-worker.timer
```

You can manually trigger reconciliation any time with:

```bash
sudo systemctl start webhooker-worker.service
```

## GitHub webhook setup

Configure the webhook URL like this:

```text
https://webhooker.example.com/github/<project_id>/wake
```

Recommended settings:

- content type: `application/json`
- secret: same value referenced by `webhook_secret_env`
- events: `Pull requests` and optionally `Ping`

The API returns `202 Accepted` for valid wake requests and never deploys directly.

## GHCR token setup

If preview images are stored in GHCR, provide a token with package-read permissions via the environment variable named in the project config.

## Docker image

A production image is provided by the repository `Dockerfile` and targets Python 3.14 on `python:3.14-slim`.

Example local build:

```bash
docker build -t webhooker:local .
```

## CI and release flow

The GitHub Actions workflow in `.github/workflows/ci.yml`:

1. installs the project on Python 3.14
2. runs Ruff, mypy, and pytest with coverage
3. builds the production Docker image
4. publishes the image to GHCR on successful pushes to `main` or version tags

## Troubleshooting

- **401 from webhook**: confirm the GitHub secret matches and that `X-Hub-Signature-256` is present.
- **403 from webhook**: verify the payload repository matches the configured `owner/repo`.
- **worker GitHub auth failure**: verify the token env var exists for the service user.
- **preview not created**: confirm the worker can read the project config and the image tag exists.
- **compose failure**: manually run the generated compose command with the same project name.
- **wildcard TLS failure**: Traefik wildcard preview domains require DNS-01.

## Operational note

This design is safer than exposing a public service with direct Docker access, but preview environments still execute PR code. Treat the staging host as less trusted than production and do not share production secrets or unrestricted private network access with it.
