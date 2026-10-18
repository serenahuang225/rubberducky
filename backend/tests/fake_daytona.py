"""An in-process stand-in for ``daytona.AsyncDaytona`` and its sandbox objects.

The adapter is handed this client at the SDK class boundary (``client_factory``); a signature
test compares every method it uses with the installed SDK, so the fake cannot drift from the
real contract unnoticed. ``exec`` really runs the *uploaded* ``trusted_checks.py`` on the
*uploaded* spec in a temporary directory, so the repository's trusted renderer/invariant checks
execute for real; failure modes replace only the sandbox's response. This is a transport
fixture: no Daytona account, sandbox or spend exists.
"""

import asyncio
import json
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class FakeDaytonaError(Exception):
    """Stands in for any SDK failure (the adapter must not copy its text anywhere)."""


class FakeFileSystem:
    def __init__(self, sandbox: "FakeSandbox") -> None:
        self._sandbox = sandbox

    async def upload_file(self, src: str | bytes, dst: str, timeout: int = 1800) -> None:
        self._sandbox.files[dst] = src if isinstance(src, bytes) else src.encode()


class FakeProcess:
    def __init__(self, sandbox: "FakeSandbox") -> None:
        self._sandbox = sandbox

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> Any:
        sandbox = self._sandbox
        service = sandbox.service
        service.exec_calls.append(command)
        mode = service.exec_mode
        if mode == "hang":
            await asyncio.sleep(3600)
        if mode == "exec_error":
            raise FakeDaytonaError("sandbox command failed: sk-leaky-secret-0123456789")
        if mode == "fixture_timeout":
            raise service.timeout_error()
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in sandbox.files.items():
                (Path(tmp) / name).write_bytes(content)
            done = subprocess.run(
                [sys.executable, *command.split()[1:]],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        report = json.loads(done.stdout.strip().splitlines()[-1])
        if mode == "garbage":
            return SimpleNamespace(exit_code=0, result="<html>not a report</html>")
        if mode == "wrong_digest":
            report["spec_digest"] = "0" * 64
            return SimpleNamespace(exit_code=0, result=json.dumps(report))
        if mode == "canned_fail":
            report["passed"] = False
            report["checks"][3] = {
                "name": "layout_math",
                "passed": False,
                "detail": "sandbox says no",
            }
            return SimpleNamespace(exit_code=1, result=json.dumps(report))
        if mode == "exit_mismatch":
            return SimpleNamespace(exit_code=1, result=json.dumps(report))
        if mode == "oversize_report":
            return SimpleNamespace(exit_code=0, result="x" * 20_000)
        return SimpleNamespace(exit_code=done.returncode, result=done.stdout)


class FakeSandbox:
    def __init__(self, service: "FakeDaytonaService", sandbox_id: str, labels: dict[str, str]):
        self.service = service
        self.id = sandbox_id
        self.labels = labels
        self.files: dict[str, bytes] = {}
        self.fs = FakeFileSystem(self)
        self.process = FakeProcess(self)


class FakeDaytonaService:
    """The shared 'account': every sandbox that exists, and a log of what was created/deleted."""

    def __init__(self) -> None:
        self.sandboxes: dict[str, FakeSandbox] = {}
        self.created_ids: list[str] = []
        self.deleted_ids: list[str] = []
        self.create_params: list[Any] = []
        self.exec_calls: list[str] = []
        self.client_closed = 0
        # create_mode: ok | error | orphan_error (service made it, client saw an error)
        #              | orphan_hang (service made it, reply never arrives)
        self.create_mode = "ok"
        self.exec_mode = "real"
        self.delete_failures: set[str] = set()
        self.list_error = False
        self._counter = 0
        self.timeout_error: Any = lambda: TimeoutError()

    def add_decoy(self, sandbox_id: str, labels: dict[str, str] | None = None) -> FakeSandbox:
        decoy = FakeSandbox(self, sandbox_id, labels or {"owner": "someone-else"})
        self.sandboxes[sandbox_id] = decoy
        return decoy

    def _new(self, labels: dict[str, str]) -> FakeSandbox:
        self._counter += 1
        sandbox = FakeSandbox(self, f"sbx-created-{self._counter}", labels)
        self.sandboxes[sandbox.id] = sandbox
        self.created_ids.append(sandbox.id)
        return sandbox

    def client(self, _config: object = None) -> "FakeAsyncDaytona":
        return FakeAsyncDaytona(self)


class FakeAsyncDaytona:
    def __init__(self, service: FakeDaytonaService) -> None:
        self._service = service

    async def create(
        self, params: Any = None, *, timeout: float = 60, on_snapshot_create_logs: Any = None
    ) -> FakeSandbox:
        service = self._service
        service.create_params.append(params)
        labels = dict(getattr(params, "labels", None) or {})
        if service.create_mode == "error":
            raise FakeDaytonaError("create refused")
        if service.create_mode == "orphan_error":
            service._new(labels)
            raise FakeDaytonaError("connection reset after create")
        if service.create_mode == "orphan_hang":
            service._new(labels)
            await asyncio.sleep(3600)
        return service._new(labels)

    async def delete(self, sandbox: FakeSandbox, timeout: float = 60, wait: bool = False) -> None:
        service = self._service
        if sandbox.id in service.delete_failures:
            raise FakeDaytonaError("delete refused")
        service.sandboxes.pop(sandbox.id, None)
        service.deleted_ids.append(sandbox.id)

    async def list(
        self, query: Any = None, request_timeout: float | None = None
    ) -> AsyncIterator[FakeSandbox]:
        service = self._service
        if service.list_error:
            raise FakeDaytonaError("list refused")
        wanted = getattr(query, "labels", None) or {}
        for sandbox in list(service.sandboxes.values()):
            if all(sandbox.labels.get(key) == value for key, value in wanted.items()):
                yield sandbox

    async def close(self) -> None:
        self._service.client_closed += 1
