"""Fixed Windows satellite executors with local allowlist and verification."""

from __future__ import annotations

import math
import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import psutil

from personal_ai_os.satellites.windows.allowlist import WindowsAllowlist, WorkflowEntry
from personal_ai_os.satellites.windows.contracts import CommandObservationFrame, ToolCommand
from personal_ai_os.tools.contracts import ToolObservationStatus
from personal_ai_os.tools.registry import argument_digest, default_registry

_REPARSE_POINT = 0x0400


class _OwnedExecution:
    def __init__(self, allow_hard_stop: bool) -> None:
        self.cancel = threading.Event()
        self.process: subprocess.Popen[bytes] | None = None
        self.allow_hard_stop = allow_hard_stop


class OwnedProcessRegistry:
    """Track only child work launched by a specific command ID."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._executions: dict[UUID, _OwnedExecution] = {}

    def create(self, command_id: UUID, *, allow_hard_stop: bool) -> _OwnedExecution:
        with self._lock:
            if command_id in self._executions:
                raise RuntimeError("owned_execution_duplicate")
            execution = _OwnedExecution(allow_hard_stop)
            self._executions[command_id] = execution
            return execution

    def remove(self, command_id: UUID) -> None:
        with self._lock:
            self._executions.pop(command_id, None)

    def request_cancel(self, command_id: UUID) -> bool:
        with self._lock:
            execution = self._executions.get(command_id)
            if execution is None:
                return False
            execution.cancel.set()
            return True


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        stat = path.lstat()
    except OSError:
        return True
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & _REPARSE_POINT)


def _safe_failure(
    command: ToolCommand, code: str, *, uncertain: bool = False
) -> CommandObservationFrame:
    return CommandObservationFrame(
        session_id=command.session_id,
        command_id=command.command_id,
        name=command.name,
        version=command.version,
        argument_digest=command.argument_digest,
        status=ToolObservationStatus.FAILED,
        output={},
        verification={"verified": False, "uncertain_outcome": uncertain},
        failure_code=code,
        observed_at=datetime.now(UTC),
    )


def _success(
    command: ToolCommand, output: dict[str, object], verification: dict[str, object]
) -> CommandObservationFrame:
    return CommandObservationFrame(
        session_id=command.session_id,
        command_id=command.command_id,
        name=command.name,
        version=command.version,
        argument_digest=command.argument_digest,
        status=ToolObservationStatus.SUCCEEDED,
        output=output,
        verification={"verified": True, **verification},
        observed_at=datetime.now(UTC),
    )


class WindowsExecutionEngine:
    """Execute only strict registry tools against immutable local ID mappings."""

    def __init__(
        self,
        allowlist: WindowsAllowlist,
        *,
        volume_script: Path | None = None,
        process_registry: OwnedProcessRegistry | None = None,
    ) -> None:
        self.allowlist = allowlist
        self.volume_script = volume_script or Path(__file__).with_name("media_volume.ps1")
        self.process_registry = process_registry or OwnedProcessRegistry()
        self.registry = default_registry()

    def available_capabilities(self) -> frozenset[str]:
        capabilities = set(self.allowlist.available_capabilities())
        if os.name != "nt" or not self.volume_script.is_file():
            capabilities.discard("windows.media.control")
        return frozenset(capabilities)

    def cancel(self, command_id: UUID) -> bool:
        return self.process_registry.request_cancel(command_id)

    def execute(self, command: ToolCommand) -> CommandObservationFrame:
        if datetime.now(UTC) >= command.deadline_at:
            return _safe_failure(command, "command_deadline_expired")
        try:
            descriptor = self.registry.resolve(command.name, command.version)
            if descriptor.execution_target != "windows_satellite_executor":
                return _safe_failure(command, "tool_target_invalid")
            arguments = self.registry.validate_arguments(descriptor, command.arguments)
            if argument_digest(arguments) != command.argument_digest:
                return _safe_failure(command, "argument_digest_mismatch")
            if descriptor.required_device_capabilities != frozenset({command.required_capability}):
                return _safe_failure(command, "capability_binding_mismatch")
            if command.required_capability not in self.available_capabilities():
                return _safe_failure(command, "capability_unavailable")
            if command.name == "windows.status.read":
                return self._status(command)
            if command.name == "windows.files.search":
                return self._search(command)
            if command.name == "windows.app.open":
                return self._open_app(command)
            if command.name == "windows.project.open":
                return self._open_project(command)
            if command.name == "windows.media.volume.get":
                return self._volume_get(command)
            if command.name == "windows.media.volume.set":
                return self._volume_set(command)
            if command.name == "windows.workflow.start":
                return self._workflow(command)
            return _safe_failure(command, "tool_not_supported")
        except Exception:
            return _safe_failure(command, "windows_executor_failed")

    def _status(self, command: ToolCommand) -> CommandObservationFrame:
        memory = psutil.virtual_memory()
        disk_root = Path.home().anchor or os.sep
        disk = psutil.disk_usage(disk_root)
        network = psutil.net_io_counters()
        battery_info = psutil.sensors_battery()
        battery: dict[str, object]
        if battery_info is None:
            battery = {"present": False, "percent": None, "on_ac_power": None}
        else:
            battery = {
                "present": True,
                "percent": float(battery_info.percent),
                "on_ac_power": bool(battery_info.power_plugged),
            }
        gpu = self._gpu_metrics()
        cpu_percent = float(psutil.cpu_percent(interval=0.1))
        memory_percent = float(memory.percent)
        disk_percent = float(disk.percent)
        output: dict[str, object] = {
            "timestamp_utc": datetime.now(UTC),
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "memory_available_bytes": int(memory.available),
            "disk_percent": disk_percent,
            "disk_free_bytes": int(disk.free),
            "network_bytes_sent": int(network.bytes_sent),
            "network_bytes_received": int(network.bytes_recv),
            "battery": battery,
            "gpu": gpu,
        }
        if not all(math.isfinite(value) for value in (cpu_percent, memory_percent, disk_percent)):
            return _safe_failure(command, "telemetry_non_finite")
        return _success(command, output, {"fresh": True, "bounded": True})

    @staticmethod
    def _gpu_metrics() -> dict[str, object]:
        candidates = [
            Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "nvidia-smi.exe",
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files"))
            / "NVIDIA Corporation"
            / "NVSMI"
            / "nvidia-smi.exe",
        ]
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            return {
                "available": False,
                "utilization_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "temperature_c": None,
            }
        completed = subprocess.run(
            [
                str(executable),
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
                "--id=0",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            return {
                "available": False,
                "utilization_percent": None,
                "memory_used_bytes": None,
                "memory_total_bytes": None,
                "temperature_c": None,
            }
        values = [part.strip() for part in completed.stdout.splitlines()[0].split(",")]
        if len(values) != 4:
            raise ValueError("GPU telemetry shape invalid")
        utilization, used_mib, total_mib, temperature = (float(value) for value in values)
        return {
            "available": True,
            "utilization_percent": utilization,
            "memory_used_bytes": int(used_mib * 1024 * 1024),
            "memory_total_bytes": int(total_mib * 1024 * 1024),
            "temperature_c": temperature,
        }

    def _search(self, command: ToolCommand) -> CommandObservationFrame:
        root_id = str(command.arguments["root_id"])
        query = str(command.arguments["query"])
        max_results = int(command.arguments["max_results"])
        if query in {".", ".."} or "/" in query or "\\" in query or "\x00" in query:
            return _safe_failure(command, "search_query_invalid")
        entry = self.allowlist.search_roots.get(root_id)
        if entry is None:
            return _safe_failure(command, "unknown_root_id")
        root = Path(entry.directory).resolve(strict=True)
        if not root.is_dir() or _is_reparse_or_symlink(root):
            return _safe_failure(command, "search_root_unavailable")
        results: list[dict[str, object]] = []
        scanned = 0
        truncated = False
        deadline = min(command.deadline_at.timestamp(), time.time() + command.timeout_seconds)
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            current = Path(directory)
            safe_directories: list[str] = []
            for name in directory_names:
                child = current / name
                if not _is_reparse_or_symlink(child):
                    safe_directories.append(name)
            directory_names[:] = safe_directories
            for name in file_names:
                scanned += 1
                if scanned > entry.max_entries or time.time() >= deadline:
                    truncated = True
                    break
                path = current / name
                if query.casefold() not in name.casefold() or _is_reparse_or_symlink(path):
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    return _safe_failure(command, "search_root_escape")
                stat = resolved.stat()
                results.append(
                    {
                        "relative_path": resolved.relative_to(root).as_posix(),
                        "name": name,
                        "size_bytes": int(stat.st_size),
                        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    }
                )
                if len(results) >= max_results:
                    truncated = scanned < entry.max_entries
                    break
            if truncated or len(results) >= max_results:
                break
        return _success(
            command,
            {"root_id": root_id, "results": results, "truncated": truncated},
            {"root_containment": True, "metadata_only": True, "scanned_entries": scanned},
        )

    def _open_app(self, command: ToolCommand) -> CommandObservationFrame:
        app_id = str(command.arguments["app_id"])
        entry = self.allowlist.apps.get(app_id)
        if entry is None:
            return _safe_failure(command, "unknown_app_id")
        executable = Path(entry.executable)
        if not executable.is_file():
            return _safe_failure(command, "app_unavailable")
        process = subprocess.Popen(
            [str(executable), *entry.fixed_args],
            cwd=entry.working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        time.sleep(0.15)
        observed = process.poll() is None
        if not observed and process.returncode not in {0, None}:
            return _safe_failure(command, "app_dispatch_failed")
        return _success(
            command,
            {"app_id": app_id, "dispatched": True, "process_observed": observed},
            {"exact_allowlist_dispatch": True},
        )

    def _open_project(self, command: ToolCommand) -> CommandObservationFrame:
        project_id = str(command.arguments["project_id"])
        entry = self.allowlist.projects.get(project_id)
        if entry is None:
            return _safe_failure(command, "unknown_project_id")
        executable = Path(entry.executable)
        project = Path(entry.project_directory).resolve(strict=True)
        if not executable.is_file() or not project.is_dir() or _is_reparse_or_symlink(project):
            return _safe_failure(command, "project_unavailable")
        process = subprocess.Popen(
            [str(executable), *entry.fixed_args, str(project)],
            cwd=entry.working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        time.sleep(0.15)
        if process.poll() not in {None, 0}:
            return _safe_failure(command, "project_dispatch_failed")
        return _success(
            command,
            {"project_id": project_id, "dispatched": True, "target_verified": True},
            {"exact_allowlist_dispatch": True, "gui_render_claimed": False},
        )

    def _volume_command(self, action: str, value: int | None = None) -> int:
        if os.name != "nt" or not self.volume_script.is_file():
            raise OSError("volume control unavailable")
        executable = (
            Path(os.environ.get("WINDIR", "C:\\Windows"))
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        arguments = [
            str(executable),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(self.volume_script),
            "-Action",
            action,
        ]
        if value is not None:
            arguments.extend(["-Value", str(value)])
        completed = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise OSError("volume command failed")
        measured = int(completed.stdout.strip())
        if not 0 <= measured <= 100:
            raise ValueError("volume readback invalid")
        return measured

    def _volume_get(self, command: ToolCommand) -> CommandObservationFrame:
        measured = self._volume_command("Get")
        return _success(command, {"volume": measured}, {"measured_readback": True})

    def _volume_set(self, command: ToolCommand) -> CommandObservationFrame:
        requested = int(command.arguments["volume"])
        measured = self._volume_command("Set", requested)
        if abs(measured - requested) > 1:
            return _safe_failure(command, "volume_readback_mismatch")
        return _success(
            command,
            {"requested_volume": requested, "measured_volume": measured},
            {"measured_readback": True, "tolerance_percent": 1},
        )

    def _workflow(self, command: ToolCommand) -> CommandObservationFrame:
        workflow_id = str(command.arguments["workflow_id"])
        entry = self.allowlist.workflows.get(workflow_id)
        if entry is None:
            return _safe_failure(command, "unknown_workflow_id")
        if not self._workflow_targets_available(entry):
            return _safe_failure(command, "workflow_unavailable")
        owned = self.process_registry.create(
            command.command_id,
            allow_hard_stop=entry.allow_hard_stop,
        )
        try:
            owned.process = subprocess.Popen(
                [entry.executable, entry.script, *entry.fixed_args],
                cwd=entry.working_directory,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
            deadline = min(
                command.deadline_at.timestamp(),
                time.time() + min(entry.timeout_seconds, command.timeout_seconds),
            )
            while owned.process.poll() is None:
                if owned.cancel.is_set():
                    stopped = self._stop_owned_process(owned)
                    return CommandObservationFrame(
                        session_id=command.session_id,
                        command_id=command.command_id,
                        name=command.name,
                        version=command.version,
                        argument_digest=command.argument_digest,
                        status=(
                            ToolObservationStatus.CANCELLED
                            if stopped
                            else ToolObservationStatus.FAILED
                        ),
                        output={},
                        verification={"verified": stopped, "owned_process_stopped": stopped},
                        failure_code="cancelled" if stopped else "cancellation_failed",
                        observed_at=datetime.now(UTC),
                    )
                if time.time() >= deadline:
                    stopped = self._stop_owned_process(owned)
                    return _safe_failure(
                        command,
                        "workflow_timeout" if stopped else "workflow_timeout_uncertain",
                        uncertain=not stopped,
                    )
                time.sleep(0.1)
            exit_code = int(owned.process.returncode)
            marker = Path(entry.verification.path)
            verified = exit_code in entry.expected_exit_codes and marker.is_file()
            if not verified:
                return _safe_failure(command, "workflow_verification_failed")
            return _success(
                command,
                {
                    "workflow_id": workflow_id,
                    "exit_code": exit_code,
                    "verification_passed": True,
                },
                {"expected_exit_code": True, "marker_verified": True},
            )
        finally:
            self.process_registry.remove(command.command_id)

    @staticmethod
    def _workflow_targets_available(entry: WorkflowEntry) -> bool:
        return (
            Path(entry.executable).is_file()
            and Path(entry.script).is_file()
            and entry.working_directory is not None
            and Path(entry.working_directory).is_dir()
        )

    @staticmethod
    def _stop_owned_process(owned: _OwnedExecution) -> bool:
        process = owned.process
        if process is None:
            return True
        if process.poll() is not None:
            return True
        process.terminate()
        try:
            process.wait(timeout=3)
            return True
        except subprocess.TimeoutExpired:
            if not owned.allow_hard_stop:
                return False
            process.kill()
            try:
                process.wait(timeout=2)
                return True
            except subprocess.TimeoutExpired:
                return False


__all__ = ["OwnedProcessRegistry", "WindowsExecutionEngine"]
