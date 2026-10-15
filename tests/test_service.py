import asyncio

import pytest

from deerflow_code_factory.service import PollService


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
