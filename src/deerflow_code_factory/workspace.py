"""Per-run Git checkout, with credentials confined to the Gateway host."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .github.delivery import validate_files

_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_JOB = re.compile(r"^[A-Za-z0-9-]+$")


class JobWorkspace:
    def __init__(self, root: str | Path, job_id: str, version: int):
        if not _JOB.fullmatch(job_id) or version < 0:
            raise ValueError("invalid workspace identity")
        self.root = Path(root).resolve()
        self.version = version
        self.path = self.root / f"{job_id}-v{version}"
        self.branch: str | None = None

    def _run(
        self, argv: list[str], *, cwd: Path | None = None, timeout: int = 120
    ) -> str:
        try:
            result = subprocess.run(
                argv,
                cwd=cwd or self.path,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"workspace command unavailable: {argv[0]}") from exc
        if result.returncode:
            raise RuntimeError(
                f"workspace command failed: {argv[0]} {argv[1] if len(argv) > 1 else ''}"
            )
        return result.stdout[:100_000]

    def prepare(self, owner: str, repo: str, base_sha: str, issue_number: int) -> None:
        if (
            not _NAME.fullmatch(owner)
            or not _NAME.fullmatch(repo)
            or not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha)
            or issue_number <= 0
        ):
            raise ValueError("invalid repository checkout inputs")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(
                "job workspace already exists; inspect before retrying"
            )
        self.branch = f"code-factory/issue-{issue_number}-run-{self.version}"
        self._run(
            [
                "gh",
                "repo",
                "clone",
                f"{owner}/{repo}",
                str(self.path),
                "--",
                "--no-checkout",
            ],
            cwd=self.root,
            timeout=180,
        )
        existing = self._run(["git", "ls-remote", "--heads", "origin", self.branch])
        if existing.strip():
            raise ValueError(
                "remote issue branch already exists; inspect before retrying"
            )
        self._run(["git", "checkout", "--detach", base_sha])
        self._run(["git", "switch", "-c", self.branch])

    def prepare_review(
        self, owner: str, repo: str, branch: str, head_sha: str, issue_number: int
    ) -> None:
        if (
            not _NAME.fullmatch(owner)
            or not _NAME.fullmatch(repo)
            or not re.fullmatch(
                rf"code-factory/issue-{issue_number}-run-[0-9]+", branch
            )
            or not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha)
        ):
            raise ValueError("invalid review checkout inputs")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError("review workspace already exists")
        self._run(
            [
                "gh",
                "repo",
                "clone",
                f"{owner}/{repo}",
                str(self.path),
                "--",
                "--no-checkout",
            ],
            cwd=self.root,
            timeout=180,
        )
        remote = self._run(["git", "ls-remote", "--heads", "origin", branch]).split()
        if not remote or remote[0] != head_sha:
            raise ValueError("PR head changed before review checkout")
        self._run(["git", "checkout", "--detach", head_sha])
        self._run(["git", "switch", "-c", branch])
        self.branch = branch

    def apply_files(self, files: list[dict[str, str]]) -> None:
        for item in validate_files(files):
            target = self.path / item["path"]
            relative_parts = Path(item["path"]).parts
            candidates = [
                self.path.joinpath(*relative_parts[:index])
                for index in range(1, len(relative_parts) + 1)
            ]
            if any(candidate.is_symlink() for candidate in candidates):
                raise ValueError("symlink paths are not allowed")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item["content"], encoding="utf-8")

    def context(self, relevant_paths: list[str] | None = None) -> str:
        paths = self._run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
        ).splitlines()
        if relevant_paths is None:
            selected = [
                p
                for p in paths
                if not p.startswith(".github/")
                and p.endswith((".py", ".md", ".toml", ".json", ".txt"))
            ][:20]
        else:
            selected = [p for p in dict.fromkeys(relevant_paths) if p in paths][:20]
        parts = ["Repository files:\n" + "\n".join(paths[:5000])]
        total = 0
        for path in selected:
            target = self.path / path
            if target.is_symlink() or not target.is_file():
                continue
            data = target.read_bytes()
            if total + len(data) > 80_000:
                break
            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            total += len(data)
            parts.append(f"\n--- {path} ---\n{content}")
        return "\n".join(parts)

    def diff(self) -> str:
        self._run(["git", "add", "-N", "."])
        return self._run(["git", "diff", "--no-ext-diff", "--", "."], timeout=60)[
            :150_000
        ]

    def commit_and_push(self, issue_number: int) -> str:
        if self.branch != f"code-factory/issue-{issue_number}-run-{self.version}":
            raise ValueError("workspace branch mismatch")
        self._run(["git", "add", "--all"])
        self._run(
            [
                "git",
                "-c",
                "user.name=DeerFlow Code Factory",
                "-c",
                "user.email=code-factory@users.noreply.github.com",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-m",
                f"Implement issue #{issue_number}",
            ]
        )
        sha = self._run(["git", "rev-parse", "HEAD"]).strip()
        self._run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "push",
                "origin",
                f"HEAD:refs/heads/{self.branch}",
            ],
            timeout=180,
        )
        return sha

    def commit_and_push_review(self, issue_number: int) -> str:
        if not self.branch or not re.fullmatch(
            rf"code-factory/issue-{issue_number}-run-[0-9]+", self.branch
        ):
            raise ValueError("review workspace branch mismatch")
        self._run(["git", "add", "--all"])
        self._run(
            [
                "git",
                "-c",
                "user.name=DeerFlow Code Factory",
                "-c",
                "user.email=code-factory@users.noreply.github.com",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-m",
                f"Address review feedback for issue #{issue_number}",
            ]
        )
        sha = self._run(["git", "rev-parse", "HEAD"]).strip()
        self._run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "push",
                "origin",
                f"HEAD:refs/heads/{self.branch}",
            ],
            timeout=180,
        )
        return sha
