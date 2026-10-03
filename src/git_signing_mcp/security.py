# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

import fnmatch
import json
import logging
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from .config import Settings


logger = logging.getLogger("git_signing_mcp.audit")


def audit(event: str, **fields: object) -> None:
    payload = {
        "event": event,
        "timestamp": int(time.time()),
        **fields,
    }
    logger.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def new_request_id() -> str:
    return uuid.uuid4().hex


def validate_branch_name(branch: str) -> None:
    if not branch or len(branch) > 255:
        raise ValueError("invalid branch name")
    if branch.startswith(("-", ".", "/")) or branch.endswith(("/", ".", ".lock")):
        raise ValueError("invalid branch name")
    forbidden = ("..", "//", "@{", "\\", " ", "~", "^", ":", "?", "*", "[")
    if any(item in branch for item in forbidden):
        raise ValueError("invalid branch name")
    if any(ord(char) < 32 or ord(char) == 127 for char in branch):
        raise ValueError("invalid branch name")


def validate_branch_policy(settings: Settings, branch: str) -> None:
    validate_branch_name(branch)
    if settings.allow_protected_branch_writes:
        return
    if any(
        fnmatch.fnmatchcase(branch.lower(), pattern.lower())
        for pattern in settings.protected_branch_patterns
    ):
        raise PermissionError(
            "direct writes to protected branches are disabled; use a feature branch"
        )


def validate_change_path(repo: Path, path: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or not candidate.parts:
        raise ValueError("invalid repository path")
    if ".." in candidate.parts or any(part == ".git" for part in candidate.parts):
        raise ValueError("unsafe repository path")

    root = repo.resolve()
    current = root
    for part in candidate.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("writes through repository symlinks are not allowed")

    parent = current.parent.resolve(strict=False)
    if not parent.is_relative_to(root):
        raise ValueError("repository path escapes the worktree")
    return candidate


class WriteGuard:
    def __init__(self, settings: Settings) -> None:
        self._limit = settings.max_writes_per_minute
        self._window: deque[float] = deque()
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(settings.max_concurrent_writes)

    @contextmanager
    def hold(self) -> Iterator[None]:
        now = time.monotonic()
        with self._lock:
            cutoff = now - 60.0
            while self._window and self._window[0] <= cutoff:
                self._window.popleft()
            if len(self._window) >= self._limit:
                raise RuntimeError("write rate limit exceeded")
            self._window.append(now)

        acquired = self._semaphore.acquire(timeout=5)
        if not acquired:
            raise RuntimeError("write concurrency limit exceeded")
        try:
            yield
        finally:
            self._semaphore.release()
