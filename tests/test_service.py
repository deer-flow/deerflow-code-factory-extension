import asyncio

import pytest

from deerflow_code_factory.service import PollService
from deerflow_code_factory.store import FactoryStore


class Store:
    def list_enabled_factories(self):
        return [{"id": "one"}, {"id": "two"}]


class Poller:
    def __init__(self):
        self.seen = []

    async def scan_factory(self, factory_id):
        self.seen.append(factory_id)
        if factory_id == "one":
            raise OSError("offline")


@pytest.mark.asyncio
async def test_service_continues_other_factories_after_scan_failure():
    poller = Poller()
    service = PollService(Store(), poller, 30)
    await service.start(None)
    for _ in range(50):
        if len(poller.seen) >= 2:
            break
        await asyncio.sleep(0)
    await service.stop()
    assert poller.seen == ["one", "two"]


@pytest.mark.asyncio
async def test_service_records_merge_intent_before_merging(tmp_path):
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    job = store.create_or_get_job(factory["id"], issue_id=70, issue_number=7)
    delivery = {
        "pr_number": 9,
        "head_sha": "a" * 40,
        "pr_url": "https://github.com/acme/widget/pull/9",
    }
    store.transition(
        job["id"], expected_version=0, phase="awaiting_checks", evidence=delivery
    )
    job = store.get_job_internal(job["id"])
    service = PollService(store, Poller(), 30)

    class Completion:
        async def refresh(self, *args, **kwargs):
            return {"state": "awaiting_merge", "ready": True}

        async def merge_if_ready(self, *args, **kwargs):
            events = store.list_events(job["id"])
            assert events[-1]["evidence"]["merge_attempt"] is True
            return {"state": "done", "merge_sha": "merge1"}

    service.completion = Completion()
    await service._refresh_job(factory, job)
    assert store.get_job_internal(job["id"])["phase"] == "done"


@pytest.mark.asyncio
async def test_service_starts_one_repair_for_new_feedback(tmp_path):
    store = FactoryStore(tmp_path / "factory.sqlite")
    factory = store.create_factory(
        owner_user_id="alice", repository_id=42, owner="acme", repo="widget"
    )
    job = store.create_or_get_job(factory["id"], issue_id=70, issue_number=7)
    store.transition(
        job["id"], expected_version=0, phase="coding", evidence={"spec": "Add mul"}
    )
    delivery = {
        "pr_number": 9,
        "head_sha": "a" * 40,
        "head_branch": "code-factory/issue-7-run-0",
    }
    store.transition(
        job["id"], expected_version=1, phase="awaiting_checks", evidence=delivery
    )
    service = PollService(store, Poller(), 30)

    class Completion:
        async def refresh(self, *args, **kwargs):
            return {
                "state": "awaiting_review",
                "reason": "open thread",
                "feedback": [{"id": "comment-1", "body": "Fix zero"}],
            }

    class Repair:
        invoker = object()
        calls = []

        def start(self, *args):
            self.calls.append(args[-2])
            return True

    service.completion = Completion()
    service.review_repair = Repair()
    await service._refresh_job(factory, store.get_job_internal(job["id"]))
    assert len(service.review_repair.calls) == 1
    current = store.get_job_internal(job["id"])
    store.transition(
        current["id"],
        expected_version=current["version"],
        phase="awaiting_checks",
        evidence={**delivery, "addressed_feedback_ids": ["comment-1"]},
    )
    await service._refresh_job(factory, store.get_job_internal(job["id"]))
    assert len(service.review_repair.calls) == 1
