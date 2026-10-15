"""Small SQLite store for factories, requirement jobs and transition evidence."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any


class StaleVersion(ValueError):
    """The job moved since the caller read it."""


class FactoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS factories (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL,
                    repository_id INTEGER NOT NULL UNIQUE,
                    owner TEXT NOT NULL,
                    repo TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    poll_cursor TEXT
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    factory_id TEXT NOT NULL REFERENCES factories(id),
                    issue_id INTEGER NOT NULL,
                    issue_number INTEGER NOT NULL,
                    phase TEXT NOT NULL DEFAULT 'draft',
                    version INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(factory_id, issue_id)
                );
                CREATE TABLE IF NOT EXISTS job_events (
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    version INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(job_id, version)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _as_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def create_factory(
        self, *, owner_user_id: str, repository_id: int, owner: str, repo: str
    ) -> dict[str, Any]:
        if not owner_user_id or repository_id <= 0 or not owner or not repo:
            raise ValueError("invalid factory")
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO factories(id, owner_user_id, repository_id, owner, repo) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), owner_user_id, repository_id, owner, repo),
            )
            row = db.execute(
                "SELECT * FROM factories WHERE repository_id=?", (repository_id,)
            ).fetchone()
            if row["owner_user_id"] != owner_user_id:
                raise PermissionError("repository belongs to another factory owner")
            return dict(row)

    def list_factories(self, owner_user_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM factories WHERE owner_user_id=? ORDER BY owner, repo",
                (owner_user_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_factory(
        self, factory_id: str, *, owner_user_id: str | None = None
    ) -> dict[str, Any] | None:
        with closing(self._connect()) as db:
            if owner_user_id is None:
                row = db.execute(
                    "SELECT * FROM factories WHERE id=?", (factory_id,)
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM factories WHERE id=? AND owner_user_id=?",
                    (factory_id, owner_user_id),
                ).fetchone()
            return self._as_dict(row)

    def create_or_get_job(
        self, factory_id: str, *, issue_id: int, issue_number: int
    ) -> dict[str, Any]:
        if issue_id <= 0 or issue_number <= 0:
            raise ValueError("invalid issue")
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO jobs(id, factory_id, issue_id, issue_number) VALUES (?, ?, ?, ?)",
                (str(uuid.uuid4()), factory_id, issue_id, issue_number),
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE factory_id=? AND issue_id=?",
                (factory_id, issue_id),
            ).fetchone()
            return dict(row)

    def get_job(self, job_id: str, *, owner_user_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT j.* FROM jobs j JOIN factories f ON f.id=j.factory_id WHERE j.id=? AND f.owner_user_id=?",
                (job_id, owner_user_id),
            ).fetchone()
            return self._as_dict(row)

    def list_jobs(self, factory_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE factory_id=? ORDER BY issue_number",
                (factory_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def set_poll_cursor(self, factory_id: str, cursor: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE factories SET poll_cursor=? WHERE id=?", (cursor, factory_id)
            )

    def transition(
        self,
        job_id: str,
        *,
        expected_version: int,
        phase: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        if not phase or not isinstance(evidence, dict):
            raise ValueError("invalid transition")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE jobs SET phase=?, version=version+1 WHERE id=? AND version=?",
                (phase, job_id, expected_version),
            ).rowcount
            if not changed:
                raise StaleVersion(job_id)
            db.execute(
                "INSERT INTO job_events(job_id, version, phase, evidence_json) VALUES (?, ?, ?, ?)",
                (
                    job_id,
                    expected_version + 1,
                    phase,
                    json.dumps(evidence, sort_keys=True),
                ),
            )
            return dict(
                db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            )

    def list_events(self, job_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT version, phase, evidence_json FROM job_events WHERE job_id=? ORDER BY version",
                (job_id,),
            ).fetchall()
            return [
                {
                    "version": row["version"],
                    "phase": row["phase"],
                    "evidence": json.loads(row["evidence_json"]),
                }
                for row in rows
            ]
