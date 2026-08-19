from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.phase_01.evaluate_stability_gate import (
    DAY_SECONDS,
    MAX_SAMPLE_GAP_SECONDS,
    SWAP_PRESSURE_THRESHOLD_BYTES,
    WEEK_SECONDS,
    evaluate_stability_gate,
)

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "infrastructure/home_server/evidence/venom_physical_gate.json"
START = datetime(2026, 1, 1, tzinfo=UTC)
BOOT_ID = "official-test-boot"
CSV_FIELDS = [
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
]


def timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def valid_row(at: datetime, **overrides: str) -> dict[str, str]:
    row = {
        "timestamp_utc": timestamp(at),
        "boot_id": BOOT_ID,
        "failed_units": "0",
        "smart_status": "passed",
        "smart_reallocated_sectors": "0",
        "smart_pending_sectors": "0",
        "smart_offline_uncorrectable_sectors": "0",
        "ssh_active": "active",
        "ufw_active": "active",
        "reboot_detected": "0",
        "missing_sample": "0",
        "thermal_status": "pass",
        "disk_status": "pass",
        "swap_used_bytes": "0",
        "ethernet_link": "up",
        "default_route_interface": "enp7s0",
        "network_status": "up",
    }
    row.update(overrides)
    return row


def regular_rows(duration_seconds: int, start_seconds: int = 0) -> list[dict[str, str]]:
    return [
        valid_row(START + timedelta(seconds=step))
        for step in range(start_seconds, duration_seconds + 1, 15 * 60)
    ]


def write_fixture(
    tmp_path: Path,
    rows: list[dict[str, str]],
    now: datetime,
    evidence_update: dict[str, object] | None = None,
) -> object:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    if evidence_update:
        evidence.update(evidence_update)
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    marker_path = tmp_path / "gate-start.env"
    marker_path.write_text(
        "gate_start_timestamp_utc="
        + timestamp(START)
        + f"\ninitial_boot_id={BOOT_ID}\nmarker_status=OFFICIAL_REAL_TIME_GATE\n",
        encoding="utf-8",
    )
    samples_path = tmp_path / "stability.csv"
    with samples_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return evaluate_stability_gate(evidence_path, marker_path, samples_path, now)


def test_evaluator_waits_before_24_real_hours(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)

    result = write_fixture(tmp_path, regular_rows(23 * 60 * 60), now)

    assert result.state == "WAITING_FOR_24H"


def test_two_row_fabricated_file_cannot_pass(tmp_path: Path) -> None:
    now = START + timedelta(seconds=WEEK_SECONDS)
    rows = [valid_row(START), valid_row(now)]

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"


def test_late_first_sample_cannot_transition_at_24h(tmp_path: Path) -> None:
    now = START + timedelta(seconds=DAY_SECONDS)
    rows = regular_rows(DAY_SECONDS, start_seconds=6 * 60 * 60)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "did not begin" in result.reasons[0]


def test_first_sample_within_normal_cadence_can_transition_at_24h(tmp_path: Path) -> None:
    now = START + timedelta(seconds=DAY_SECONDS)
    rows = regular_rows(DAY_SECONDS, start_seconds=15 * 60)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "WAITING_FOR_7D"


def test_internal_timestamp_gap_blocks_even_when_monitor_flag_is_clear(tmp_path: Path) -> None:
    now = START + timedelta(seconds=DAY_SECONDS)
    rows = regular_rows(DAY_SECONDS)
    del rows[40:43]

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "continuity gap" in result.reasons[0]


def test_stale_final_sample_blocks_at_24h(tmp_path: Path) -> None:
    now = START + timedelta(seconds=DAY_SECONDS)
    rows = regular_rows(23 * 60 * 60)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "stale" in result.reasons[0]


def test_stale_final_sample_blocks_at_7d(tmp_path: Path) -> None:
    now = START + timedelta(seconds=WEEK_SECONDS)
    rows = regular_rows(6 * DAY_SECONDS)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "stale" in result.reasons[0]


def test_concentrated_week_coverage_cannot_pass(tmp_path: Path) -> None:
    now = START + timedelta(seconds=WEEK_SECONDS)
    rows = regular_rows(int(WEEK_SECONDS * 0.75))

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "stale" in result.reasons[0]


def test_concentrated_end_of_day_coverage_cannot_transition(tmp_path: Path) -> None:
    now = START + timedelta(seconds=DAY_SECONDS)
    rows = regular_rows(DAY_SECONDS, start_seconds=6 * 60 * 60)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "did not begin" in result.reasons[0]


