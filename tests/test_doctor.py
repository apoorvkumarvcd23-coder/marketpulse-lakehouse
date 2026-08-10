"""Tests for the deterministic beginner setup doctor."""

from pathlib import Path

import pytest

from marketpulse.cli import main
from marketpulse.doctor import format_doctor_report, run_doctor


def _write_valid_project(project_root: Path) -> None:
    for name in ("README.md", "ROADMAP.md"):
        (project_root / name).write_text(f"# {name}\n", encoding="utf-8")
    (project_root / "pyproject.toml").write_text(
        """[project]
name = "marketpulse-lakehouse"
requires-python = ">=3.12,<3.13"
""",
        encoding="utf-8",
    )
    (project_root / "uv.lock").write_text(
        """version = 1
requires-python = "==3.12.*"

[[package]]
name = "marketpulse-lakehouse"
version = "0.1.0"
""",
        encoding="utf-8",
    )
    (project_root / ".gitignore").write_text(
        "/data/\n/outputs/\n.env\n",
        encoding="utf-8",
    )


def test_doctor_passes_a_complete_python_312_project(tmp_path: Path) -> None:
    _write_valid_project(tmp_path)

    report = run_doctor(tmp_path, python_version=(3, 12, 13))

    assert report.passed
    assert report.passed_count == 5
    assert all(check.passed for check in report.checks)
    assert "Ready: the basic local project setup is reproducible." in format_doctor_report(report)


def test_doctor_explains_an_incompatible_python_version(tmp_path: Path) -> None:
    _write_valid_project(tmp_path)

    report = run_doctor(tmp_path, python_version=(3, 14, 0))
    python_check = report.checks[0]

    assert not report.passed
    assert not python_check.passed
    assert "Python 3.14.0" in python_check.detail
    assert "uv python install 3.12" in python_check.fix


@pytest.mark.parametrize("missing_name", ["README.md", "uv.lock"])
def test_doctor_reports_missing_root_files(tmp_path: Path, missing_name: str) -> None:
    _write_valid_project(tmp_path)
    (tmp_path / missing_name).unlink()

    report = run_doctor(tmp_path, python_version=(3, 12, 13))
    files_check = next(check for check in report.checks if check.name == "Project files")

    assert not report.passed
    assert missing_name in files_check.detail


def test_doctor_reports_invalid_project_metadata(tmp_path: Path) -> None:
    _write_valid_project(tmp_path)
    (tmp_path / "pyproject.toml").write_text("not valid = [", encoding="utf-8")

    report = run_doctor(tmp_path, python_version=(3, 12, 13))
    metadata_check = next(check for check in report.checks if check.name == "Project metadata")

    assert not metadata_check.passed
    assert "could not be read" in metadata_check.detail


def test_doctor_rejects_a_lock_without_the_project_package(tmp_path: Path) -> None:
    _write_valid_project(tmp_path)
    (tmp_path / "uv.lock").write_text(
        'version = 1\nrequires-python = "==3.12.*"\n',
        encoding="utf-8",
    )

    report = run_doctor(tmp_path, python_version=(3, 12, 13))
    lock_check = next(check for check in report.checks if check.name == "Locked environment")

    assert not lock_check.passed
    assert "project package present=False" in lock_check.detail


def test_doctor_requires_private_data_and_journal_boundaries(tmp_path: Path) -> None:
    _write_valid_project(tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")

    report = run_doctor(tmp_path, python_version=(3, 12, 13))
    privacy_check = next(
        check for check in report.checks if check.name == "Private-file boundaries"
    )

    assert not privacy_check.passed
    assert "/data/" in privacy_check.detail
    assert "/outputs/" in privacy_check.detail


def test_doctor_command_prints_the_five_check_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_valid_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    exit_code = main(["doctor"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "[PASS] Python version" in output
    assert "Result: 5/5 checks passed" in output


def test_doctor_command_returns_failure_and_repair_hints_outside_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main(["doctor"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "[FAIL] Project files" in output
    assert "Fix:" in output
    assert "Not ready: fix the failed checks" in output
