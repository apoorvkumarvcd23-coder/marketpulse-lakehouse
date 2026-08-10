"""Read-only, repeatable checks for the beginner local setup."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

EXPECTED_PYTHON = (3, 12)
EXPECTED_PROJECT_NAME = "marketpulse-lakehouse"
EXPECTED_REQUIRES_PYTHON = ">=3.12,<3.13"
REQUIRED_FILES = (
    "README.md",
    "ROADMAP.md",
    "pyproject.toml",
    "uv.lock",
    ".gitignore",
)
REQUIRED_IGNORE_RULES = ("/data/", "/outputs/", ".env")


@dataclass(frozen=True, slots=True)
class SetupCheck:
    """The outcome and repair hint for one local setup requirement."""

    name: str
    passed: bool
    detail: str
    fix: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """All deterministic checks performed against one project directory."""

    project_root: Path
    checks: tuple[SetupCheck, ...]

    @property
    def passed(self) -> bool:
        """Return true only when every required check passed."""
        return all(check.passed for check in self.checks)

    @property
    def passed_count(self) -> int:
        """Count successful checks for the human-readable summary."""
        return sum(check.passed for check in self.checks)


def _python_check(version: tuple[int, int, int]) -> SetupCheck:
    actual = version[:2]
    passed = actual == EXPECTED_PYTHON
    return SetupCheck(
        name="Python version",
        passed=passed,
        detail=f"running Python {version[0]}.{version[1]}.{version[2]}",
        fix="Run 'uv python install 3.12' and use commands through 'uv run'.",
    )


def _required_files_check(project_root: Path) -> SetupCheck:
    missing = [name for name in REQUIRED_FILES if not (project_root / name).is_file()]
    return SetupCheck(
        name="Project files",
        passed=not missing,
        detail="all required root files are present"
        if not missing
        else f"missing: {', '.join(missing)}",
        fix="Run this command from the MarketPulse repository root after a complete clone.",
    )


def _project_metadata_check(project_root: Path) -> SetupCheck:
    path = project_root / "pyproject.toml"
    try:
        with path.open("rb") as source:
            project = tomllib.load(source).get("project", {})
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return SetupCheck(
            name="Project metadata",
            passed=False,
            detail=f"pyproject.toml could not be read: {exc}",
            fix="Restore pyproject.toml from Git and rerun 'uv sync --locked'.",
        )

    name = project.get("name")
    requires_python = project.get("requires-python")
    passed = name == EXPECTED_PROJECT_NAME and requires_python == EXPECTED_REQUIRES_PYTHON
    return SetupCheck(
        name="Project metadata",
        passed=passed,
        detail=f"name={name!r}, requires-python={requires_python!r}",
        fix="Restore the project name and Python 3.12 requirement in pyproject.toml.",
    )


def _lockfile_check(project_root: Path) -> SetupCheck:
    path = project_root / "uv.lock"
    try:
        with path.open("rb") as source:
            lock = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return SetupCheck(
            name="Locked environment",
            passed=False,
            detail=f"uv.lock could not be read: {exc}",
            fix="Run 'uv lock' after reviewing dependency changes, then commit uv.lock.",
        )

    package_names = {package.get("name") for package in lock.get("package", [])}
    passed = (
        lock.get("version") == 1
        and lock.get("requires-python") == "==3.12.*"
        and EXPECTED_PROJECT_NAME in package_names
    )
    return SetupCheck(
        name="Locked environment",
        passed=passed,
        detail=(
            f"lock version={lock.get('version')!r}, "
            f"requires-python={lock.get('requires-python')!r}, project package present="
            f"{EXPECTED_PROJECT_NAME in package_names}"
        ),
        fix="Run 'uv lock' with Python 3.12 and review the resulting uv.lock change.",
    )


def _privacy_boundary_check(project_root: Path) -> SetupCheck:
    path = project_root / ".gitignore"
    try:
        rules = {
            line.partition("#")[0].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.partition("#")[0].strip()
        }
    except OSError as exc:
        return SetupCheck(
            name="Private-file boundaries",
            passed=False,
            detail=f".gitignore could not be read: {exc}",
            fix="Restore .gitignore from Git before creating local data or notes.",
        )

    missing = [rule for rule in REQUIRED_IGNORE_RULES if rule not in rules]
    return SetupCheck(
        name="Private-file boundaries",
        passed=not missing,
        detail="data, outputs, and .env are excluded from Git"
        if not missing
        else f"missing ignore rules: {', '.join(missing)}",
        fix="Restore the /data/, /outputs/, and .env rules in .gitignore.",
    )


def run_doctor(
    project_root: Path | None = None,
    *,
    python_version: tuple[int, int, int] | None = None,
) -> DoctorReport:
    """Run deterministic, read-only checks and return structured results."""
    root = (project_root or Path.cwd()).resolve()
    version = python_version or tuple(sys.version_info[:3])
    checks = (
        _python_check(version),
        _required_files_check(root),
        _project_metadata_check(root),
        _lockfile_check(root),
        _privacy_boundary_check(root),
    )
    return DoctorReport(project_root=root, checks=checks)


def format_doctor_report(report: DoctorReport) -> str:
    """Explain a doctor report in a terminal-friendly beginner format."""
    lines = ["MarketPulse setup doctor", f"Project: {report.project_root}", ""]
    for check in report.checks:
        label = "PASS" if check.passed else "FAIL"
        lines.append(f"[{label}] {check.name}: {check.detail}")
        if not check.passed:
            lines.append(f"       Fix: {check.fix}")

    lines.append("")
    lines.append(f"Result: {report.passed_count}/{len(report.checks)} checks passed")
    if report.passed:
        lines.append("Ready: the basic local project setup is reproducible.")
    else:
        lines.append("Not ready: fix the failed checks, then run the doctor again.")
    return "\n".join(lines)


__all__ = ["DoctorReport", "SetupCheck", "format_doctor_report", "run_doctor"]
