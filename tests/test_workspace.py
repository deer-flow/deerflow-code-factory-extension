from pathlib import Path

import pytest

from deerflow_code_factory.workspace import JobWorkspace


def test_workspace_rejects_existing_run_directory(tmp_path: Path) -> None:
    workspace = JobWorkspace(tmp_path, "job-1", 0)
    workspace.path.mkdir()
    with pytest.raises(FileExistsError):
        workspace.prepare("acme", "widget", "a" * 40, 7)


def test_workspace_applies_only_validated_text_files(tmp_path: Path) -> None:
    workspace = JobWorkspace(tmp_path, "job-1", 0)
    workspace.path.mkdir()
    workspace.apply_files([{"path": "src/widget.py", "content": "value = 1\n"}])
    assert (workspace.path / "src/widget.py").read_text() == "value = 1\n"
    (workspace.path / "link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        workspace.apply_files([{"path": "link/escape.py", "content": "pass\n"}])


def test_workspace_command_uses_argv_and_rejects_existing_remote_branch(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:3] == ["git", "ls-remote", "--heads"]:
            return type(
                "Result", (), {"returncode": 0, "stdout": "existing\n", "stderr": ""}
            )()
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("subprocess.run", run)
    workspace = JobWorkspace(tmp_path, "job-1", 0)
    with pytest.raises(ValueError, match="already exists"):
        workspace.prepare("acme", "widget", "a" * 40, 7)
    assert calls[0][:3] == ["gh", "repo", "clone"]
    assert all(not isinstance(command, str) for command in calls)


def test_workspace_branch_is_unique_to_run(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("subprocess.run", run)
    workspace = JobWorkspace(tmp_path, "job-1", 6)
    workspace.prepare("acme", "widget", "a" * 40, 7)
    assert workspace.branch == "code-factory/issue-7-run-6"
    assert ["git", "ls-remote", "--heads", "origin", workspace.branch] in calls


def test_review_checkout_requires_exact_existing_head(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        output = "b" * 40 if argv[:3] == ["git", "ls-remote", "--heads"] else ""
        return type("Result", (), {"returncode": 0, "stdout": output, "stderr": ""})()

    monkeypatch.setattr("subprocess.run", run)
    workspace = JobWorkspace(tmp_path, "job-1", 6)
    with pytest.raises(ValueError, match="head changed"):
        workspace.prepare_review(
            "acme", "widget", "code-factory/issue-7-run-2", "a" * 40, 7
        )
    assert not any(argv[:2] == ["git", "push"] for argv in calls)
