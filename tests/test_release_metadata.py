from pathlib import Path
import re


def test_role_default_image_uses_installed_collection_version() -> None:
    defaults = Path("roles/webhooker/defaults/main.yml").read_text(encoding="utf-8")

    assert "webhooker_collection_version" in defaults
    assert "ghcr.io/malaber/webhooker/webhooker:{{ webhooker_collection_version }}" in defaults
    assert ":main" not in defaults


def test_examples_and_docs_do_not_recommend_main_image_tag() -> None:
    example_vars = Path("examples/generic/vars/webhooker.yml").read_text(encoding="utf-8")
    role_readme = Path("roles/webhooker/README.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert ":main" not in example_vars
    assert ":main" not in role_readme
    assert ":main" not in readme
    assert "Stable releases publish both `<version>` and `latest`" in readme


def test_project_and_collection_versions_match() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    galaxy = Path("galaxy.yml").read_text(encoding="utf-8")

    pyproject_match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    galaxy_match = re.search(r"^version:\s*([^\n]+)$", galaxy, re.MULTILINE)

    assert pyproject_match is not None
    assert galaxy_match is not None
    assert pyproject_match.group(1) == galaxy_match.group(1).strip()
