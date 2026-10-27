"""Run operator-configured repository checks in a bounded Docker container."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    exit_code: int
    output: str


class DockerChecker:
    def __init__(self, image: str, command: str, timeout_seconds: int = 120):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,199}", image):
            raise ValueError("invalid Docker image")
        if (
            not command.strip()
            or len(command) > 500
            or not 10 <= timeout_seconds <= 600
        ):
            raise ValueError("invalid check command or timeout")
        self.image = image
        self.command = command
        self.timeout_seconds = timeout_seconds

    def require_ready(self) -> None:
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True,
                text=True,
                timeout=20,
                shell=False,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Docker is unavailable for local checks") from exc
        if result.returncode:
            raise RuntimeError(f"Docker check image is unavailable: {self.image}")

    def run(self, workspace: str | Path) -> CheckResult:
        path = Path(workspace).resolve(strict=True)
        argv = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--read-only",
            "--pids-limit",
            "256",
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m",
            "--tmpfs",
            "/workspace/.git:rw,nosuid,noexec,size=1m",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-v",
            f"{path}:/workspace:rw",
            "-w",
            "/workspace",
            self.image,
            "sh",
            "-lc",
            self.command,
        ]
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(False, 124, "Checks exceeded the configured timeout")
        except OSError as exc:
            raise RuntimeError("Docker is unavailable; checks were not run") from exc
        return CheckResult(
            result.returncode == 0,
            result.returncode,
            (result.stdout + result.stderr)[-20_000:],
        )
