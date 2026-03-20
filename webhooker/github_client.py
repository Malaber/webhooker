from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from webhooker.config import env_required
from webhooker.models import ProjectConfig, PullRequestInfo


class GitHubClient:
    def __init__(
        self,
        config: ProjectConfig,
        client: httpx.Client | None = None,
    ) -> None:
        self.config = config
        self._client = client
        token = env_required(config.github.token_env)
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def list_open_pull_requests(self) -> list[PullRequestInfo]:
        owner = self.config.github.owner
        repo = self.config.github.repo
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        params = {"state": "open", "per_page": 100}
        response = self._get(url, params=params)
        return self._parse_pull_requests(response.json())

    def get_branch_head_sha(self, branch: str) -> str:
        owner = self.config.github.owner
        repo = self.config.github.repo
        url = f"{self.base_url}/repos/{owner}/{repo}/branches/{branch}"
        response = self._get(url)
        payload: dict[str, Any] = response.json()
        return str(payload["commit"]["sha"])

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        request_kwargs = {
            "params": params,
            "headers": self.headers,
            "timeout": 30.0,
        }
        if self._client is not None:
            response = self._client.get(url, **request_kwargs)
            response.raise_for_status()
            return response

        with httpx.Client() as client:
            response = client.get(url, **request_kwargs)
            response.raise_for_status()
            return response

    @staticmethod
    def _parse_pull_requests(data: Iterable[dict[str, Any]]) -> list[PullRequestInfo]:
        return [
            PullRequestInfo(
                number=item["number"],
                head_sha=item["head"]["sha"],
                state=item["state"],
                merged=False,
            )
            for item in data
        ]