def test_future_marker_is_blocked(tmp_path: Path) -> None:
    now = START
    result = write_fixture(tmp_path, [valid_row(START)], now)
    marker = tmp_path / "gate-start.env"
    marker.write_text(
        "gate_start_timestamp_utc=2026-01-02T00:00:00Z\n"
        "initial_boot_id=official-test-boot\n"
        "marker_status=OFFICIAL_REAL_TIME_GATE\n",
        encoding="utf-8",
    )

    assert result.state == "WAITING_FOR_24H"
    result = evaluate_stability_gate(
        tmp_path / "evidence.json", marker, tmp_path / "stability.csv", now
    )
    assert result.state == "BLOCKED"


def test_future_sample_is_blocked(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    rows[-1]["timestamp_utc"] = timestamp(now + timedelta(seconds=1))

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "future" in result.reasons[0]


def test_malformed_sample_timestamp_is_blocked(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    rows[2]["timestamp_utc"] = "not-a-timestamp"

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "timestamp" in result.reasons[0]


def test_non_monotonic_official_samples_are_blocked(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    rows[3]["timestamp_utc"] = rows[2]["timestamp_utc"]

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "monotonic" in result.reasons[0]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("reboot_detected", "1", "reboot"),
        ("missing_sample", "1", "missing sample"),
        ("thermal_status", "breach", "thermal"),
        ("disk_status", "breach", "root-disk"),
        ("failed_units", "1", "failed system unit"),
        ("ethernet_link", "down", "Ethernet"),
        ("default_route_interface", "wlp4s0", "Ethernet"),
        ("network_status", "degraded", "Ethernet"),
        ("ssh_active", "inactive", "SSH"),
        ("ufw_active", "inactive", "UFW"),
        ("smart_status", "not_passed_or_unavailable", "SMART"),
    ],
)
def test_health_failures_block(tmp_path: Path, field: str, value: str, reason: str) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    rows[4][field] = value

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert reason in result.reasons[0]


@pytest.mark.parametrize(
    "field",
    [
        "smart_reallocated_sectors",
        "smart_pending_sectors",
        "smart_offline_uncorrectable_sectors",
    ],
)
def test_any_smart_sector_counter_blocks(tmp_path: Path, field: str) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    rows[4][field] = "1"

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "SMART sector counter" in result.reasons[0]


def test_pre_official_samples_do_not_count(tmp_path: Path) -> None:
    now = START + timedelta(seconds=WEEK_SECONDS)
    rows = [
        valid_row(START - timedelta(minutes=30), boot_id="old-boot"),
        valid_row(START - timedelta(minutes=15), boot_id="old-boot"),
        valid_row(START),
        valid_row(START + timedelta(minutes=15)),
    ]

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"


def test_small_stable_residual_swap_does_not_block(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    for row in rows:
        row["swap_used_bytes"] = str(1024 * 1024)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "WAITING_FOR_24H"


def test_one_transient_meaningful_swap_sample_does_not_block(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    rows[4]["swap_used_bytes"] = str(SWAP_PRESSURE_THRESHOLD_BYTES)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "WAITING_FOR_24H"


def test_sustained_high_swap_pressure_blocks(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    for index in (4, 5, 6):
        rows[index]["swap_used_bytes"] = str(SWAP_PRESSURE_THRESHOLD_BYTES)

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "swap pressure" in result.reasons[0]


def test_malformed_numeric_sample_data_is_blocked_not_raised(tmp_path: Path) -> None:
    now = START + timedelta(hours=23)
    rows = regular_rows(23 * 60 * 60)
    rows[4]["swap_used_bytes"] = "not-a-number"

    result = write_fixture(tmp_path, rows, now)

    assert result.state == "BLOCKED"
    assert "not a non-negative integer" in result.reasons[0]


def test_evaluator_reaches_waiting_for_7d_after_valid_24h(tmp_path: Path) -> None:
    now = START + timedelta(seconds=DAY_SECONDS + 3600)

    result = write_fixture(tmp_path, regular_rows(DAY_SECONDS + 3600), now)

    assert result.state == "WAITING_FOR_7D"


def test_evaluator_cannot_pass_before_seven_real_days(tmp_path: Path) -> None:
    now = START + timedelta(days=6, hours=23)

    result = write_fixture(tmp_path, regular_rows((6 * 24 * 60 * 60) + (23 * 60 * 60)), now)

    assert result.state == "WAITING_FOR_7D"


def test_evaluator_passes_after_seven_real_days(tmp_path: Path) -> None:
    now = START + timedelta(seconds=WEEK_SECONDS)

    result = write_fixture(tmp_path, regular_rows(WEEK_SECONDS), now)

    assert result.state == "PASS"


def test_continuity_tolerance_matches_documented_timer_policy() -> None:
    assert MAX_SAMPLE_GAP_SECONDS == 31 * 60
