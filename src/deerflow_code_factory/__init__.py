"""DeerFlow code factory extension."""

from pathlib import Path
from typing import Any

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BackendAction, PluginContribution

from .store import FactoryStore


@extension(api="0.2.5", name="code-factory")
def install(registry: Any, config: dict[str, Any]) -> None:
    path = config.get("storage_path")
    enabled = config.get("enabled", False)
    if (
        not isinstance(path, str)
        or not Path(path).is_absolute()
        or type(enabled) is not bool
    ):
        raise ValueError("configure absolute storage_path and boolean enabled")
    store = FactoryStore(path)

    async def create_factory(payload: dict[str, Any], context: Any) -> dict[str, Any]:
        if set(payload) != {"repository_id", "owner", "repo"}:
            raise ValueError("invalid factory fields")
        return store.create_factory(
            owner_user_id=context.principal.user_id,
            repository_id=payload["repository_id"],
            owner=payload["owner"],
            repo=payload["repo"],
        )

    async def list_factories(
        payload: dict[str, Any], context: Any
    ) -> list[dict[str, Any]]:
        if payload:
            raise ValueError("list_factories takes no fields")
        return store.list_factories(context.principal.user_id)

    accepted = registry.plugin(
        PluginContribution(
            namespace="code-factory",
            title="代码工厂 / Code factory",
            description="GitHub Issue-driven requirement development.",
            enabled=enabled,
            backend=(
                BackendAction("create_factory", create_factory),
                BackendAction("list_factories", list_factories),
            ),
        )
    )
    if accepted is not True:
        raise RuntimeError("code factory requires full-stack plugin support")
