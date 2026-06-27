from __future__ import annotations

import json
import os
from json import JSONDecodeError

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from webhooker import __version__
from webhooker.config import load_project_configs
from webhooker.desired import (
    DesiredDeployments,
    DesiredProjectSelection,
    desired_deployments_path,
    load_desired_deployments,
    save_desired_deployments,
)
from webhooker.models import ProjectConfig
from webhooker.security import verify_github_signature
from webhooker.wake import touch_wake_file


def create_app(config_dir: str) -> FastAPI:
    app = FastAPI(title="webhooker", version=__version__)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/ui")

    @app.get("/ui", response_class=HTMLResponse)
    async def deployment_ui() -> str:
        configs = load_project_configs(config_dir)
        desired = load_desired_deployments(desired_deployments_path(config_dir))
        return _deployment_ui_html(configs, desired)

    @app.get("/ui/deployments")
    async def deployment_config() -> dict[str, object]:
        configs = load_project_configs(config_dir)
        desired = load_desired_deployments(desired_deployments_path(config_dir))
        return {
            "resources": _resource_summary(configs),
            "desired": desired.model_dump(mode="json"),
            "projects": [_project_summary(config) for config in configs],
        }

    @app.post("/ui/deployments")
    async def update_deployment_config(request: Request) -> dict[str, object]:
        payload = await request.json()
        desired = DesiredDeployments.model_validate(payload)
        save_desired_deployments(desired_deployments_path(config_dir), desired)
        return {"status": "saved", "desired": desired.model_dump(mode="json")}

    @app.post("/github/{project_id}/wake")
    async def github_wake(project_id: str, request: Request) -> JSONResponse:
        configs = {config.project_id: config for config in load_project_configs(config_dir)}
        config = configs.get(project_id)
        if config is None:
            raise HTTPException(status_code=404, detail="Unknown project")

        raw_body = await request.body()
        secret = os.getenv(config.github.webhook_secret_env)
        if not secret:
            raise HTTPException(status_code=500, detail="Webhook secret missing on server")

        signature = request.headers.get("X-Hub-Signature-256")
        if not verify_github_signature(secret, raw_body, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bad signature",
            )

        event_type = request.headers.get("X-GitHub-Event")
        if event_type not in config.github.required_event_types:
            return JSONResponse(
                status_code=202,
                content={"status": "ignored", "reason": "event type"},
            )

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
        repo_info = payload.get("repository", {})
        full_name = repo_info.get("full_name")
        expected_full_name = f"{config.github.owner}/{config.github.repo}"
        if full_name and full_name != expected_full_name:
            raise HTTPException(status_code=403, detail="Repository mismatch")

        touch_wake_file(config.wake.wake_file)
        return JSONResponse(status_code=202, content={"status": "accepted"})

    return app


def _project_summary(config: ProjectConfig) -> dict[str, object]:
    deployment = config.deployment
    return {
        "project_id": config.project_id,
        "mode": deployment.mode,
        "hostname": (
            deployment.production_hostname
            if deployment.mode == "production"
            else deployment.hostname_template
        ),
        "ram_budget_env": config.resources.ram_budget_env,
        "ram_per_application_env": config.resources.ram_per_application_env,
    }


def _resource_summary(configs: list[ProjectConfig]) -> dict[str, object]:
    if not configs:
        return {"ram_budget": None, "ram_per_application": None, "capacity": None}
    resources = configs[0].resources
    budget = os.getenv(resources.ram_budget_env)
    per_app = os.getenv(resources.ram_per_application_env)
    capacity = None
    if budget and per_app and int(per_app) > 0:
        capacity = int(budget) // int(per_app)
    return {
        "ram_budget": int(budget) if budget else None,
        "ram_per_application": int(per_app) if per_app else None,
        "capacity": capacity,
    }


def _deployment_ui_html(configs: list[ProjectConfig], desired: DesiredDeployments) -> str:
    rows = []
    for config in configs:
        selection = desired.projects.get(config.project_id, DesiredProjectSelection())
        review_prs = (
            "" if selection.review_prs is None else ",".join(str(pr) for pr in selection.review_prs)
        )
        checked = "checked" if selection.enabled else ""
        rows.append(f"""
            <tr>
              <td>{config.project_id}</td>
              <td>{config.deployment.mode}</td>
              <td><input type='checkbox' data-project='{config.project_id}' data-field='enabled' {checked}></td>
              <td><input type='text' data-project='{config.project_id}' data-field='review_prs' value='{review_prs}' placeholder='all open PRs'></td>
            </tr>
            """)
    return f"""
    <!doctype html>
    <html lang='en'>
      <head>
        <meta charset='utf-8'>
        <title>webhooker deployments</title>
        <style>
          body {{ font-family: system-ui, sans-serif; margin: 2rem; max-width: 960px; }}
          table {{ border-collapse: collapse; width: 100%; }}
          th, td {{ border-bottom: 1px solid #ddd; padding: .75rem; text-align: left; }}
          input[type=text] {{ width: 100%; }}
        </style>
      </head>
      <body>
        <h1>webhooker deployments</h1>
        <p>Changes are saved to the desired deployment config file. The worker reads that file during reconciliation.</p>
        <p>RAM budget: {os.getenv('WEBHOOKER_RAM_BUDGET', 'unlimited')} / per app: {os.getenv('WEBHOOKER_RAM_PER_APPLICATION', 'unset')}</p>
        <table>
          <thead><tr><th>Project</th><th>Mode</th><th>Present</th><th>Review PR allowlist</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        <button id='save'>Save desired deployments</button>
        <pre id='status'></pre>
        <script>
          document.getElementById('save').addEventListener('click', async () => {{
            const projects = {{}};
            document.querySelectorAll('[data-project]').forEach((input) => {{
              const project = input.dataset.project;
              projects[project] ||= {{ enabled: true }};
              if (input.dataset.field === 'enabled') projects[project].enabled = input.checked;
              if (input.dataset.field === 'review_prs') {{
                const value = input.value.trim();
                projects[project].review_prs = value ? value.split(',').map((part) => parseInt(part.trim(), 10)) : null;
              }}
            }});
            const response = await fetch('/ui/deployments', {{
              method: 'POST',
              headers: {{ 'content-type': 'application/json' }},
              body: JSON.stringify({{ projects }}),
            }});
            document.getElementById('status').textContent = JSON.stringify(await response.json(), null, 2);
          }});
        </script>
      </body>
    </html>
    """
