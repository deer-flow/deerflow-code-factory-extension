from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow_code_factory import install
from deerflow_code_factory.github.gh_cli import ValidationReport
from deerflow_code_factory.store import FactoryStore


class Registry:
    def __init__(self):
        self.contribution = None

    def plugin(self, contribution):
        self.contribution = contribution
        return True

    def service(self, service):
        self.service_instance = service


@pytest.mark.asyncio
async def test_install_registers_owner_scoped_actions(
    tmp_path: Path, monkeypatch
) -> None:
    async def validate(self, owner, repo):
        return ValidationReport(42, owner, repo, (), ())

    monkeypatch.setattr(
        "deerflow_code_factory.github.gh_cli.GhRepositorySetup.validate", validate
    )
    registry = Registry()
    install(
        registry,
        {
            "storage_path": str(tmp_path / "factory.sqlite"),
            "enabled": True,
            "operator_user_ids": ["alice"],
        },
    )
    assert registry.contribution.namespace == "code-factory"
    actions = {action.name: action.handler for action in registry.contribution.backend}
    context = SimpleNamespace(principal=SimpleNamespace(user_id="alice"))
    created = await actions["create_factory"](
        {"owner": "acme", "repo": "widget", "create_labels": False}, context
    )
    assert created["repository_id"] == 42
    assert len(await actions["list_factories"]({}, context)) == 1
    store = FactoryStore(tmp_path / "factory.sqlite")
    job = store.create_or_get_job(created["id"], issue_id=70, issue_number=7)
    store.transition(
        job["id"],
        expected_version=0,
        phase="awaiting_checks",
        evidence={
            "pr_url": "https://github.com/acme/widget/pull/9",
            "pr_number": 9,
            "head_sha": "head",
        },
    )
    listed = await actions["list_jobs"]({"factory_id": created["id"]}, context)
    assert listed[0]["pr_url"] == "https://github.com/acme/widget/pull/9"
    assert listed[0]["issue_url"] == "https://github.com/acme/widget/issues/7"
    other = SimpleNamespace(principal=SimpleNamespace(user_id="bob"))
    with pytest.raises(PermissionError):
        await actions["list_factories"]({}, other)


def test_install_rejects_relative_storage_path() -> None:
    with pytest.raises(ValueError):
        install(Registry(), {"storage_path": "factory.sqlite", "enabled": True})


def test_install_registers_workspace_page_and_management_actions(
    tmp_path: Path,
) -> None:
    registry = Registry()
    install(
        registry,
        {
            "storage_path": str(tmp_path / "factory.sqlite"),
            "enabled": True,
            "operator_user_ids": ["alice"],
        },
    )
    assert registry.contribution.frontend.module == "code-factory.v1"
    names = {action.name for action in registry.contribution.backend}
    assert {
        "validate_repository",
        "create_factory",
        "list_factories",
        "set_factory_enabled",
        "scan_factory",
        "list_jobs",
    } <= names
