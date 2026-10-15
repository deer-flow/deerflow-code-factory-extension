"""Single-process issue discovery, with cursor advancement after a full scan."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .requirements import RequirementSource
from .store import FactoryStore


class Poller:
    def __init__(self, store: FactoryStore, source: RequirementSource):
        self.store = store
        self.source = source

    async def scan_factory(self, factory_id: str) -> int:
        factory = self.store.get_factory(factory_id)
        if factory is None:
            raise KeyError(factory_id)
        cursor = (
            datetime.fromisoformat(factory["poll_cursor"])
            if factory["poll_cursor"]
            else None
        )
        # The overlap guards against second-level timestamp ties and delayed indexing.
        since = cursor - timedelta(minutes=2) if cursor else None
        refs = await self.source.list_candidates(factory, since)
        created = 0
        latest = cursor
        for ref in refs:
            ticket = await self.source.fetch(factory, ref)
            if (
                ticket.is_pull_request
                or ticket.state != "open"
                or "factory:ready" not in ticket.labels
            ):
                continue
            existing = {job["issue_id"] for job in self.store.list_jobs(factory_id)}
            self.store.create_or_get_job(
                factory_id, issue_id=ticket.issue_id, issue_number=ticket.number
            )
            if ticket.issue_id not in existing:
                created += 1
            stamp = ticket.updated_at.astimezone(timezone.utc)
            latest = max(latest, stamp) if latest else stamp
        if latest:
            self.store.set_poll_cursor(factory_id, latest.isoformat())
        return created
