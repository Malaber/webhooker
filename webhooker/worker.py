from __future__ import annotations

import logging
import os
from collections.abc import Callable

from webhooker.deployer import Deployer
from webhooker.desired import DesiredDeployments, project_selection
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
    desired_deployments: DesiredDeployments | None = None,
) -> None:
    state = load_state(config.state.state_file, config.project_id)
    github_client = github_client_factory(config)
    deployer = deployer_factory(config)

    try:
        if config.deployment.mode == "review":
            _reconcile_review_project(config, state, github_client, deployer, desired_deployments)
        else:
            _reconcile_production_project(
                config, state, github_client, deployer, desired_deployments
            )
    finally:
        save_state(config.state.state_file, state)
        clear_wake_file(config.wake.wake_file)


def _reconcile_review_project(
    config: ProjectConfig,
    state: ProjectState,
    github_client: GitHubClient,
    deployer: Deployer,
    desired_deployments: DesiredDeployments | None = None,
) -> None:
    desired_fingerprint = deployer.deployment_fingerprint()
    open_prs = github_client.list_open_pull_requests()
    open_by_number = {pr.number: pr for pr in open_prs}
    selection = project_selection(desired_deployments or DesiredDeployments(), config.project_id)

    desired_numbers = set(open_by_number) if selection.enabled else set()
    if selection.review_prs is not None:
        desired_numbers &= set(selection.review_prs)
    deployed_numbers = set(state.reviews)

    if config.reconcile.cleanup_closed_prs:
        stale_numbers = deployed_numbers - desired_numbers
        for pr_number in sorted(stale_numbers):
            deployed = state.reviews[pr_number]
            logger.info("Cleaning stale review project_id=%s pr=%s", config.project_id, pr_number)
            deployer.remove_review(deployed)
            del state.reviews[pr_number]

    startable_numbers = _startable_numbers(
        config, len(deployed_numbers), desired_numbers - deployed_numbers
    )

    for pr_number in sorted(desired_numbers):
        pr = open_by_number[pr_number]
        current = state.reviews.get(pr_number)

        if current is None:
            if pr_number not in startable_numbers:
                logger.warning(
                    "Skipping review deployment because RAM budget is exhausted project_id=%s pr=%s",
                    config.project_id,
                    pr_number,
                )
                continue
            logger.info(
                "Creating review deployment project_id=%s pr=%s", config.project_id, pr_number
            )
            state.reviews[pr_number] = _review_with_fingerprint(
                deployer.deploy_review(pr, previous=None), desired_fingerprint
            )
            continue

        if (
            (config.reconcile.redeploy_on_sha_change and current.sha != pr.head_sha)
            or current.config_fingerprint != desired_fingerprint
            or current.placeholder_active
            or not deployer.review_runtime_exists(current)
        ):
            logger.info(
                "Updating review deployment project_id=%s pr=%s",
                config.project_id,
                pr_number,
            )
            state.reviews[pr_number] = _review_with_fingerprint(
                deployer.deploy_review(pr, previous=current), desired_fingerprint
            )


def _reconcile_production_project(
    config: ProjectConfig,
    state: ProjectState,
    github_client: GitHubClient,
    deployer: Deployer,
    desired_deployments: DesiredDeployments | None = None,
) -> None:
    desired_fingerprint = deployer.deployment_fingerprint()
    selection = project_selection(desired_deployments or DesiredDeployments(), config.project_id)
    if not selection.enabled:
        if state.production is not None:
            logger.info(
                "Production disabled by desired deployment file project_id=%s", config.project_id
            )
            deployer.remove_production(state.production)
            state.production = None
        return

    production_config = config.production
    if production_config is None:
        raise RuntimeError("production configuration is required for production deployments")

    desired_sha = github_client.get_branch_head_sha(production_config.branch)
    current = state.production

    if current is None:
        if not _has_ram_capacity(config, existing_apps=0, new_apps=1):
            logger.warning(
                "Skipping production deployment because RAM budget is exhausted project_id=%s",
                config.project_id,
            )
            return
        logger.info("Creating production deployment project_id=%s", config.project_id)
        state.production = _production_with_fingerprint(
            deployer.deploy_production(desired_sha, previous=None), desired_fingerprint
        )
        return

    if (
        (config.reconcile.redeploy_on_sha_change and current.sha != desired_sha)
        or current.config_fingerprint != desired_fingerprint
        or not deployer.production_runtime_exists(current)
    ):
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


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return int(raw.strip())


def _has_ram_capacity(config: ProjectConfig, *, existing_apps: int, new_apps: int) -> bool:
    budget = _env_int(config.resources.ram_budget_env)
    per_app = _env_int(config.resources.ram_per_application_env)
    if budget is None or per_app is None:
        return True
    if per_app <= 0:
        raise RuntimeError("RAM per application must be greater than zero")
    return (existing_apps + new_apps) * per_app <= budget


def _startable_numbers(
    config: ProjectConfig, existing_count: int, candidate_numbers: set[int]
) -> set[int]:
    budget = _env_int(config.resources.ram_budget_env)
    per_app = _env_int(config.resources.ram_per_application_env)
    if budget is None or per_app is None:
        return candidate_numbers
    if per_app <= 0:
        raise RuntimeError("RAM per application must be greater than zero")
    slots = max((budget // per_app) - existing_count, 0)
    return set(sorted(candidate_numbers)[:slots])
