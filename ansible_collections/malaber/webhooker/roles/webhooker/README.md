# malaber.webhooker.webhooker

`malaber.webhooker.webhooker` deploys the `webhooker-api` and `webhooker-worker` containers with Docker Compose, writes one or more `webhooker` project YAML files, publishes app bundle files to the target host, and renders secret env files used by managed apps.

## Requirements

- Docker and the Docker Compose plugin are already installed on the target host.
- The playbook usually runs with `become: true` because the default paths live under `/opt`, `/etc`, `/var/lib`, and `/srv`.
- The worker container needs bind mounts for every host path referenced by the app Compose files it will execute.

## Variables

### Core paths and stack settings

- `webhooker_deploy_path`: host directory that stores `docker-compose.yml`. Default: `/opt/webhooker`
- `webhooker_compose_project_name`: Compose project name for the `webhooker` stack. Default: `webhooker`
- `webhooker_config_dir`: directory that holds `webhooker` project YAML files. Default: `/etc/webhooker/projects`
- `webhooker_env_dir`: directory that holds `webhooker.env`. Default: `/etc/webhooker/env`
- `webhooker_state_dir`: directory for persisted worker state. Default: `/var/lib/webhooker/state`
- `webhooker_wake_dir`: directory for wake files written by the API and consumed by the worker. Default: `/var/lib/webhooker/wake`
- `webhooker_image`: container image for both services. Default: `ghcr.io/malaber/webhooker/webhooker:main`
- `webhooker_api_bind_address`: address used for the published API port. Default: `127.0.0.1`
- `webhooker_api_port`: published API port. Default: `9100`
- `webhooker_worker_sleep_seconds`: polling delay between worker runs inside the long-running worker container. Default: `60`
- `webhooker_compose_pull`: whether the role runs `docker compose pull` before `up`. Default: `true`

### Runtime data

- `webhooker_env`: dictionary rendered to `/etc/webhooker/env/webhooker.env`
- `webhooker_projects`: list of project definitions rendered to `<webhooker_config_dir>/<filename>`
- `webhooker_worker_extra_mounts`: extra bind mounts added to the worker container
- `webhooker_managed_files`: controller-side files to copy to the target host
- `webhooker_secret_env_files`: dotenv files rendered on the target host, usually from vaulted values

## `webhooker_projects` Shape

Each list item must contain:

- `filename`
- `content`

The role writes each item to `<webhooker_config_dir>/<filename>` and renders `content` as YAML without reinterpreting the nested structure in Ansible.

The documented examples use the schema `webhooker` validates today. That means the project content must use keys such as:

- `github.token_env`
- `github.webhook_secret_env`
- `github.required_event_types`
- `reconcile.poll_interval_seconds`
- `state.state_file`
- `wake.wake_file`

Review image templates should use placeholders like `{pr}` and `{sha7}`. Production image templates should use `{sha}` or `{sha7}`. Production configs still need `deployment.project_name_prefix` because the current `webhooker` model requires it.

## Managed Files

`webhooker_managed_files` is how an infra repo publishes app-owned deployment assets to the target host.

Example:

```yaml
webhooker_managed_files:
  - src: files/example-app/deploy/webhooker/compose.review.yml
    dest: /opt/example-app/deploy/webhooker/compose.review.yml
    mode: "0644"
```

Each item supports:

- `src`
- `dest`
- `mode`
- `owner`
- `group`

The role creates the parent directory for each destination before copying the file.

## Secret Env Files

`webhooker_secret_env_files` renders dotenv files on the target host.

Example:

```yaml
webhooker_secret_env_files:
  - path: /etc/example-app/review.secrets.env
    mode: "0600"
    content:
      SECRET_KEY: "{{ example_app_review_secret_key }}"
```

Each file is rendered as:

```dotenv
SECRET_KEY=replace-me
```

## Extra Worker Mounts

The worker container runs `docker compose`, so it must be able to access every host path referenced by the application Compose templates. Add those paths with `webhooker_worker_extra_mounts`.

Example:

```yaml
webhooker_worker_extra_mounts:
  - /opt/example-app/deploy/webhooker:/opt/example-app/deploy/webhooker:ro
  - /etc/example-app:/etc/example-app:ro
  - /srv/webhooker:/srv/webhooker
```

The role always adds these mounts by default for the worker:

- `/var/run/docker.sock:/var/run/docker.sock`
- `<webhooker_config_dir>:<webhooker_config_dir>:ro`
- `<webhooker_state_dir>:<webhooker_state_dir>`
- `<webhooker_wake_dir>:<webhooker_wake_dir>`

## Idempotency

- Directory, template, and copy tasks only change when content or metadata changes.
- The role always runs `docker compose up -d --remove-orphans`, which is safe on repeated runs.
- The role marks the Docker Compose command tasks as unchanged to keep repeat runs predictable while still ensuring the stack is reconciled.

## Generic Example

