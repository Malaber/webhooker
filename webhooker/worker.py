from __future__ import annotations

import logging
from collections.abc import Callable

from webhooker.deployer import Deployer
from webhooker.github_client import GitHubClient
from webhooker.models import DeployedProduction, DeployedReview, ProjectConfig, ProjectState
from webhooker.state import load_state, save_state
from webhooker.wake import clear_wake_file

logger = logging.getLogger(__name__)

GitHubClientFactory = Callable[[ProjectConfig], GitHubClient]
DeployerFactory = Callable[[ProjectConfig], Deployer]


def reconcile_project(
    config: ProjectConfig,
    github_client_factory: GitHubClientFactory = GitHubClient,
    deployer_factory: DeployerFactory = Deployer,
) -> None:
    state = load_state(config.state.state_file, config.project_id)
    github_client = github_client_factory(config)
    deployer = deployer_factory(config)

    try:
        if config.deployment.mode == "review":
            _reconcile_review_project(config, state, github_client, deployer)
        else:
            _reconcile_production_project(config, state, github_client, deployer)
    finally:
        save_state(config.state.state_file, state)
        clear_wake_file(config.wake.wake_file)


def _reconcile_review_project(
    config: ProjectConfig,
    state: ProjectState,
    github_client: GitHubClient,
    deployer: Deployer,
) -> None:
    desired_fingerprint = deployer.deployment_fingerprint()
    open_prs = github_client.list_open_pull_requests()
    open_by_number = {pr.number: pr for pr in open_prs}

    desired_numbers = set(open_by_number)
    deployed_numbers = set(state.reviews)

    if config.reconcile.cleanup_closed_prs:
        stale_numbers = deployed_numbers - desired_numbers
        for pr_number in sorted(stale_numbers):
            deployed = state.reviews[pr_number]
            logger.info("Cleaning stale review project_id=%s pr=%s", config.project_id, pr_number)
            deployer.remove_review(deployed)
            del state.reviews[pr_number]

    for pr_number in sorted(desired_numbers):
        pr = open_by_number[pr_number]
        current = state.reviews.get(pr_number)

        if current is None:
            logger.info(
                "Creating review deployment project_id=%s pr=%s", config.project_id, pr_number
            )
            state.reviews[pr_number] = _review_with_fingerprint(
                deployer.deploy_review(pr), desired_fingerprint
            )
            continue

        if (
            config.reconcile.redeploy_on_sha_change and current.sha != pr.head_sha
        ) or current.config_fingerprint != desired_fingerprint:
            logger.info(
                "Updating review deployment project_id=%s pr=%s",
                config.project_id,
                pr_number,
            )
            state.reviews[pr_number] = _review_with_fingerprint(
                deployer.deploy_review(pr), desired_fingerprint
            )


def _reconcile_production_project(
    config: ProjectConfig,
    state: ProjectState,
    github_client: GitHubClient,
    deployer: Deployer,
) -> None:
    desired_fingerprint = deployer.deployment_fingerprint()
    production_config = config.production
    if production_config is None:
        raise RuntimeError("production configuration is required for production deployments")

    desired_sha = github_client.get_branch_head_sha(production_config.branch)
    current = state.production

    if current is None:
        logger.info("Creating production deployment project_id=%s", config.project_id)
        state.production = _production_with_fingerprint(
            deployer.deploy_production(desired_sha, previous=None), desired_fingerprint
        )
        return

    if (
        config.reconcile.redeploy_on_sha_change and current.sha != desired_sha
    ) or current.config_fingerprint != desired_fingerprint:
        logger.info("Updating production deployment project_id=%s", config.project_id)
        state.production = _production_with_fingerprint(
            deployer.deploy_production(desired_sha, previous=current), desired_fingerprint
        )


def _review_with_fingerprint(review: DeployedReview, fingerprint: str) -> DeployedReview:
    return review.model_copy(update={"config_fingerprint": fingerprint})


def _production_with_fingerprint(
    production: DeployedProduction, fingerprint: str
) -> DeployedProduction:
    return production.model_copy(update={"config_fingerprint": fingerprint})
