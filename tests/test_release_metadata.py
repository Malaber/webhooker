from pathlib import Path


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
