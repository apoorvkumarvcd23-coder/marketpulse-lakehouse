"""Tests for the installable MarketPulse package."""

import sys
from importlib.metadata import version

import marketpulse


def test_project_runs_with_python_312() -> None:
    """Protect compatibility-sensitive tooling from the host Python version."""
    assert sys.version_info[:2] == (3, 12)


def test_package_version_matches_installed_metadata() -> None:
    """Keep the importable package and distribution metadata in agreement."""
    assert marketpulse.__version__ == version("marketpulse-lakehouse")
