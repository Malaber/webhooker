from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from webhooker.github_client import GitHubClient



def test_list_open_pull_requests(project_config, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.params["state"] == "open"
        return httpx.Response(
            200,
            json=[
                {"number": 7, "state": "open", "head": {"sha": "abcdef123456"}},
            ],
        )

    monkeypatch.setenv(project_config.github.token_env, "test-token")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    github = GitHubClient(project_config, client=client)

    pull_requests = github.list_open_pull_requests()

    assert pull_requests[0].number == 7
    assert pull_requests[0].head_sha == "abcdef123456"
