from __future__ import annotations

from types import SimpleNamespace

import numpy

from personal_ai_os.voice.contracts import AudioFrame, TurnDecision
from personal_ai_os.voice.pipecat_adapter import LocalSmartTurnDetector


def test_smart_turn_prediction_is_product_owned_and_scalar(monkeypatch) -> None:
    class Analyzer:
        def __init__(self, **kwargs) -> None:
            self._log_data = True

        def _predict_endpoint(self, samples):
            assert isinstance(samples, numpy.ndarray)
            assert samples.dtype == numpy.float32
            return {"prediction": 1}

    monkeypatch.setattr(
        "personal_ai_os.voice.pipecat_adapter.importlib.import_module",
        lambda name: (
            SimpleNamespace(LocalSmartTurnAnalyzerV3=Analyzer)
            if name == "pipecat.audio.turn.smart_turn.local_smart_turn_v3"
            else numpy
        ),
    )
    detector = LocalSmartTurnDetector()
    decision = detector.decide((AudioFrame(b"\x00\x00" * 160),), silence_seconds=0.2)
    assert detector.available is True
    assert decision is TurnDecision.COMPLETE


def test_smart_turn_falls_back_after_dependency_failure(monkeypatch) -> None:
    def fail(_name: str):
        raise ImportError("synthetic missing dependency")

    monkeypatch.setattr("personal_ai_os.voice.pipecat_adapter.importlib.import_module", fail)
    detector = LocalSmartTurnDetector(fallback_timeout_seconds=1.0)
    frame = AudioFrame(b"\x00\x00" * 160)
    assert detector.available is False
    assert detector.decide((frame,), silence_seconds=0.5) is TurnDecision.INCOMPLETE
    assert detector.decide((frame,), silence_seconds=1.0) is TurnDecision.FALLBACK_COMPLETE
