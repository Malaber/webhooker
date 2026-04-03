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
├── galaxy.yml
├── pyproject.toml
├── README.md
├── roles/
│   └── webhooker/
├── webhooker/
├── examples/
│   └── generic/
├── config/
│   ├── example.production.yaml
│   └── example.project.yaml
├── systemd/
├── scripts/
├── tests/
└── .github/workflows/ci.yml
```

## Ansible collection

This repository is also the root of the `malaber.webhooker` Ansible collection, so another repo can install it directly from Git without a subdirectory suffix.

Direct Git install:

```bash
ansible-galaxy collection install git+https://github.com/Malaber/webhooker.git
```

`requirements.yml` example for direct Git install:

```yaml
---
collections:
  - name: git+https://github.com/Malaber/webhooker.git
    type: git
```

Direct release tarball install:

```bash
ansible-galaxy collection install \
  https://github.com/Malaber/webhooker/releases/download/vX.Y.Z/malaber-webhooker-X.Y.Z.tar.gz
```

The collection exposes one role:

- `malaber.webhooker.webhooker`

The reusable role content lives in [`roles/webhooker/`](/Users/daniel/Git/Github.com/Malaber/webhooker/roles/webhooker), and the generic consumer example lives in [`examples/generic/`](/Users/daniel/Git/Github.com/Malaber/webhooker/examples/generic).

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

## How webhooker deploys your app

`webhooker` does not generate a Compose file for your application. You create and maintain the Compose template yourself, then point `webhooker` at it with:

- `deployment.compose_file`: the exact Compose file to run
- `deployment.working_directory`: the directory where `docker compose` should run

At reconcile time, `webhooker` executes commands like:

```bash
docker pull <image>
docker compose -p <project-name> -f <compose-file> up -d --remove-orphans
docker compose -p <project-name> -f <compose-file> down --remove-orphans
```

That means the app deployment template must already exist on the deploy host. A common layout is to keep everything for one app under a single self-contained root:

```text
/srv/example-app/
├── deploy/
│   ├── compose.review.yml
│   └── compose.production.yml
├── secrets/
│   ├── review.env
│   └── production.env
├── data/
│   ├── reviews/
│   └── production/
└── webhooker/
    ├── compose.yml
    ├── env/
    │   └── webhooker.env
    ├── projects/
    │   ├── example-review.yaml
    │   └── example-production.yaml
    └── runtime/
        ├── state/
        └── wake/
```

If you are onboarding a new app, think of the setup in three pieces:

1. Your app CI builds and pushes Docker images.
2. You write one or two app-specific Compose templates on the deploy host.
3. You write one `webhooker` YAML file per deployment mode that points to those templates.

## What your app Compose template must do

Your application Compose file should be a normal Compose file that can be started with `docker compose -f ... up -d`. The important difference is that it should read these environment variables, because `webhooker` injects them at runtime:

- `APP_IMAGE`: full image reference chosen by `webhooker`
- `APP_HOSTNAME`: hostname for Traefik or your reverse proxy
- `APP_DATA_DIR`: host directory where the app should store persistent data
- `APP_SQLITE_PATH`: host path to the SQLite file
- `TRAEFIK_ROUTER`
- `TRAEFIK_SERVICE`
- `TRAEFIK_CERTRESOLVER`

The safest mental model is: `webhooker` chooses the image tag and the per-environment names, but your Compose file still defines the containers, ports, volumes, labels, commands, and health checks for the app.

## Where your app settings should live

The settings for the deployed app are usually split into three groups:

1. Build-time defaults inside the app image.
   Example: Python module path, default port, or a default log level.
2. Non-secret runtime settings stored next to the app deployment templates.
   Example: feature flags, public base URLs, worker concurrency, or app mode.
3. Secret runtime settings stored only on the deploy host.
   Example: API keys, OAuth secrets, SMTP passwords, and production-only database credentials.

`webhooker` should not be the main place where your app settings live. Its YAML files are for deployment orchestration: which repo to watch, which image tags to use, where the data directories are, and which Compose template to run.

For most apps, a good layout is:

```text
/srv/example-app/
├── deploy/
│   ├── compose.review.yml
│   ├── compose.production.yml
│   ├── env/
│   │   ├── review.common.env
│   │   └── production.common.env
│   └── config/
│       ├── review.settings.toml
│       └── production.settings.toml
└── secrets/
    ├── review.env
    └── production.env