Example files also live under [examples/generic](/Users/daniel/Git/Github.com/Malaber/webhooker/ansible_collections/malaber/webhooker/examples/generic).

Playbook:

```yaml
---
- name: Deploy webhooker
  hosts: webhooker_hosts
  become: true
  roles:
    - role: malaber.webhooker.webhooker
```

Non-secret vars:

```yaml
---
webhooker_image: ghcr.io/malaber/webhooker/webhooker:main

webhooker_env:
  GITHUB_TOKEN: "{{ webhooker_github_token }}"
  GITHUB_WEBHOOK_SECRET: "{{ webhooker_github_webhook_secret }}"

webhooker_worker_extra_mounts:
  - /opt/example-app/deploy/webhooker:/opt/example-app/deploy/webhooker:ro
  - /etc/example-app:/etc/example-app:ro
  - /srv/webhooker:/srv/webhooker

webhooker_managed_files:
  - src: files/example-app/deploy/webhooker/compose.review.yml
    dest: /opt/example-app/deploy/webhooker/compose.review.yml
    mode: "0644"
  - src: files/example-app/deploy/webhooker/compose.production.yml
    dest: /opt/example-app/deploy/webhooker/compose.production.yml
    mode: "0644"
  - src: files/example-app/deploy/webhooker/env/review.common.env
    dest: /opt/example-app/deploy/webhooker/env/review.common.env
    mode: "0644"
  - src: files/example-app/deploy/webhooker/env/production.common.env
    dest: /opt/example-app/deploy/webhooker/env/production.common.env
    mode: "0644"

webhooker_secret_env_files:
  - path: /etc/example-app/review.secrets.env
    mode: "0600"
    content:
      SECRET_KEY: "{{ example_app_review_secret_key }}"
  - path: /etc/example-app/production.secrets.env
    mode: "0600"
    content:
      SECRET_KEY: "{{ example_app_production_secret_key }}"

webhooker_projects:
  - filename: example-app-review.yaml
    content:
      project_id: example-app-review
      github:
        owner: your-github-user-or-org
        repo: example-app
        token_env: GITHUB_TOKEN
        webhook_secret_env: GITHUB_WEBHOOK_SECRET
        required_event_types:
          - pull_request
          - ping
      deployment:
        mode: review
        compose_file: /opt/example-app/deploy/webhooker/compose.review.yml
        compose_bin: docker
        working_directory: /opt/example-app/deploy/webhooker
        project_name_prefix: example-app-pr-
        preview_base_domain: review.example.com
        hostname_template: pr-{pr}.review.example.com
      image:
        registry: ghcr.io
        repository: your-github-user-or-org/example-app
        tag_template: pr-{pr}-{sha7}
      preview:
        base_dir: /srv/webhooker/reviews/example-app
        data_dir_template: /srv/webhooker/reviews/example-app/pr-{pr}/data
        sqlite_path_template: /srv/webhooker/reviews/example-app/pr-{pr}/data/app.db
      reconcile:
        poll_interval_seconds: 60
        cleanup_closed_prs: true
        redeploy_on_sha_change: true
      traefik:
        enable_labels: true
        certresolver: letsencrypt
      state:
        state_file: /var/lib/webhooker/state/example-app-review.json
      wake:
        wake_file: /var/lib/webhooker/wake/example-app-review.wake

  - filename: example-app-production.yaml
    content:
      project_id: example-app-production
      github:
        owner: your-github-user-or-org
        repo: example-app
        token_env: GITHUB_TOKEN
        webhook_secret_env: GITHUB_WEBHOOK_SECRET
        required_event_types:
          - push
          - ping
      deployment:
        mode: production
        compose_file: /opt/example-app/deploy/webhooker/compose.production.yml
        compose_bin: docker
        working_directory: /opt/example-app/deploy/webhooker
        project_name_prefix: example-app-
        production_project_name: example-app
        production_hostname: app.example.com
      image:
        registry: ghcr.io
        repository: your-github-user-or-org/example-app
        tag_template: unused
        production_tag_template: sha-{sha7}
      production:
        branch: main
        data_dir: /srv/webhooker/production/example-app/data
        sqlite_path: /srv/webhooker/production/example-app/data/app.db
        backup_dir: /srv/webhooker/production/example-app/backups
        backup_keep: 3
      reconcile:
        poll_interval_seconds: 60
        cleanup_closed_prs: false
        redeploy_on_sha_change: true
      traefik:
        enable_labels: true
        certresolver: letsencrypt
      state:
        state_file: /var/lib/webhooker/state/example-app-production.json
      wake:
        wake_file: /var/lib/webhooker/wake/example-app-production.wake
```

Secret vars:

```yaml
---
webhooker_github_token: replace-me
webhooker_github_webhook_secret: replace-me
example_app_review_secret_key: replace-me
example_app_production_secret_key: replace-me
```

Example command:

```bash
ansible-playbook -i inventory/hosts.ini playbooks/deploy-webhooker.yml -l webhooker_hosts
```
