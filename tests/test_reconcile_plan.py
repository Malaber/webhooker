from __future__ import annotations

from pathlib import Path

import pytest

from webhooker.models import (
    DeployedProduction,
    DeployedReview,
    ProjectConfig,
    ProjectState,
    PullRequestInfo,
)
from webhooker.state import save_state
from webhooker.worker import reconcile_project


class FakeReviewGitHubClient:
    def __init__(self, config: ProjectConfig, prs: list[PullRequestInfo]) -> None:
        self.config = config
        self._prs = prs

    def list_open_pull_requests(self) -> list[PullRequestInfo]:
        return self._prs


class FakeProductionGitHubClient:
    def __init__(self, config: ProjectConfig, sha: str) -> None:
        self.config = config
        self.sha = sha

    def get_branch_head_sha(self, branch: str) -> str:
        assert branch == "main"
        return self.sha


class FakeDeployer:
    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.config_fingerprint = "fingerprint-v1"
        self.missing_review_runtime: set[int] = set()
        self.missing_production_runtime = False
        self.review_deployed: list[int] = []
        self.review_removed: list[int] = []
        self.production_deployed: list[str] = []

    def deployment_fingerprint(self) -> str:
        return self.config_fingerprint

    def deploy_review(
        self,
        pr: PullRequestInfo,
        previous: DeployedReview | None = None,
    ) -> DeployedReview:
        del previous
        self.review_deployed.append(pr.number)
        return DeployedReview(
            pr=pr.number,
            sha=pr.head_sha,
            compose_project=f"demo-pr-{pr.number}",
            hostname=f"pr-{pr.number}.review.example.test",
            data_dir=f"/tmp/demo/pr-{pr.number}",
            sqlite_path=f"/tmp/demo/pr-{pr.number}/app.db",
            image=f"ghcr.io/example/repo:pr-{pr.number}-{pr.head_sha[:7]}",
            config_fingerprint=self.deployment_fingerprint(),
        )

    def remove_review(self, deployed: DeployedReview) -> None:
        self.review_removed.append(deployed.pr)

    def review_runtime_exists(self, deployed: DeployedReview) -> bool:
        return deployed.pr not in self.missing_review_runtime

    def deploy_production(
        self,
        sha: str,
        previous: DeployedProduction | None,
    ) -> DeployedProduction:
        self.production_deployed.append(sha)
        return DeployedProduction(
            sha=sha,
            compose_project="demo-production",
            hostname="app.example.test",
            data_dir="/tmp/demo/production",
            sqlite_path="/tmp/demo/production/app.db",
            image=f"ghcr.io/example/repo:sha-{sha[:7]}",
            branch="main",
            config_fingerprint=self.deployment_fingerprint(),
        )

    def production_runtime_exists(self, deployed: DeployedProduction) -> bool:
        return not self.missing_production_runtime


class FailingReviewDeployer(FakeDeployer):
    def __init__(self, config: ProjectConfig, failing_pr: int) -> None:
        super().__init__(config)
        self.failing_pr = failing_pr

    def deploy_review(
        self,
        pr: PullRequestInfo,
        previous: DeployedReview | None = None,
    ) -> DeployedReview:
        del previous
        if pr.number == self.failing_pr:
            raise RuntimeError(f"simulated deploy failure for pr {pr.number}")
        return super().deploy_review(pr)


