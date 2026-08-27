"""Optional Pipecat coordination boundary without leaking framework types."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any

from personal_ai_os.voice.adapters import installed_version
from personal_ai_os.voice.contracts import AudioFrame, TurnDecision, TurnDetector


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

    def turn_detector(
        self, *, fallback_timeout_seconds: float = 2.5, model_path: str | None = None
    ) -> TurnDetector:
        return LocalSmartTurnDetector(
            fallback_timeout_seconds=fallback_timeout_seconds,
            model_path=model_path,
        )


class LocalSmartTurnDetector:
    """Product-owned synchronous boundary for Pipecat Smart Turn v3.x.

    Pipecat's analyzer is used only for end-of-turn classification. VAD and a
    bounded deterministic timeout remain authoritative for safety and liveness.
    """

    def __init__(self, *, fallback_timeout_seconds: float = 2.5, model_path: str | None = None):
        if fallback_timeout_seconds <= 0:
            raise ValueError("Smart Turn fallback timeout must be positive")
        self.fallback_timeout_seconds = fallback_timeout_seconds
        self.available = False
        self.version = installed_version("pipecat-ai")
        self._analyzer: Any | None = None
        try:
            module = importlib.import_module("pipecat.audio.turn.smart_turn.local_smart_turn_v3")
            analyzer_type = module.__dict__["LocalSmartTurnAnalyzerV3"]
            self._analyzer = analyzer_type(smart_turn_model_path=model_path, cpu_count=1)
            # The upstream analyzer has an optional debug audio writer. Product
            # privacy is fail-closed even if an owner environment variable is set.
            if hasattr(self._analyzer, "_log_data"):
                self._analyzer._log_data = False
            self.available = True
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            self._analyzer = None

    def decide(
        self,
        frames: Sequence[AudioFrame],
        *,
        silence_seconds: float,
    ) -> TurnDecision:
        if not frames or silence_seconds <= 0:
            return TurnDecision.INCOMPLETE
        if self._analyzer is None:
            return (
                TurnDecision.FALLBACK_COMPLETE
                if silence_seconds >= self.fallback_timeout_seconds
                else TurnDecision.INCOMPLETE
            )
        try:
            numpy = importlib.import_module("numpy")
            pcm = b"".join(frame.pcm_s16le for frame in frames)
            samples = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32) / 32768.0
            result = self._analyzer._predict_endpoint(samples)
            if isinstance(result, dict) and int(result.get("prediction", 0)) == 1:
                return TurnDecision.COMPLETE
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            self.available = False
        return (
            TurnDecision.FALLBACK_COMPLETE
            if silence_seconds >= self.fallback_timeout_seconds
            else TurnDecision.INCOMPLETE
        )


__all__ = ["LocalSmartTurnDetector", "PipecatUnavailable", "PipecatVoiceCoordinator"]
