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
- rendering app secret env files such as `/etc/listerine/review.secrets.env`
- adding extra worker bind mounts for every host path the worker must read or write

The role is intentionally generic. It does not hardcode Listerine or any other app.

## Prerequisites

- Docker and the Docker Compose plugin must already be installed on the target host.
- The target host user running the role must be able to create files under the configured deploy, config, env, state, and wake directories.
- The worker's extra mounts must cover every host path referenced by the app Compose templates that `webhooker` will execute.

## Install From GitHub Releases

Tagged releases publish a versioned Galaxy collection tarball as a GitHub Release asset.

Direct install example:

```bash
ansible-galaxy collection install \
  https://github.com/Malaber/webhooker/releases/download/v0.3.0/malaber-webhooker-0.3.0.tar.gz
```

`requirements.yml` example:

```yaml
---
collections:
  - name: https://github.com/Malaber/webhooker/releases/download/v0.3.0/malaber-webhooker-0.3.0.tar.gz
    type: url
```

The collection version tracks the GitHub release tag. For example, tag `v0.3.0` publishes `malaber-webhooker-0.3.0.tar.gz`.

## Listerine Example

A complete example consumer layout lives under [examples/listerine](/Users/daniel/Git/Github.com/Malaber/webhooker/ansible_collections/malaber/webhooker/examples/listerine).

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
ansible-playbook -i inventory/hosts.ini playbooks/deploy-webhooker.yml -l minidoener
```

## Role Documentation

See [roles/webhooker/README.md](/Users/daniel/Git/Github.com/Malaber/webhooker/ansible_collections/malaber/webhooker/roles/webhooker/README.md) for variables, role behavior, and the full Listerine review + production example.
