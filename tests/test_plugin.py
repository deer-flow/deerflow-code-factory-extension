from pathlib import Path
from types import SimpleNamespace

import pytest

from deerflow_code_factory import install


class Registry:
    def __init__(self):
        self.contribution = None

    def plugin(self, contribution):
        self.contribution = contribution
        return True


@pytest.mark.asyncio
async def test_install_registers_owner_scoped_actions(tmp_path: Path) -> None:
    registry = Registry()
    install(
        registry, {"storage_path": str(tmp_path / "factory.sqlite"), "enabled": True}
    )
    assert registry.contribution.namespace == "code-factory"
    actions = {action.name: action.handler for action in registry.contribution.backend}
    context = SimpleNamespace(principal=SimpleNamespace(user_id="alice"))
    created = await actions["create_factory"](
        {"repository_id": 42, "owner": "acme", "repo": "widget"}, context
    )
    assert created["repository_id"] == 42
    assert len(await actions["list_factories"]({}, context)) == 1
    other = SimpleNamespace(principal=SimpleNamespace(user_id="bob"))
    assert await actions["list_factories"]({}, other) == []


def test_install_rejects_relative_storage_path() -> None:
    with pytest.raises(ValueError):
        install(Registry(), {"storage_path": "factory.sqlite", "enabled": True})
