from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from personal_ai_os.satellites.windows.allowlist import WindowsAllowlist
from personal_ai_os.satellites.windows.contracts import PROTOCOL_VERSION, ToolCommand
from personal_ai_os.satellites.windows.credentials import MemoryCredentialStore
from personal_ai_os.satellites.windows.execution import WindowsExecutionEngine
from personal_ai_os.satellites.windows.replay import ReplayConflictError, ReplayJournal
from personal_ai_os.tools.contracts import ToolObservationStatus
from personal_ai_os.tools.registry import argument_digest, default_registry


def _allowlist(tmp_path: Path) -> WindowsAllowlist:
    search = tmp_path / "search"
    search.mkdir()
    workflow = tmp_path / "workflow.py"
    workflow.write_text("from pathlib import Path\nPath('done.marker').touch()\n")
    document = {
        "schema_version": "phase-09-windows-allowlist/v1",
        "apps": [],
        "projects": [],
        "search_roots": [{"root_id": "documents", "directory": str(search), "max_entries": 100}],
        "workflows": [
            {
                "workflow_id": "bounded",
                "executable": str(Path(sys.executable)),
                "fixed_args": [],
                "working_directory": str(tmp_path),
                "script": str(workflow),
                "timeout_seconds": 5,
                "expected_exit_codes": [0],
                "allow_hard_stop": False,
                "verification": {
                    "kind": "marker_file_exists",
                    "path": str(tmp_path / "done.marker"),
                },
            }
        ],
    }
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return WindowsAllowlist.load(path)


def _command(name: str, arguments: dict[str, object], capability: str) -> ToolCommand:
    descriptor = default_registry().resolve(name, 1)
    validated = default_registry().validate_arguments(descriptor, arguments)
    return ToolCommand(
        protocol_version=PROTOCOL_VERSION,
        session_id=uuid4(),
        command_id=uuid4(),
        correlation_id="phase09-test",
        name=name,
        version=1,
        arguments=validated,
        argument_digest=argument_digest(validated),
        required_capability=capability,
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
        timeout_seconds=5,
    )


def test_metadata_search_is_bounded_and_rejects_path_input(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path)
    search = Path(allowlist.search_roots["documents"].directory)
    (search / "Quarterly Report.txt").write_text("private content is not returned")
    engine = WindowsExecutionEngine(allowlist)
    result = engine.execute(
        _command(
            "windows.files.search",
            {"root_id": "documents", "query": "report", "max_results": 5},
            "windows.files.search",
        )
    )
    assert result.status is ToolObservationStatus.SUCCEEDED
    assert result.output["results"][0]["relative_path"] == "Quarterly Report.txt"  # type: ignore[index]
    assert "private content" not in result.model_dump_json()

    rejected = engine.execute(
        _command(
            "windows.files.search",
            {"root_id": "documents", "query": "../report", "max_results": 5},
            "windows.files.search",
        )
    )
    assert rejected.failure_code == "search_query_invalid"


def test_consequential_workflow_is_fixed_verified_and_replay_safe(tmp_path: Path) -> None:
    engine = WindowsExecutionEngine(_allowlist(tmp_path))
    command = _command(
        "windows.workflow.start",
        {"workflow_id": "bounded"},
        "windows.workflow.start",
    )
    result = engine.execute(command)
    assert result.status is ToolObservationStatus.SUCCEEDED
    assert result.output == {
        "workflow_id": "bounded",
        "exit_code": 0,
        "verification_passed": True,
    }

    journal_path = tmp_path / "state" / "replay.json"
    journal = ReplayJournal(journal_path)
    journal.begin(command)
    journal.finish(command, result)
    assert journal.lookup(command) == result
    restarted = ReplayJournal(journal_path)
    assert restarted.lookup(command) == "consequential_outcome_uncertain"
    changed = command.model_copy(update={"argument_digest": "a" * 64})
    try:
        restarted.lookup(changed)
    except ReplayConflictError:
        pass
    else:
        raise AssertionError("changed digest was accepted")