def test_new_review_pr_causes_deploy(review_project_config) -> None:
    deployer = FakeDeployer(review_project_config)
    prs = [PullRequestInfo(number=5, head_sha="abcdef123456", state="open")]

    reconcile_project(
        review_project_config,
        github_client_factory=lambda _: FakeReviewGitHubClient(review_project_config, prs),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.review_deployed == [5]
    assert deployer.review_removed == []


def test_changed_review_sha_causes_redeploy_without_cleanup(review_project_config) -> None:
    save_state(
        review_project_config.state.state_file,
        ProjectState(
            project_id=review_project_config.project_id,
            reviews={
                5: DeployedReview(
                    pr=5,
                    sha="oldsha1",
                    compose_project="demo-pr-5",
                    hostname="pr-5.review.example.test",
                    data_dir="/tmp/demo/pr-5",
                    sqlite_path="/tmp/demo/pr-5/app.db",
                    image="ghcr.io/example/repo:pr-5-oldsha1",
                )
            },
        ),
    )
    deployer = FakeDeployer(review_project_config)
    prs = [PullRequestInfo(number=5, head_sha="newsha123456", state="open")]

    reconcile_project(
        review_project_config,
        github_client_factory=lambda _: FakeReviewGitHubClient(review_project_config, prs),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.review_removed == []
    assert deployer.review_deployed == [5]


def test_closed_review_pr_causes_cleanup(review_project_config) -> None:
    save_state(
        review_project_config.state.state_file,
        ProjectState(
            project_id=review_project_config.project_id,
            reviews={
                7: DeployedReview(
                    pr=7,
                    sha="abcdef0",
                    compose_project="demo-pr-7",
                    hostname="pr-7.review.example.test",
                    data_dir="/tmp/demo/pr-7",
                    sqlite_path="/tmp/demo/pr-7/app.db",
                    image="ghcr.io/example/repo:pr-7-abcdef0",
                )
            },
        ),
    )
    deployer = FakeDeployer(review_project_config)

    reconcile_project(
        review_project_config,
        github_client_factory=lambda _: FakeReviewGitHubClient(review_project_config, []),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.review_removed == [7]
    assert deployer.review_deployed == []


def test_stale_review_cleanup_is_saved_even_when_later_deploy_fails(review_project_config) -> None:
    save_state(
        review_project_config.state.state_file,
        ProjectState(
            project_id=review_project_config.project_id,
            reviews={
                7: DeployedReview(
                    pr=7,
                    sha="abcdef0",
                    compose_project="demo-pr-7",
                    hostname="pr-7.review.example.test",
                    data_dir="/tmp/demo/pr-7",
                    sqlite_path="/tmp/demo/pr-7/app.db",
                    image="ghcr.io/example/repo:pr-7-abcdef0",
                )
            },
        ),
    )
    deployer = FailingReviewDeployer(review_project_config, failing_pr=8)
    prs = [PullRequestInfo(number=8, head_sha="newsha123456", state="open")]

    with pytest.raises(RuntimeError, match="simulated deploy failure"):
        reconcile_project(
            review_project_config,
            github_client_factory=lambda _: FakeReviewGitHubClient(review_project_config, prs),
            deployer_factory=lambda _: deployer,
        )

    persisted = ProjectState.model_validate_json(
        Path(review_project_config.state.state_file).read_text(encoding="utf-8")
    )

    assert deployer.review_removed == [7]
    assert 7 not in persisted.reviews


def test_review_config_change_causes_redeploy_without_sha_change(review_project_config) -> None:
    save_state(
        review_project_config.state.state_file,
        ProjectState(
            project_id=review_project_config.project_id,
            reviews={
                5: DeployedReview(
                    pr=5,
                    sha="same-sha-123456",
                    compose_project="demo-pr-5",
                    hostname="pr-5.review.example.test",
                    data_dir="/tmp/demo/pr-5",
                    sqlite_path="/tmp/demo/pr-5/app.db",
                    image="ghcr.io/example/repo:pr-5-same-sh",
                    config_fingerprint="old-fingerprint",
                )
            },
        ),
    )
    deployer = FakeDeployer(review_project_config)
    deployer.config_fingerprint = "new-fingerprint"
    prs = [PullRequestInfo(number=5, head_sha="same-sha-123456", state="open")]

    reconcile_project(
        review_project_config,
        github_client_factory=lambda _: FakeReviewGitHubClient(review_project_config, prs),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.review_removed == []
    assert deployer.review_deployed == [5]


def test_placeholder_review_is_retried_without_sha_change(review_project_config) -> None:
    save_state(
        review_project_config.state.state_file,
        ProjectState(
            project_id=review_project_config.project_id,
            reviews={
                5: DeployedReview(
                    pr=5,
                    sha="same-sha-123456",
                    compose_project="demo-pr-5",
                    hostname="pr-5.review.example.test",
                    data_dir="/tmp/demo/pr-5",
                    sqlite_path="/tmp/demo/pr-5/app.db",
                    image="ghcr.io/example/repo:pr-5-same-sh",
                    placeholder_active=True,
                )
            },
        ),
    )
    deployer = FakeDeployer(review_project_config)
    prs = [PullRequestInfo(number=5, head_sha="same-sha-123456", state="open")]

    reconcile_project(
        review_project_config,
        github_client_factory=lambda _: FakeReviewGitHubClient(review_project_config, prs),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.review_removed == []
    assert deployer.review_deployed == [5]


def test_missing_review_runtime_causes_redeploy_without_sha_change(review_project_config) -> None:
    save_state(
        review_project_config.state.state_file,
        ProjectState(
            project_id=review_project_config.project_id,
            reviews={
                5: DeployedReview(
                    pr=5,
                    sha="same-sha-123456",
                    compose_project="demo-pr-5",
                    hostname="pr-5.review.example.test",
                    data_dir="/tmp/demo/pr-5",
                    sqlite_path="/tmp/demo/pr-5/app.db",
                    image="ghcr.io/example/repo:pr-5-same-sh",
                )
            },
        ),
    )
    deployer = FakeDeployer(review_project_config)
    deployer.missing_review_runtime.add(5)
    prs = [PullRequestInfo(number=5, head_sha="same-sha-123456", state="open")]

    reconcile_project(
        review_project_config,
        github_client_factory=lambda _: FakeReviewGitHubClient(review_project_config, prs),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.review_deployed == [5]


def test_production_sha_change_causes_single_redeploy(production_project_config) -> None:
    save_state(
        production_project_config.state.state_file,
        ProjectState(
            project_id=production_project_config.project_id,
            production=DeployedProduction(
                sha="oldsha1",
                compose_project="demo-production",
                hostname="app.example.test",
                data_dir="/tmp/demo/production",
                sqlite_path="/tmp/demo/production/app.db",
                image="ghcr.io/example/repo:sha-oldsha1",
                branch="main",
            ),
        ),
    )
    deployer = FakeDeployer(production_project_config)

    reconcile_project(
        production_project_config,
        github_client_factory=lambda _: FakeProductionGitHubClient(
            production_project_config,
            "newsha123456",
        ),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.production_deployed == ["newsha123456"]


def test_new_production_deploy_is_created(production_project_config) -> None:
    deployer = FakeDeployer(production_project_config)

    reconcile_project(
        production_project_config,
        github_client_factory=lambda _: FakeProductionGitHubClient(
            production_project_config,
            "newsha123456",
        ),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.production_deployed == ["newsha123456"]


def test_production_config_change_causes_redeploy_without_sha_change(
    production_project_config,
) -> None:
    save_state(
        production_project_config.state.state_file,
        ProjectState(
            project_id=production_project_config.project_id,
            production=DeployedProduction(
                sha="same-sha-123456",
                compose_project="demo-production",
                hostname="app.example.test",
                data_dir="/tmp/demo/production",
                sqlite_path="/tmp/demo/production/app.db",
                image="ghcr.io/example/repo:sha-same-sh",
                branch="main",
                config_fingerprint="old-fingerprint",
            ),
        ),
    )
    deployer = FakeDeployer(production_project_config)
    deployer.config_fingerprint = "new-fingerprint"

    reconcile_project(
        production_project_config,
        github_client_factory=lambda _: FakeProductionGitHubClient(
            production_project_config,
            "same-sha-123456",
        ),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.production_deployed == ["same-sha-123456"]


def test_missing_production_runtime_causes_redeploy_without_sha_change(
    production_project_config,
) -> None:
    save_state(
        production_project_config.state.state_file,
        ProjectState(
            project_id=production_project_config.project_id,
            production=DeployedProduction(
                sha="same-sha-123456",
                compose_project="demo-production",
                hostname="app.example.test",
                data_dir="/tmp/demo/production",
                sqlite_path="/tmp/demo/production/app.db",
                image="ghcr.io/example/repo:sha-same-sh",
                branch="main",
            ),
        ),
    )
    deployer = FakeDeployer(production_project_config)
    deployer.missing_production_runtime = True

    reconcile_project(
        production_project_config,
        github_client_factory=lambda _: FakeProductionGitHubClient(
            production_project_config,
            "same-sha-123456",
        ),
        deployer_factory=lambda _: deployer,
    )

    assert deployer.production_deployed == ["same-sha-123456"]


def test_production_without_config_raises(review_project_config) -> None:
    invalid_config = review_project_config.model_copy(
        update={
            "deployment": review_project_config.deployment.model_copy(
                update={"mode": "production"}
            ),
            "preview": None,
        }
    )

    with pytest.raises(RuntimeError):
        reconcile_project(
            invalid_config,
            github_client_factory=lambda _: FakeProductionGitHubClient(
                invalid_config,
                "newsha123456",
            ),
            deployer_factory=lambda _: FakeDeployer(invalid_config),
        )