```

That gives you a clean rule:

- commit non-secret defaults in the app repo under `deploy/`
- publish secrets to the server under `/srv/<app-name>/secrets/`
- let the Compose template combine both at runtime

### Example: publishing runtime settings with Compose

This is a practical production example:

```yaml
services:
  app:
    image: ${APP_IMAGE}
    restart: unless-stopped
    env_file:
      - /srv/example-app/deploy/env/production.common.env
      - /srv/example-app/secrets/production.env
    volumes:
      - ${APP_DATA_DIR}:/data
      - /srv/example-app/deploy/config/production.settings.toml:/app/config/settings.toml:ro
    environment:
      APP_HOSTNAME: ${APP_HOSTNAME}
      SQLITE_PATH: ${APP_SQLITE_PATH}
```

In that example:

- the image is published by app CI
- the Compose template is published to `/srv/example-app/deploy/compose.production.yml`
- non-secret environment settings are published to `/srv/example-app/deploy/env/production.common.env`
- secret settings are published to `/srv/example-app/secrets/production.env`
- a config file is published to `/srv/example-app/deploy/config/production.settings.toml`

### Who should publish those files

The simplest answer is:

- the app repository should own `deploy/compose.*.yml`, `deploy/env/*.env`, and any non-secret config files
- your deployment process should copy those files to the deploy host, usually with `rsync`, Ansible, a CI deploy job, or a Git checkout on the server
- secrets should be created manually once or managed by your secret-management tool, but they should not be committed to Git

### What should go in the webhooker YAML vs the app files

Put this in the `webhooker` project YAML:

- GitHub repo name
- image registry and tag template
- deployment mode
- compose file path
- working directory
- host data paths
- wake/state paths
- branch name for production

Put this in the app Compose template or app env/config files:

- app ports
- reverse-proxy labels
- app framework settings
- feature flags
- API endpoints
- SMTP settings
- OAuth configuration
- secret keys and tokens

If you follow that split, `webhooker` stays small and generic, and the app keeps ownership of its real runtime configuration.

### Example review Compose template for an app

Store this on the deployment host, for example at `/srv/example-app/deploy/compose.review.yml`:

```yaml
services:
  app:
    image: ${APP_IMAGE}
    restart: unless-stopped
    environment:
      APP_HOSTNAME: ${APP_HOSTNAME}
      DATABASE_URL: sqlite:////data/app.db
    volumes:
      - ${APP_DATA_DIR}:/data
    labels:
      traefik.enable: "true"
      traefik.http.routers.${TRAEFIK_ROUTER}.rule: Host(`${APP_HOSTNAME}`)
      traefik.http.routers.${TRAEFIK_ROUTER}.entrypoints: websecure
      traefik.http.routers.${TRAEFIK_ROUTER}.tls.certresolver: ${TRAEFIK_CERTRESOLVER}
      traefik.http.services.${TRAEFIK_SERVICE}.loadbalancer.server.port: "8000"
```

This file is just an app deployment template. `webhooker` will reuse the same template for every PR, but with a different Compose project name, hostname, image tag, and data directory.

### Example production Compose template for an app

Store this on the deployment host, for example at `/srv/example-app/deploy/compose.production.yml`:

```yaml
services:
  app:
    image: ${APP_IMAGE}
    restart: unless-stopped
    environment:
      APP_HOSTNAME: ${APP_HOSTNAME}
      DATABASE_URL: sqlite:////data/app.db
    volumes:
      - ${APP_DATA_DIR}:/data
    labels:
      traefik.enable: "true"
      traefik.http.routers.${TRAEFIK_ROUTER}.rule: Host(`${APP_HOSTNAME}`)
      traefik.http.routers.${TRAEFIK_ROUTER}.entrypoints: websecure
      traefik.http.routers.${TRAEFIK_ROUTER}.tls.certresolver: ${TRAEFIK_CERTRESOLVER}
      traefik.http.services.${TRAEFIK_SERVICE}.loadbalancer.server.port: "8000"
```

For production, the template is usually almost identical. The difference is in the `webhooker` config: production tracks one branch and one long-lived data directory instead of creating one deployment per PR.

## Review deployment example

`config/example.project.yaml` shows a complete review deployment example. It manages one Compose project per PR and stores review SQLite files under `/srv/example-app/data/reviews/`.

### Step-by-step review setup

1. Build preview images in your app CI.
   Use tags like `pr-<number>-<sha7>` so they match `image.tag_template`.
2. Prepare the app root on the host.
   Example: create `/srv/example-app/deploy/compose.review.yml`.
3. Write the review Compose template for the app.
   The template should use `${APP_IMAGE}` and mount `${APP_DATA_DIR}` so each PR gets its own persistent SQLite file.
4. Copy the webhooker config.
   Start from `config/example.project.yaml` and save it as `/srv/example-app/webhooker/projects/example-review.yaml`.
5. Update the webhooker config fields.
   Set the GitHub repository, image registry, domain, and point `deployment.compose_file` at `/srv/example-app/deploy/compose.review.yml`.
6. Create the runtime directories.
   Example: `/srv/example-app/data/reviews`, `/srv/example-app/webhooker/runtime/state`, and `/srv/example-app/webhooker/runtime/wake`.
   Those writable bind mounts must be owned by the unprivileged container user that runs `webhooker` in the published image, which is uid/gid `1000:1000` by default.
   Mount the parent directories, not the `state_file` or `wake_file` paths themselves, so Docker never creates directories where those files should later appear.
7. Configure secrets for the host services.
   Export the GitHub API token and webhook secret so both `webhooker-api` and `webhooker-worker` can read them.
8. Expose the wake endpoint.
   Example: `https://webhooker.example.com/github/example-review/wake`.
9. Configure the GitHub webhook.
   Send `pull_request` and `ping` events for the same repository configured in the YAML.
10. Start `webhooker`.
    Enable `webhooker-api.service` and `webhooker-worker.timer`.

When a PR opens, synchronizes, or reopens, `webhooker` will:

- compute the image tag from the PR number and head SHA
- pull that image before switching the review deployment
- start `docker compose` with a PR-specific project name
- keep the PR SQLite file between image upgrades
- run the review seed command only the first time that PR environment is created

If the review image tag does not exist yet because app CI is still building it, `webhooker` temporarily serves a small loading page on the PR hostname instead of leaving Traefik with no backend. The worker keeps retrying the real image on each reconcile and swaps the placeholder out as soon as the image can be pulled.

## Production deployment example

`config/example.production.yaml` shows a complete production deployment example. It tracks the `main` branch, deploys one Compose project, and stores SQLite backups under `/srv/example-app/data/production/backups/`.

### Step-by-step production setup

1. Build production images in your app CI.
   Use a stable tag pattern like `sha-<sha7>` so it matches `image.production_tag_template`.
2. Prepare the app root on the host.
   Example: create `/srv/example-app/deploy/compose.production.yml`.
3. Write the production Compose template for the app.
   The template should mount `${APP_DATA_DIR}` so the SQLite file exists on the host and can be backed up before upgrades.
4. Copy the webhooker config.
   Start from `config/example.production.yaml` and save it as `/srv/example-app/webhooker/projects/example-production.yaml`.
5. Update the webhooker config fields.
   Set repository, image path, branch name, hostname, and point `deployment.compose_file` at `/srv/example-app/deploy/compose.production.yml`.
6. Create the runtime directories.
   Example: `/srv/example-app/data/production`, `/srv/example-app/data/production/backups`, `/srv/example-app/webhooker/runtime/state`, and `/srv/example-app/webhooker/runtime/wake`.
   Those writable bind mounts must be owned by the unprivileged container user that runs `webhooker` in the published image, which is uid/gid `1000:1000` by default.
   Mount the parent directories, not the `state_file` or `wake_file` paths themselves.
7. Configure secrets for the host services.
   Export the GitHub API token and webhook secret for the API and worker.
8. Expose the wake endpoint.
   Example: `https://webhooker.example.com/github/example-production/wake`.
9. Configure the GitHub webhook.
   Send `push` and `ping` events for the production repository.
10. Start `webhooker`.
    Enable the worker timer and the API service.

When the configured branch moves, `webhooker` will:

- resolve the new branch head SHA from GitHub
- stop the current Compose project
- copy the SQLite database into the backup directory
- keep only the newest three backups
- start the new image with the same long-lived data directory

## Recommended webhooker installation

The recommended installation is to run `webhooker` itself as two containers:

- one `webhooker-api` container
- one `webhooker-worker` container

The worker container is the only one that needs Docker access, so it should have the Docker socket mounted. Both containers should use the image published by this repository's CI.

The workflow publishes an image to:

- `ghcr.io/<owner>/<repo>/webhooker`

For this repository, that means:

- `ghcr.io/malaber/webhooker/webhooker:<tag>`

Stable releases publish both `<version>` and `latest`, but the recommended install pattern is to pin a concrete `<version>` tag in your own deployment config.

### Recommended host layout

```text
/srv/example-app/
├── deploy/
│   ├── compose.review.yml
│   ├── compose.production.yml
│   ├── env/
│   └── config/
├── secrets/
│   ├── review.env
│   └── production.env
├── data/
│   ├── reviews/
│   └── production/
└── webhooker/
    ├── compose.yml
    ├── env/
    │   └── webhooker.env
    ├── projects/
    │   ├── example-review.yaml
    │   └── example-production.yaml
    └── runtime/
        ├── state/
        └── wake/
```

### Recommended webhooker Compose stack

Store this on the deploy host, for example at `/srv/example-app/webhooker/compose.yml`:

```yaml
services:
  webhooker-api:
    image: ghcr.io/malaber/webhooker/webhooker:<release-version>
    restart: unless-stopped
    command:
      - webhooker-api
      - --config-dir
      - /srv/example-app/webhooker/projects
      - --host
      - 0.0.0.0
      - --port
      - "9100"
    env_file:
      - /srv/example-app/webhooker/env/webhooker.env
    volumes:
      - /srv/example-app/webhooker/projects:/srv/example-app/webhooker/projects:ro
      - /srv/example-app/webhooker/runtime/wake:/srv/example-app/webhooker/runtime/wake
    ports:
      - "127.0.0.1:9100:9100"

  webhooker-worker:
    image: ghcr.io/malaber/webhooker/webhooker:<release-version>
    restart: unless-stopped
    command:
      - /bin/sh
      - -lc
      - |
        while true; do
          webhooker-worker --config-dir /srv/example-app/webhooker/projects
          sleep 60
        done
    env_file:
      - /srv/example-app/webhooker/env/webhooker.env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /srv/example-app/webhooker/projects:/srv/example-app/webhooker/projects:ro
      - /srv/example-app/webhooker/runtime/state:/srv/example-app/webhooker/runtime/state
      - /srv/example-app/webhooker/runtime/wake:/srv/example-app/webhooker/runtime/wake
      - /srv/example-app:/srv/example-app
```

This setup keeps the trust boundary clean:

- the API container validates GitHub webhooks and only touches wake files
- the worker container reads project configs, talks to GitHub, and runs `docker compose`
- only the worker gets access to `/var/run/docker.sock`

### Why these mounts are required

- `/var/run/docker.sock`: lets the worker talk to the host Docker daemon
- `/srv/example-app/webhooker/projects`: lets both containers read the `webhooker` project YAML files
- `/srv/example-app/webhooker/runtime/state`: stores persisted reconciliation state
- `/srv/example-app/webhooker/runtime/wake`: stores wake files created by the API and consumed by the worker
- `/srv/example-app`: gives the worker access to the app Compose templates, secrets, and persistent app data under one self-contained root

If `/var/run/docker.sock` is owned by `root:<docker-gid>` with restrictive permissions, `webhooker` auto-detects that gid on the host and adds it to the worker container as a supplemental group instead of requiring the worker to run as root.

### Writable mount ownership

The published image runs both services as the unprivileged `webhooker` user, not as root. Any bind mount the API or worker must write to therefore needs host ownership or permissions that allow that user to write.

At minimum, make these writable mounts owned by uid/gid `1000:1000` on the host:

- `/srv/example-app/webhooker/runtime/state`
- `/srv/example-app/webhooker/runtime/wake`
- each app data root such as `/srv/example-app/data/reviews` and `/srv/example-app/data/production`
- any app secret env files that your Compose templates reference, such as `/srv/example-app/secrets/review.env`

### Recommended environment file for webhooker itself

Store this on the host at `/srv/example-app/webhooker/env/webhooker.env`:

```dotenv
GITHUB_TOKEN=replace-me
GITHUB_WEBHOOK_SECRET=replace-me

# Surrounding whitespace is ignored when webhook signatures are verified.
```

If you manage multiple projects with different GitHub credentials, you can still use one shared env file, or you can split secrets by container orchestration approach. The important rule is that the environment variable names must match the names used in each `webhooker` YAML file.

### Starting the webhooker stack

```bash
mkdir -p \
  /srv/example-app/deploy/env \
  /srv/example-app/deploy/config \
  /srv/example-app/secrets \
  /srv/example-app/data/reviews \
  /srv/example-app/data/production \
  /srv/example-app/webhooker/projects \
  /srv/example-app/webhooker/env \
  /srv/example-app/webhooker/runtime/state \
  /srv/example-app/webhooker/runtime/wake
chown -R 1000:1000 /srv/example-app/data /srv/example-app/webhooker/runtime
docker compose -f /srv/example-app/webhooker/compose.yml up -d
```

After that:

- point your reverse proxy at `127.0.0.1:9100`
- configure the GitHub webhook to call `/github/<project_id>/wake`
- place your app deployment templates, secrets, and data under `/srv/<app-name>/`

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

## Docker image

The repository `Dockerfile` builds the image used for both the API container and the worker container. It bundles the Docker CLI plus the Compose v2 plugin so the worker can use the mounted `/var/run/docker.sock` without installing extra packages on container start.

```bash
docker build -t webhooker:local .
```

## CI and release flow

The GitHub Actions workflow:

1. installs the project on Python 3.14
2. runs Black, mypy, and pytest with coverage
3. builds the production Docker image
4. publishes the image to GHCR on successful pushes

Pushes to `main` now compute the next patch version from git tags, stamp that version into `pyproject.toml` and `galaxy.yml`, commit it back to `main`, and only then build release artifacts from that exact source. The reusable versioning, version-stamping, and Ansible collection release logic now live in [`Malaber/github-workflows`](https://github.com/Malaber/github-workflows), so other repositories can share the same tag and GitHub Release flow without keeping their own stamping script. Stable releases publish both `<version>` and `latest` image tags, while non-`main` branch pushes publish matching `-rc.<run>` prerelease versions without moving `latest`. The repository root is the collection root, and the release asset is published to the matching GitHub Release so another infra repo can install it directly.

## Troubleshooting

- **401 from webhook**: confirm the GitHub secret matches and `X-Hub-Signature-256` is present
- **403 from webhook**: verify the payload repository matches the configured `owner/repo`
- **review DB reset unexpectedly**: check whether the PR was deleted and recreated instead of updated
- **production backup missing**: verify `production.sqlite_path` points to the host-mounted SQLite file
- **compose failure**: manually run the generated compose command with the same project name
- **wildcard TLS failure**: wildcard review domains require DNS-01

## Operational note

This design is safer than exposing a public service with direct Docker access, but both review and production deployments still execute application code. Keep production secrets isolated, and do not allow review environments to share unrestricted access to production-only infrastructure.
