"""Optional Pipecat coordination boundary without leaking framework types."""

from __future__ import annotations

from personal_ai_os.voice.adapters import installed_version


class PipecatUnavailable(RuntimeError):
    """Pipecat is optional and cannot make the local product unavailable."""


class PipecatVoiceCoordinator:
    """Record/use Pipecat only as an internal coordinator behind product contracts."""

    distribution = "pipecat-ai"

    def __init__(self) -> None:
        version = installed_version(self.distribution)
        if version is None:
            raise PipecatUnavailable("pipecat-ai is not installed")
        self.version = version

    def healthy(self) -> bool:
        return True


__all__ = ["PipecatUnavailable", "PipecatVoiceCoordinator"]
