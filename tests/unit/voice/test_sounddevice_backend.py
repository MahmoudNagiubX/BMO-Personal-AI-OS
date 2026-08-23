from __future__ import annotations

from types import SimpleNamespace

import pytest

from personal_ai_os.voice.sounddevice_backend import SoundDeviceBackend


def test_backend_reports_selected_input_and_output_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSoundDevice:
        @staticmethod
        def query_devices(_selector: object, kind: str) -> dict[str, object]:
            if kind == "input":
                return {"name": "TUF Microphone", "max_input_channels": 1}
            return {"name": "TUF Headphones", "max_output_channels": 2}

    monkeypatch.setattr(
        "personal_ai_os.voice.sounddevice_backend.importlib.import_module",
        lambda name: FakeSoundDevice if name == "sounddevice" else SimpleNamespace(),
    )

    backend = SoundDeviceBackend(input_device=3, output_device=4)

    assert backend.input_device_name == "TUF Microphone"
    assert backend.output_device_name == "TUF Headphones"
    assert backend.input_device == 3
    assert backend.output_device == 4


def test_backend_rejects_device_without_input_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSoundDevice:
        @staticmethod
        def query_devices(_selector: object, kind: str) -> dict[str, object]:
            if kind == "input":
                return {"name": "Playback Only", "max_input_channels": 0}
            return {"name": "TUF Headphones", "max_output_channels": 2}

    monkeypatch.setattr(
        "personal_ai_os.voice.sounddevice_backend.importlib.import_module",
        lambda name: FakeSoundDevice if name == "sounddevice" else SimpleNamespace(),
    )

    with pytest.raises(RuntimeError, match="no input channel"):
        SoundDeviceBackend()
