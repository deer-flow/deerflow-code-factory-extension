from pathlib import Path

from deerflow_code_factory.checks import DockerChecker
import pytest


def test_docker_checks_have_no_network_or_credentials(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return type(
            "Result", (), {"returncode": 1, "stdout": "1 failure", "stderr": ""}
        )()

    monkeypatch.setattr("subprocess.run", run)
    result = DockerChecker(
        "python:3.12-slim", "python -m unittest discover -s tests"
    ).run(tmp_path)
    argv, options = calls[0]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert argv[argv.index("--network") + 1] == "none"
    assert "--cap-drop" in argv and "--read-only" in argv
    assert "/workspace/.git:rw,nosuid,noexec,size=1m" in argv
    assert result.passed is False
    assert result.exit_code == 1
    assert "1 failure" in result.output
    assert options["shell"] is False


def test_missing_image_blocks_before_development(monkeypatch) -> None:
    def run(argv, **kwargs):
        return type(
            "Result", (), {"returncode": 1, "stdout": "", "stderr": "missing"}
        )()

    monkeypatch.setattr("subprocess.run", run)
    with pytest.raises(RuntimeError, match="image"):
        DockerChecker("python:3.12-slim", "python -m unittest").require_ready()
