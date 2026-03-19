from __future__ import annotations

import json
import os

from webhooker.config import load_project_configs
from webhooker.security import verify_github_signature
from webhooker.wake import touch_wake_file



def create_app(config_dir: str):
    try:
        from fastapi import FastAPI, HTTPException, Request, status
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fastapi is required to run webhooker-api") from exc

    app = FastAPI(title="webhooker", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/github/{project_id}/wake")
    async def github_wake(project_id: str, request: Request) -> JSONResponse:
        configs = {config.project_id: config for config in load_project_configs(config_dir)}
        config = configs.get(project_id)
        if not config:
            raise HTTPException(status_code=404, detail="Unknown project")

        raw_body = await request.body()
        secret = os.getenv(config.github.webhook_secret_env)
        if not secret:
            raise HTTPException(status_code=500, detail="Webhook secret missing on server")

        signature = request.headers.get("X-Hub-Signature-256")
        if not verify_github_signature(secret, raw_body, signature):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad signature")

        event_type = request.headers.get("X-GitHub-Event")
        if event_type not in config.github.required_event_types:
            return JSONResponse(status_code=202, content={"status": "ignored", "reason": "event type"})

        payload = json.loads(raw_body.decode("utf-8") or "{}")
        repo_info = payload.get("repository", {})
        full_name = repo_info.get("full_name")
        expected_full_name = f"{config.github.owner}/{config.github.repo}"
        if full_name and full_name != expected_full_name:
            raise HTTPException(status_code=403, detail="Repository mismatch")

        touch_wake_file(config.wake.wake_file)
        return JSONResponse(status_code=202, content={"status": "accepted"})

    return app
