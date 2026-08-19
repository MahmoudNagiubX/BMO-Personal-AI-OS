"""Derive the VENOM stability-gate state from real timestamps and samples."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

GateState = Literal["WAITING_FOR_24H", "WAITING_FOR_7D", "BLOCKED", "PASS"]

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
SAMPLE_INTERVAL_SECONDS = 15 * 60
# The root timer has a 15-minute cadence and AccuracySec=1min. Thirty-one
# minutes permits one delayed nominal interval but rejects a missed cycle.
MAX_SAMPLE_GAP_SECONDS = 31 * 60
DAY_SECONDS = 24 * 60 * 60
WEEK_SECONDS = 7 * DAY_SECONDS
MIN_COVERAGE_RATIO = 0.75
MIN_SAMPLE_COUNT = 4
# A 4 GiB host can retain a small amount of cold memory in swap. Treat only
# three consecutive samples at or above 256 MiB as sustained swap pressure.
SWAP_PRESSURE_THRESHOLD_BYTES = 256 * 1024 * 1024
SWAP_PRESSURE_CONSECUTIVE_SAMPLES = 3

REQUIRED_SAMPLE_FIELDS = frozenset(
    {
        "timestamp_utc",
        "boot_id",
        "failed_units",
        "smart_status",
        "smart_reallocated_sectors",
        "smart_pending_sectors",
        "smart_offline_uncorrectable_sectors",
        "ssh_active",
        "ufw_active",
        "reboot_detected",
        "missing_sample",
        "thermal_status",
        "disk_status",
        "swap_used_bytes",
        "ethernet_link",
        "default_route_interface",
        "network_status",
    }
)


@dataclass(frozen=True)
class StabilityResult:
    """Deterministic evaluator output; it never mutates evidence."""

    state: GateState
    reasons: tuple[str, ...]
    official_sample_count: int
    minimum_sample_count: int


@dataclass(frozen=True)
class Sample:
    timestamp: datetime
    values: Mapping[str, str]


def parse_utc_timestamp(value: str) -> datetime:
    """Parse the exact sanitized UTC timestamp format used by VENOM."""

    if not value.endswith("Z"):
        raise ValueError("timestamp must end with Z")
    return datetime.strptime(value, UTC_FORMAT).replace(tzinfo=UTC)


def _blocked(reason: str, sample_count: int = 0, minimum_count: int = 0) -> StabilityResult:
    return StabilityResult("BLOCKED", (reason,), sample_count, minimum_count)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _immediate_prerequisite_error(evidence: Mapping[str, object]) -> str | None:
    acceptance = _mapping(evidence.get("acceptance"))
    monitor = _mapping(evidence.get("stability_monitor"))
    backup = _mapping(evidence.get("backup_restore"))
    reboot = _mapping(evidence.get("reboot_recovery"))
    if acceptance is None:
        return "acceptance evidence is missing"
    if any(acceptance.get(field) != "PASS" for field in ("thermal", "memory", "ssh_key")):
        return "immediate thermal, memory, or SSH acceptance is incomplete"
    if acceptance.get("phase_5b") != "NOT_STARTED":
        return "Phase 5B must remain NOT_STARTED"
    if backup is None or backup.get("status") != "PASS" or backup.get("restore_proof") != "PASS":
        return "encrypted backup and restore proof are incomplete"
    if (
        reboot is None
        or reboot.get("status") != "PASS"
        or reboot.get("recovery_verified") is not True
    ):
        return "controlled reboot recovery is incomplete"
    if (
        monitor is None
        or monitor.get("system_timer") != "active"
        or monitor.get("durable_monitoring") is not True
    ):
        return "durable root monitoring is incomplete"
    return None


def _read_marker(path: Path) -> tuple[datetime, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    timestamp_text = values.get("gate_start_timestamp_utc")
    boot_id = values.get("initial_boot_id")
    if timestamp_text is None or boot_id is None or not boot_id:
        raise ValueError("official marker is missing timestamp or boot ID")
    if values.get("marker_status") != "OFFICIAL_REAL_TIME_GATE":
        raise ValueError("marker is not official")
    return parse_utc_timestamp(timestamp_text), boot_id


def _read_samples(path: Path, now: datetime) -> tuple[Sample, ...]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError("stability CSV is empty") from exc
        missing_fields = REQUIRED_SAMPLE_FIELDS.difference(header)
        if missing_fields:
            raise ValueError(f"stability CSV is missing fields: {sorted(missing_fields)}")
        samples: list[Sample] = []
        for line_number, values in enumerate(reader, start=2):
            if len(values) != len(header):
                raise ValueError(f"stability CSV row {line_number} has the wrong column count")
            row = dict(zip(header, values, strict=True))
            timestamp = parse_utc_timestamp(row["timestamp_utc"])
            if timestamp > now:
                raise ValueError(f"stability CSV row {line_number} is in the future")
            samples.append(Sample(timestamp, row))
    return tuple(samples)


def _nonnegative_int(row: Mapping[str, str], field: str) -> int:
    value = row.get(field, "")
    if not value.isdigit():
        raise ValueError(f"sample field {field} is not a non-negative integer")
    return int(value)


def _validate_sample_health(samples: tuple[Sample, ...], expected_boot_id: str) -> str | None:
    swap_pressure_run = 0
    previous_timestamp: datetime | None = None
    for sample in samples:
        row = sample.values
        if previous_timestamp is not None and sample.timestamp <= previous_timestamp:
            return "official sample timestamps are not strictly monotonic"
        previous_timestamp = sample.timestamp
        if row.get("boot_id") != expected_boot_id or row.get("reboot_detected") != "0":
            return "unexpected boot ID change or reboot flag during the official gate"
        if row.get("missing_sample") != "0":
            return "missing sample flag during the official gate"
        if row.get("thermal_status") != "pass":
            return "thermal breach during the official gate"
        if row.get("disk_status") != "pass":
            return "root-disk breach during the official gate"
        if (
            row.get("ethernet_link") != "up"
            or row.get("default_route_interface") != "enp7s0"
            or row.get("network_status") != "up"
        ):
            return "Ethernet/default-route health failed the control-plane policy"
        if row.get("ssh_active") != "active":
            return "SSH service was not active during the official gate"
        if row.get("ufw_active") != "active":
            return "UFW was not active during the official gate"
        if row.get("smart_status") != "passed":
            return "SMART health was not passed during the official gate"
        for field in (
            "smart_reallocated_sectors",
            "smart_pending_sectors",
            "smart_offline_uncorrectable_sectors",
        ):
            if _nonnegative_int(row, field) != 0:
                return f"SMART sector counter {field} exceeded the accepted zero baseline"
        if _nonnegative_int(row, "failed_units") != 0:
            return "a failed system unit was recorded during the official gate"
        swap_used_bytes = _nonnegative_int(row, "swap_used_bytes")
        if swap_used_bytes >= SWAP_PRESSURE_THRESHOLD_BYTES:
            swap_pressure_run += 1
            if swap_pressure_run >= SWAP_PRESSURE_CONSECUTIVE_SAMPLES:
                return "sustained high swap pressure indicates swap thrashing"
        else:
            swap_pressure_run = 0
    return None


def _continuity_error(
    samples: tuple[Sample, ...], marker_timestamp: datetime, current_time: datetime
) -> str | None:
    """Reject acceptance windows with unobserved leading, internal, or trailing gaps."""

    if not samples:
        return "official monitoring did not produce a sample"
    leading_gap = (samples[0].timestamp - marker_timestamp).total_seconds()
    if leading_gap > MAX_SAMPLE_GAP_SECONDS:
        return "official monitoring did not begin close enough to the gate marker"
    previous_sample = samples[0]
    for sample in samples[1:]:
        if (sample.timestamp - previous_sample.timestamp).total_seconds() > MAX_SAMPLE_GAP_SECONDS:
            return "official sample continuity gap exceeded tolerance"
        previous_sample = sample
    trailing_gap = (current_time - samples[-1].timestamp).total_seconds()
    if trailing_gap > MAX_SAMPLE_GAP_SECONDS:
        return "official monitoring is stale at evaluation time"
    return None


def _minimum_samples(elapsed_seconds: int) -> int:
    window = WEEK_SECONDS if elapsed_seconds >= WEEK_SECONDS else DAY_SECONDS
    expected = math.ceil(window / SAMPLE_INTERVAL_SECONDS) + 1
    return max(MIN_SAMPLE_COUNT, math.ceil(expected * MIN_COVERAGE_RATIO))


def evaluate_stability_gate(
    evidence_path: Path,
    marker_path: Path,
    samples_path: Path,
    now: datetime | None = None,
) -> StabilityResult:
    """Evaluate a gate without trusting or mutating status strings."""

    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        raise ValueError("now must be timezone-aware UTC")
    current_time = current_time.astimezone(UTC)
    sample_count = 0
    minimum_count = 0
    try:
        evidence_value = json.loads(evidence_path.read_text(encoding="utf-8"))
        if not isinstance(evidence_value, Mapping):
            return _blocked("physical-gate evidence is not an object")
        immediate_error = _immediate_prerequisite_error(evidence_value)
        if immediate_error is not None:
            return _blocked(immediate_error)
        marker_timestamp, marker_boot_id = _read_marker(marker_path)
        if marker_timestamp > current_time:
            return _blocked("official gate marker is in the future")
        all_samples = _read_samples(samples_path, current_time)
        official_samples = tuple(
            sample for sample in all_samples if sample.timestamp >= marker_timestamp
        )
        sample_count = len(official_samples)
        health_error = _validate_sample_health(official_samples, marker_boot_id)
        if health_error is not None:
            return _blocked(health_error, sample_count, _minimum_samples(0))

        elapsed_seconds = int((current_time - marker_timestamp).total_seconds())
        minimum_count = _minimum_samples(elapsed_seconds)
        if elapsed_seconds >= DAY_SECONDS:
            continuity_error = _continuity_error(official_samples, marker_timestamp, current_time)
            if continuity_error is not None:
                return _blocked(continuity_error, sample_count, minimum_count)
            if sample_count < minimum_count:
                return _blocked(
                    "official sample coverage is below the documented 75% minimum",
                    sample_count,
                    minimum_count,
                )
        if elapsed_seconds < DAY_SECONDS:
            return StabilityResult(
                "WAITING_FOR_24H",
                ("24 real hours have not elapsed",),
                sample_count,
                minimum_count,
            )
        if elapsed_seconds < WEEK_SECONDS:
            return StabilityResult(
                "WAITING_FOR_7D",
                ("7 real days have not elapsed",),
                sample_count,
                minimum_count,
            )
        return StabilityResult(
            "PASS",
            ("24-hour and 7-day real-time gates elapsed",),
            sample_count,
            minimum_count,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _blocked(str(exc), sample_count, minimum_count)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--marker", required=True, type=Path)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument(
        "--now",
        type=str,
        help="UTC timestamp for deterministic tests only; production uses current UTC",
    )
    args = parser.parse_args()
    now = parse_utc_timestamp(args.now) if args.now else None
    result = evaluate_stability_gate(args.evidence, args.marker, args.samples, now)
    print(f"STATE={result.state}")
    print(f"OFFICIAL_SAMPLE_COUNT={result.official_sample_count}")
    print(f"MINIMUM_SAMPLE_COUNT={result.minimum_sample_count}")
    for reason in result.reasons:
        print(f"REASON={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
