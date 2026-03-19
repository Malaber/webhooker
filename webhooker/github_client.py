from __future__ import annotations

from typing import Any

from webhooker.config import env_required
from webhooker.models import ProjectConfig, PullRequestInfo


class GitHubClient:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        token = env_required(config.github.token_env)
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def list_open_pull_requests(self) -> list[PullRequestInfo]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("httpx is required to query GitHub") from exc

        owner = self.config.github.owner
        repo = self.config.github.repo
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        params = {"state": "open", "per_page": 100}

        with httpx.Client(timeout=30.0, headers=self.headers) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data: list[dict[str, Any]] = response.json()

        return [
            PullRequestInfo(
                number=item["number"],
                head_sha=item["head"]["sha"],
                state=item["state"],
                merged=False,
            )
            for item in data
        ]
