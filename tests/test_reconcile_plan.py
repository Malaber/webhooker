from __future__ import annotations

from webhooker.models import DeployedPreview, ProjectConfig, PullRequestInfo, ProjectState
from webhooker.state import save_state
from webhooker.worker import reconcile_project


class FakeGitHubClient:
    def __init__(self, config: ProjectConfig, prs: list[PullRequestInfo]) -> None:
        self.config = config
        self._prs = prs

    def list_open_pull_requests(self) -> list[PullRequestInfo]:
        return self._prs


class FakeDeployer:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.deployed: list[int] = []
        self.removed: list[int] = []

    def deploy_preview(self, pr: PullRequestInfo) -> DeployedPreview:
        self.deployed.append(pr.number)
        return DeployedPreview(
            pr=pr.number,
            sha=pr.head_sha,
            compose_project=f"demo-pr-{pr.number}",
            hostname=f"{pr.number}.pr.example.test",
            data_dir=f"/tmp/demo/pr-{pr.number}",
            image=f"ghcr.io/example/repo:pr-{pr.number}-{pr.head_sha[:7]}",
        )

    def remove_preview(self, deployed: DeployedPreview) -> None:
        self.removed.append(deployed.pr)


def build_config(tmp_path) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "project_id": "demo",
            "github": {
                "owner": "example",
                "repo": "repo",
                "token_env": "GITHUB_TOKEN",
                "webhook_secret_env": "GITHUB_WEBHOOK_SECRET",
            },
            "deployment": {
                "compose_file": "/tmp/compose.yml",
                "working_directory": "/tmp",
                "project_name_prefix": "demo-pr-",
                "preview_base_domain": "pr.example.test",
                "hostname_template": "{pr}.pr.example.test",
            },
            "image": {
                "registry": "ghcr.io",
                "repository": "example/repo",
                "tag_template": "pr-{pr}-{sha7}",
            },
            "preview": {
                "base_dir": "/tmp/previews",
                "data_dir_template": "/tmp/previews/pr-{pr}",
                "sqlite_path_template": "/tmp/previews/pr-{pr}/app.db",
            },
            "reconcile": {
                "poll_interval_seconds": 600,
                "cleanup_closed_prs": True,
                "redeploy_on_sha_change": True,
            },
            "traefik": {"certresolver": "letsencrypt"},
            "state": {"state_file": str(tmp_path / "state.json")},
            "wake": {"wake_file": str(tmp_path / "wake")},
        }
    )


def test_new_pr_causes_deploy(tmp_path) -> None:
    config = build_config(tmp_path)
    deployer = FakeDeployer(config)
    prs = [PullRequestInfo(number=5, head_sha="abcdef123456", state="open")]

    reconcile_project(
        config,
        github_client_factory=lambda _: FakeGitHubClient(config, prs),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.deployed == [5]
    assert deployer.removed == []


def test_changed_sha_causes_redeploy(tmp_path) -> None:
    config = build_config(tmp_path)
    save_state(
        config.state.state_file,
        ProjectState(
            project_id=config.project_id,
            deployed={
                5: DeployedPreview(
                    pr=5,
                    sha="oldsha1",
                    compose_project="demo-pr-5",
                    hostname="5.pr.example.test",
                    data_dir="/tmp/demo/pr-5",
                    image="ghcr.io/example/repo:pr-5-oldsha1",
                )
            },
        ),
    )
    deployer = FakeDeployer(config)
    prs = [PullRequestInfo(number=5, head_sha="newsha123456", state="open")]

    reconcile_project(
        config,
        github_client_factory=lambda _: FakeGitHubClient(config, prs),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.removed == [5]
    assert deployer.deployed == [5]


def test_closed_pr_causes_cleanup(tmp_path) -> None:
    config = build_config(tmp_path)
    save_state(
        config.state.state_file,
        ProjectState(
            project_id=config.project_id,
            deployed={
                7: DeployedPreview(
                    pr=7,
                    sha="abcdef0",
                    compose_project="demo-pr-7",
                    hostname="7.pr.example.test",
                    data_dir="/tmp/demo/pr-7",
                    image="ghcr.io/example/repo:pr-7-abcdef0",
                )
            },
        ),
    )
    deployer = FakeDeployer(config)

    reconcile_project(
        config,
        github_client_factory=lambda _: FakeGitHubClient(config, []),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.removed == [7]
    assert deployer.deployed == []
