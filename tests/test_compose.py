"""Contract checks for local Docker Compose services."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = PROJECT_ROOT / "compose.yaml"
DOCKER = shutil.which("docker")


def load_compose_config() -> dict[str, Any]:
    """Ask Docker Compose to parse and normalize the project configuration."""
    if DOCKER is None:
        pytest.skip("Docker Compose is not installed")

    result = subprocess.run(
        [DOCKER, "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.integration
def test_postgres_compose_contract() -> None:
    """Keep the local database private, persistent, and health checked."""
    config = load_compose_config()
    postgres = config["services"]["postgres"]

    assert postgres["image"] == "postgres:18"
    assert postgres["restart"] == "unless-stopped"
    assert postgres["environment"]["POSTGRES_DB"] == "marketpulse"
    assert postgres["environment"]["POSTGRES_USER"] == "marketpulse"

    host_port = postgres["ports"][0]
    assert host_port["host_ip"] == "127.0.0.1"
    assert str(host_port["published"]) == "5432"
    assert host_port["target"] == 5432

    data_mount = next(mount for mount in postgres["volumes"] if mount["type"] == "volume")
    assert data_mount["target"] == "/var/lib/postgresql"

    healthcheck = postgres["healthcheck"]
    assert "pg_isready" in " ".join(healthcheck["test"])
    assert healthcheck["retries"] == 12
