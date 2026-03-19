from __future__ import annotations

import logging
from collections.abc import Callable

from webhooker.deployer import Deployer
from webhooker.github_client import GitHubClient
from webhooker.models import ProjectConfig, ProjectState
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
    state: ProjectState = load_state(config.state.state_file, config.project_id)
    github_client = github_client_factory(config)
    deployer = deployer_factory(config)

    open_prs = github_client.list_open_pull_requests()
    open_by_number = {pr.number: pr for pr in open_prs}

    desired_numbers = set(open_by_number)
    deployed_numbers = set(state.deployed)

    if config.reconcile.cleanup_closed_prs:
        stale_numbers = deployed_numbers - desired_numbers
        for pr_number in sorted(stale_numbers):
            deployed = state.deployed[pr_number]
            logger.info("Cleaning stale preview project_id=%s pr=%s", config.project_id, pr_number)
            deployer.remove_preview(deployed)
            del state.deployed[pr_number]

    for pr_number in sorted(desired_numbers):
        pr = open_by_number[pr_number]
        current = state.deployed.get(pr_number)

        if current is None:
            logger.info("Deploying new preview project_id=%s pr=%s", config.project_id, pr_number)
            state.deployed[pr_number] = deployer.deploy_preview(pr)
            continue

        if config.reconcile.redeploy_on_sha_change and current.sha != pr.head_sha:
            logger.info(
                "Redeploying preview for SHA change project_id=%s pr=%s",
                config.project_id,
                pr_number,
            )
            deployer.remove_preview(current)
            state.deployed[pr_number] = deployer.deploy_preview(pr)

    save_state(config.state.state_file, state)
    clear_wake_file(config.wake.wake_file)
