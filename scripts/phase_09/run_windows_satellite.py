"""Run the reviewed per-user Windows satellite with bounded rotating logs."""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler

from personal_ai_os.satellites.windows.agent import WindowsSatelliteAgent
from personal_ai_os.satellites.windows.allowlist import WindowsAllowlist
from personal_ai_os.satellites.windows.config import WindowsSatelliteSettings
from personal_ai_os.satellites.windows.credentials import WindowsCredentialStore
from personal_ai_os.satellites.windows.execution import WindowsExecutionEngine
from personal_ai_os.satellites.windows.replay import ReplayJournal


def main() -> None:
    settings = WindowsSatelliteSettings()  # type: ignore[call-arg]
    settings.state_root.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bmo.windows_satellite")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        settings.state_root / "satellite.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter('{"level":"%(levelname)s","message":"%(message)s"}'))
    logger.addHandler(handler)
    allowlist = WindowsAllowlist.load(settings.allowlist_path)
    agent = WindowsSatelliteAgent(
        settings,
        WindowsCredentialStore(),
        WindowsExecutionEngine(allowlist),
        ReplayJournal(settings.state_root / "replay.json"),
        logger=logger,
    )
    try:
        asyncio.run(agent.run_forever())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
