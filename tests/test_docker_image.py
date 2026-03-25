from pathlib import Path


def test_dockerfile_includes_docker_cli_and_compose_plugin() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM docker:28-cli AS docker-cli" in dockerfile
    assert "COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker" in dockerfile
    assert (
        "COPY --from=docker-cli /usr/local/libexec/docker /usr/local/libexec/docker" in dockerfile
    )
