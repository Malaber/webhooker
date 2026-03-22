# malaber.webhooker

`malaber.webhooker` is an Ansible Galaxy collection for deploying `webhooker` as a Docker Compose stack and publishing the app bundle files that `webhooker` needs on the target host.

The collection currently exposes one role:

- `malaber.webhooker.webhooker`

## What The Role Manages

The role is responsible for:

- deploying `webhooker-api` and `webhooker-worker` with Docker Compose
- rendering `/etc/webhooker/env/webhooker.env`
- rendering one or more `webhooker` project YAML files under `/etc/webhooker/projects/`
- copying app deployment bundle files such as Compose templates and non-secret env files onto the host
- rendering app secret env files such as `/etc/example-app/review.secrets.env`
- adding extra worker bind mounts for every host path the worker must read or write

The role is intentionally generic. App-specific deployment details belong in the consuming infra repo.

## Prerequisites

- Docker and the Docker Compose plugin must already be installed on the target host.
- The target host user running the role must be able to create files under the configured deploy, config, env, state, and wake directories.
- The worker's extra mounts must cover every host path referenced by the app Compose templates that `webhooker` will execute.

## Install From GitHub Releases

Tagged releases publish a versioned Galaxy collection tarball as a GitHub Release asset.

Direct install example:

```bash
ansible-galaxy collection install \
  https://github.com/Malaber/webhooker/releases/download/vX.Y.Z/malaber-webhooker-X.Y.Z.tar.gz
```

`requirements.yml` example:

```yaml
---
collections:
  - name: https://github.com/Malaber/webhooker/releases/download/vX.Y.Z/malaber-webhooker-X.Y.Z.tar.gz
    type: url
```

The collection version tracks the GitHub release tag. For example, tag `vX.Y.Z` publishes `malaber-webhooker-X.Y.Z.tar.gz`.

## Using In Another Repo

The normal consumption pattern is:

1. Add the collection tarball URL to your infra repo's `requirements.yml`.
2. Put your app deployment bundle files in that infra repo under `files/`.
3. Add a playbook that includes `malaber.webhooker.webhooker`.
4. Add one non-secret vars file that defines `webhooker_env`, `webhooker_projects`, `webhooker_managed_files`, and `webhooker_worker_extra_mounts`.
5. Add one secret vars file, usually encrypted with Ansible Vault, for `webhooker_secret_env_files` values.
6. Run the playbook against the host group that should run `webhooker`.

Suggested consuming repo layout:

```text
infra-repo/
├── requirements.yml
├── inventory/
│   └── hosts.ini
├── playbooks/
│   └── deploy-webhooker.yml
├── vars/
│   ├── webhooker.yml
│   └── webhooker.secrets.yml
└── files/
    └── example-app/
        └── deploy/
            └── webhooker/
                ├── compose.review.yml
                ├── compose.production.yml
                └── env/
                    ├── review.common.env
                    └── production.common.env
```

Install the collection:

```bash
ansible-galaxy collection install -r requirements.yml
```

Create a playbook:

```yaml
---
- name: Deploy webhooker
  hosts: webhooker_hosts
  become: true
  roles:
    - role: malaber.webhooker.webhooker
```

Run it:

```bash
ansible-playbook -i inventory/hosts.ini playbooks/deploy-webhooker.yml \
  -e @vars/webhooker.yml \
  -e @vars/webhooker.secrets.yml \
  -l webhooker_hosts
```

## Generic Example

A generic consumer layout lives under [examples/generic](/Users/daniel/Git/Github.com/Malaber/webhooker/ansible_collections/malaber/webhooker/examples/generic).

Typical consumption flow in another infra repo:

1. Install the collection from a GitHub Release tarball.
2. Add a playbook that includes `malaber.webhooker.webhooker`.
3. Add one non-secret vars file and one secret vars file.
4. Commit the app bundle files to that repo.
5. Set `webhooker_managed_files` to publish those files to the target host.
6. Define `webhooker_projects` using the schema `webhooker` validates today.
7. Run the playbook against the chosen host group.

Example command:

```bash
ansible-playbook -i inventory/hosts.ini playbooks/deploy-webhooker.yml -l webhooker_hosts
```

## Role Documentation

See [roles/webhooker/README.md](/Users/daniel/Git/Github.com/Malaber/webhooker/ansible_collections/malaber/webhooker/roles/webhooker/README.md) for variables, role behavior, and a generic review + production example.
