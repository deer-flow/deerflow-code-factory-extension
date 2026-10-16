"""Provider-neutral requirement ticket shapes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class IssueRef:
    issue_id: int
    number: int


@dataclass(frozen=True)
class RequirementSnapshot:
    issue_id: int
    number: int
    title: str
    body: str
    author_id: int
    state: str
    labels: frozenset[str]
    updated_at: datetime
    is_pull_request: bool = False
    comments: tuple[str, ...] = ()


class RequirementSource(Protocol):
    async def list_candidates(
        self, factory: dict, since: datetime | None
    ) -> list[IssueRef]: ...

    async def fetch(self, factory: dict, ref: IssueRef) -> RequirementSnapshot: ...