def test_deadline_digest_and_capability_fail_closed(tmp_path: Path) -> None:
    engine = WindowsExecutionEngine(_allowlist(tmp_path))
    command = _command("windows.status.read", {}, "windows.telemetry.read")
    expired = command.model_copy(update={"deadline_at": datetime.now(UTC)})
    assert engine.execute(expired).failure_code == "command_deadline_expired"
    changed = command.model_copy(update={"argument_digest": "0" * 64})
    assert engine.execute(changed).failure_code == "argument_digest_mismatch"
    wrong_capability = command.model_copy(update={"required_capability": "windows.files.search"})
    assert engine.execute(wrong_capability).failure_code == "capability_binding_mismatch"


def test_memory_credential_rotation_and_revocation_are_immediate() -> None:
    store = MemoryCredentialStore()
    assert store.read() is None
    store.write("opaque-first")
    assert store.read() == "opaque-first"
    store.write("opaque-rotated")
    assert store.read() == "opaque-rotated"
    store.delete()
    assert store.read() is None


def test_telemetry_is_finite_bounded_and_contains_no_identity(tmp_path: Path) -> None:
    result = WindowsExecutionEngine(_allowlist(tmp_path)).execute(
        _command("windows.status.read", {}, "windows.telemetry.read")
    )
    assert result.status is ToolObservationStatus.SUCCEEDED
    for field in ("cpu_percent", "memory_percent", "disk_percent"):
        assert math.isfinite(result.output[field])  # type: ignore[arg-type]
        assert 0 <= result.output[field] <= 100  # type: ignore[operator]
    encoded = result.model_dump_json().casefold()
    assert "username" not in encoded
    assert "serial" not in encoded
    assert "credential" not in encoded


def test_workflow_timeout_and_owned_cancellation_are_typed(tmp_path: Path) -> None:
    allowlist = _allowlist(tmp_path)
    workflow = tmp_path / "workflow.py"
    workflow.write_text("import time\ntime.sleep(10)\n")
    engine = WindowsExecutionEngine(allowlist)
    timeout_command = _command(
        "windows.workflow.start",
        {"workflow_id": "bounded"},
        "windows.workflow.start",
    ).model_copy(update={"timeout_seconds": 0.2})
    timed_out = engine.execute(timeout_command)
    assert timed_out.failure_code == "workflow_timeout"

    cancel_command = _command(
        "windows.workflow.start",
        {"workflow_id": "bounded"},
        "windows.workflow.start",
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(engine.execute, cancel_command)
        delivered = False
        for _ in range(50):
            delivered = engine.cancel(cancel_command.command_id)
            if delivered:
                break
            time.sleep(0.02)
        assert delivered
        cancelled = future.result(timeout=5)
    assert cancelled.status is ToolObservationStatus.CANCELLED
    assert cancelled.verification["owned_process_stopped"] is True
    assert engine.cancel(uuid4()) is False


def test_app_and_project_dispatch_never_use_shell_or_remote_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = Path(sys.executable)
    project = tmp_path / "project"
    project.mkdir()
    document = {
        "schema_version": "phase-09-windows-allowlist/v1",
        "apps": [
            {
                "app_id": "editor",
                "executable": str(executable),
                "fixed_args": ["--version"],
                "working_directory": str(tmp_path),
                "observe_process": True,
            }
        ],
        "projects": [
            {
                "project_id": "bmo",
                "executable": str(executable),
                "fixed_args": ["--version"],
                "working_directory": str(tmp_path),
                "project_directory": str(project),
            }
        ],
        "search_roots": [],
        "workflows": [],
    }
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    engine = WindowsExecutionEngine(WindowsAllowlist.load(path))
    calls: list[tuple[list[str], dict[str, object]]] = []

    class _Process:
        returncode = None

        def poll(self) -> None:
            return None

    def fake_popen(arguments: list[str], **kwargs: object) -> _Process:
        calls.append((arguments, kwargs))
        return _Process()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    app = engine.execute(_command("windows.app.open", {"app_id": "editor"}, "windows.app.open"))
    project_result = engine.execute(
        _command("windows.project.open", {"project_id": "bmo"}, "windows.project.open")
    )
    assert app.status is ToolObservationStatus.SUCCEEDED
    assert project_result.status is ToolObservationStatus.SUCCEEDED
    resolved_executable = str(executable.resolve())
    assert calls[0][0] == [resolved_executable, "--version"]
    assert calls[1][0] == [resolved_executable, "--version", str(project.resolve())]
    assert all(kwargs["shell"] is False for _, kwargs in calls)
