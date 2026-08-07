"""Regression checks for files that could accidentally expose local secrets."""

import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        ".env.production",
        "secrets/database-password.txt",
        "gcp-service-account.json",
        "private.key",
    ],
)
def test_sensitive_local_paths_are_ignored_by_git(path: str) -> None:
    """Common secret-bearing files should be blocked from ordinary Git staging."""
    if GIT is None:
        pytest.skip("Git is not installed")

    result = subprocess.run(
        [GIT, "check-ignore", "--no-index", "--quiet", path],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 0, f"{path} is not protected by .gitignore"


def test_environment_example_remains_shareable() -> None:
    """The template must stay committed because it documents required names."""
    if GIT is None:
        pytest.skip("Git is not installed")

    result = subprocess.run(
        [GIT, "check-ignore", "--no-index", "--quiet", ".env.example"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    assert result.returncode == 1


def test_docker_build_context_excludes_secret_files() -> None:
    """Docker images should not receive local credentials in their build context."""
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert ".env" in ignored
    assert "secrets" in ignored
    assert "*credentials*.json" in ignored
