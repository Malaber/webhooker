# webhooker

`webhooker` is a reusable Python 3.14 service for Docker Compose deployments. It supports two deployment modes:

- **review deployments**: one isolated environment per pull request
- **production deployments**: one long-lived deployment that tracks a configured branch

The public API only validates GitHub webhooks and wakes reconciliation. The worker is the only process allowed to talk to GitHub, decide desired state, manage SQLite backups, and invoke `docker compose`.

## What webhooker does

- Loads one or more project definitions from YAML.
- Polls GitHub for open pull requests or a production branch head, depending on deployment mode.
- Computes desired image tags from trusted configuration and GitHub state.
- Reconciles local Docker Compose deployments.
- Persists deployment state locally.
- Validates `X-Hub-Signature-256` on the wake endpoint.
- Supports review environments with persistent per-PR SQLite data.
- Supports production deployments with automatic SQLite backups before roll-forward.

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
    - query GitHub API
    - compute desired state
    - review mode: reconcile one Compose project per PR
    - production mode: reconcile one Compose project for a branch
    - keep state on disk
```

## Repository layout

```text
webhooker/
├── AGENTS.md
├── Dockerfile
├── pyproject.toml
├── README.md
├── webhooker/
├── config/
│   ├── example.production.yaml
│   └── example.project.yaml
├── systemd/
├── scripts/
├── tests/
└── .github/workflows/ci.yml
```

## Deployment modes

### Review mode behavior

- The worker polls open PRs.
- Each PR gets its own Compose project name and hostname.
- The SQLite database is kept across image changes for the same PR.
- Seed commands run **only** on first creation of that PR environment.
- When the PR closes, the worker removes the deployment and deletes the review data directory.

### Production mode behavior

- The worker polls the configured branch, typically `main`.
- Only one Compose project is deployed.
- On image change, the worker:
  1. stops the current container stack
  2. copies the SQLite file into a timestamped backup directory
  3. keeps only the newest 3 backups
  4. starts the new container stack
- Seed commands run only when the production SQLite database does not exist yet.

## Configuration reference

Each managed target gets one YAML file.

### Shared sections

- `project_id`: identifier used by `/github/<project_id>/wake`
- `github`: repository owner/name, token env var, webhook secret env var, and allowed event types
- `deployment`: compose file details plus mode-specific deployment fields
- `image`: registry/repository and tag templates
- `reconcile`: polling and redeploy behavior
- `traefik`: label and certificate resolver inputs
- `state`: JSON file path for persisted state
- `wake`: wake file path touched by the webhook API

### Review mode sections

Set `deployment.mode: review` and provide:

- `deployment.hostname_template`
- `deployment.project_name_prefix`
- `preview.base_dir`
- `preview.data_dir_template`
- `preview.sqlite_path_template`
- optional `preview.seed_command`

### Production mode sections

Set `deployment.mode: production` and provide:

- `deployment.production_project_name`
- `deployment.production_hostname`
- `production.branch`
- `production.data_dir`
- `production.sqlite_path`
- `production.backup_dir`
- `production.backup_keep`
- optional `production.seed_command`
- optional `image.production_tag_template`

## Review deployment example

`config/example.project.yaml` shows a complete review deployment example. It manages one Compose project per PR and stores review SQLite files under `/srv/webhooker/reviews/example-app/`.

### How to configure and use webhooker for review deployments

1. Build preview images in your app CI using a PR tag like `pr-<number>-<sha7>`.
2. Install `webhooker` on the review host.
3. Copy `config/example.project.yaml` to `/etc/webhooker/projects/example-review.yaml` and adjust repository/image/domain values.
4. Point your reverse proxy to `https://webhooker.example.com/github/example-review/wake`.
5. Configure a GitHub webhook secret and export matching environment variables for the systemd services.
6. Enable `webhooker-api.service` and `webhooker-worker.timer`.
7. When a PR opens, synchronizes, or reopens, GitHub wakes the worker and the worker reconciles the per-PR review environment.

## Production deployment example

`config/example.production.yaml` shows a complete production deployment example. It tracks the `main` branch, deploys one Compose project, and stores SQLite backups under `/srv/webhooker/production/example-app/backups/`.

### How to configure and use webhooker for production deployments

1. Build and publish production images in your app CI using a stable production tag template such as `sha-<sha7>`.
2. Copy `config/example.production.yaml` to `/etc/webhooker/projects/example-production.yaml` and update repository/image/hostname/path values.
3. Ensure the target app Compose file uses the host-mounted `APP_DATA_DIR` and `APP_SQLITE_PATH`.
4. Expose the wake endpoint, for example `https://webhooker.example.com/github/example-production/wake`.
5. Configure GitHub to send `push` and `ping` events for the production repository.
6. Enable the worker timer. On each branch SHA change, webhooker stops the old stack, backs up SQLite, keeps the newest 3 backups, and starts the new stack.

## Security model

### What the webhook is allowed to do

- Verify `X-Hub-Signature-256`
- Validate the configured `project_id`
- Filter allowed event types
- Verify the repository identity
- Touch a wake file

### What the webhook is not allowed to do

- Accept an image URL
- Accept a compose file path
- Accept a command to execute
- Accept a PR number to deploy
- Talk to Docker directly

### What the worker does

- Talks to the GitHub API
- Computes desired review or production state
- Runs `docker compose`
- Removes stale review environments
- Backs up SQLite before production upgrades
- Persists deployment state

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
python -m black --check .
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

To reconcile immediately:

```bash
sudo systemctl start webhooker-worker.service
```

## Docker image

The repository `Dockerfile` builds a production image based on `python:3.14-slim`.

```bash
docker build -t webhooker:local .
```

## CI and release flow

The GitHub Actions workflow:

1. installs the project on Python 3.14
2. runs Black, mypy, and pytest with coverage
3. builds the production Docker image
4. publishes the image to GHCR on successful pushes to `main` or version tags

## Troubleshooting

- **401 from webhook**: confirm the GitHub secret matches and `X-Hub-Signature-256` is present
- **403 from webhook**: verify the payload repository matches the configured `owner/repo`
- **review DB reset unexpectedly**: check whether the PR was deleted and recreated instead of updated
- **production backup missing**: verify `production.sqlite_path` points to the host-mounted SQLite file
- **compose failure**: manually run the generated compose command with the same project name
- **wildcard TLS failure**: wildcard review domains require DNS-01

## Operational note

This design is safer than exposing a public service with direct Docker access, but both review and production deployments still execute application code. Keep production secrets isolated, and do not allow review environments to share unrestricted access to production-only infrastructure.
