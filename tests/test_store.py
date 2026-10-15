from pathlib import Path

import pytest

from deerflow_code_factory.store import FactoryStore, StaleVersion


def test_factory_is_unique_per_repository(tmp_path: Path) -> None:
    store = FactoryStore(tmp_path / "factory.sqlite")
    first = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    second = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    assert first["id"] == second["id"]
    assert len(store.list_factories("alice")) == 1


def test_issue_creates_one_job_and_checks_owner(tmp_path: Path) -> None:
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    first = store.create_or_get_job(factory["id"], issue_id=100, issue_number=7)
    second = store.create_or_get_job(factory["id"], issue_id=100, issue_number=7)
    assert first["id"] == second["id"]
    assert store.get_job(first["id"], owner_user_id="alice") is not None
    assert store.get_job(first["id"], owner_user_id="bob") is None


def test_transition_rejects_stale_version_and_records_event(tmp_path: Path) -> None:
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    job = store.create_or_get_job(factory["id"], issue_id=100, issue_number=7)
    changed = store.transition(
        job["id"],
        expected_version=0,
        phase="analyzing",
        evidence={"issue_revision": "x"},
    )
    assert changed["version"] == 1
    assert store.list_events(job["id"]) == [
        {"version": 1, "phase": "analyzing", "evidence": {"issue_revision": "x"}}
    ]
    with pytest.raises(StaleVersion):
        store.transition(job["id"], expected_version=0, phase="coding", evidence={})
