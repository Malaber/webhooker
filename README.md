# webhooker

`webhooker` is a reusable Python service that manages pull-request preview environments for Docker Compose applications. It keeps a small public-facing webhook separate from the privileged deployment worker so that GitHub webhooks can only wake the reconciler, never instruct it what to deploy.

## What webhooker does

- Loads one or more project definitions from YAML.
- Polls GitHub for open pull requests per configured project.
- Computes the expected preview image tag for each PR.
- Reconciles local Docker Compose deployments so open PRs are deployed and closed PRs are removed.
- Persists deployment state locally.
- Supports seeded SQLite preview data that can be reset on redeploy.
- Exposes a tiny FastAPI wake endpoint that only validates GitHub signatures and touches a wake file.

## Architecture

```text
GitHub webhook
    |
    v
webhooker-api (FastAPI)
    - validate X-Hub-Signature-256
    - verify event type and repository
    - touch wake file
    - return 202

systemd timer / manual start
    |
    v
webhooker-worker
    - load project config(s)
    - query GitHub API for open PRs
    - compute desired previews
    - docker compose up/down per PR
    - reset preview data and seed SQLite if configured
    - persist state file
```

## Repository layout

```text
webhooker/
├── pyproject.toml
├── README.md
├── webhooker/
├── config/
├── systemd/
├── scripts/
└── tests/
```

## Configuration reference

Each target application gets one YAML file under a config directory passed to the API and worker.

Important sections:

- `github`: repository identity, token env var, webhook secret env var, and allowed event types.
- `deployment`: static compose file path, compose binary, project name prefix, and hostname template.
- `image`: registry/repository and tag template, such as `pr-{pr}-{sha7}`.
- `preview`: per-PR data directory paths and an optional seed command.
- `reconcile`: polling interval, closed-PR cleanup, and SHA-based redeploy behavior.
- `state`: JSON state file path.
- `wake`: wake file path used by the webhook.

See `config/example.project.yaml` for a complete example.

## Target app compose file requirements

The target application owns its static preview compose file. `webhooker` reuses that file and relies on a unique Docker Compose project name per PR deployment.

The compose file should read these environment variables:

- `APP_IMAGE`
- `APP_HOSTNAME`
- `APP_DATA_DIR`
- `TRAEFIK_ROUTER`
- `TRAEFIK_SERVICE`
- `TRAEFIK_CERTRESOLVER`

A preview compose file can then be deployed repeatedly by varying the compose project name, for example `listerine-pr-12` and `listerine-pr-18`.

## Setup

### 1. Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
```

Or use the bootstrap helper on the target host:

```bash
sudo ./scripts/bootstrap.sh
```

### 2. Create project configs

Copy `config/example.project.yaml` to your config directory and fill in repository-specific values.

### 3. Export secrets

Provide the GitHub token and webhook secret via environment variables referenced by the config file.

Example:

```bash
export GITHUB_TOKEN=ghp_redacted
export GITHUB_WEBHOOK_SECRET=replace_me
```

### 4. Systemd setup

Install the provided units from `systemd/` and then enable the API service and worker timer:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now webhooker-api.service
sudo systemctl enable --now webhooker-worker.timer
```

You can also run the worker manually:

```bash
webhooker-worker --config-dir /etc/webhooker/projects
```

## GitHub webhook setup

Configure GitHub to send the webhook to the wake endpoint:

```text
https://webhooker.example.com/github/<project_id>/wake
```

Recommended settings:

- Content type: `application/json`
- Secret: same value as the environment variable referenced by `webhook_secret_env`
- Events: `Pull requests` and optionally `Ping`

The webhook endpoint validates `X-Hub-Signature-256`, rejects unknown projects, rejects repository mismatches, and ignores unexpected event types.

## GHCR token setup

If preview images are stored in GHCR, provide a token that can read the package and query the repository metadata. Keep the token in environment or a secret manager, not in YAML files.

## Reconciliation flow

For each configured project, the worker:

1. Loads the local state file.
2. Queries GitHub for open pull requests.
3. Removes stale deployments for PRs that are no longer open.
4. Deploys previews for newly opened PRs.
5. Redeploys previews when the tracked PR head SHA changes.
6. Saves the updated state file.
7. Clears the wake file.

## Security model

### Webhook allowed actions

- Verify GitHub HMAC signatures.
- Check project ID, repository, and event type.
- Touch a wake file.

### Webhook forbidden actions

- It never accepts an image URL.
- It never accepts a compose file path.
- It never accepts a command to run.
- It never accepts a PR number to deploy.
- It never talks to Docker directly.

### Worker responsibilities

- Talks to the GitHub API.
- Computes desired preview state.
- Runs `docker compose`.
- Removes stale preview deployments.
- Resets preview data and optionally seeds SQLite.

## Troubleshooting

- **Webhook returns 401**: confirm the shared secret matches GitHub and the `X-Hub-Signature-256` header is present.
- **Webhook returns 403**: check that the payload repository matches the configured `owner/repo`.
- **Worker exits with GitHub auth errors**: verify the token env var exists for the service user.
- **No previews are created**: confirm the project config is in the configured directory and the worker can read it.
- **Compose deployment fails**: run the generated `docker compose` command manually with the same project name to inspect container errors.
- **Wildcard TLS fails for PR subdomains**: configure Traefik DNS-01 for wildcard certificates.

## Testing

Run the test suite with:

```bash
pytest
```

## Operational note

This design is safer than exposing a public service with direct Docker access, but preview environments still run PR code. Treat the staging host as less trusted than production and do not share sensitive secrets or unrestricted internal network access.
