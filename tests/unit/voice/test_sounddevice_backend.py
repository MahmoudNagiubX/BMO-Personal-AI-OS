from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from personal_ai_os.voice.contracts import AudioFrame
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


def test_raw_streams_avoid_sounddevice_duplicate_channel_context_bug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_streams = 0
    peak_active_streams = 0
    output_started = threading.Event()
    input_kwargs: dict[str, object] = {}
    output_kwargs: dict[str, object] = {}

    class FakeCallbackStop(Exception):
        pass

    class FakeInputStream:
        def __init__(self, **kwargs: object) -> None:
            input_kwargs.update(kwargs)
            self.callback = kwargs["callback"]
            self.active = False

        def start(self) -> None:
            nonlocal active_streams, peak_active_streams
            active_streams += 1
            peak_active_streams = max(peak_active_streams, active_streams)
            self.active = True
            self.callback(b"\x01\x00" * 1600, 1600, None, None)

        def stop(self) -> None:
            nonlocal active_streams
            if self.active:
                active_streams -= 1
            self.active = False

        def close(self) -> None:
            return None

    class FakeOutputStream:
        def __init__(self, **kwargs: object) -> None:
            output_kwargs.update(kwargs)
            self.callback = kwargs["callback"]
            self.active = False

        def start(self) -> None:
            nonlocal active_streams, peak_active_streams
            active_streams += 1
            peak_active_streams = max(peak_active_streams, active_streams)
            self.active = True
            output_started.set()
            time.sleep(0.05)
            try:
                self.callback(bytearray(3200), 1600, None, None)
            except FakeCallbackStop:
                self.active = False

        def stop(self) -> None:
            nonlocal active_streams
            if self.active:
                active_streams -= 1
            self.active = False

        def abort(self) -> None:
            self.stop()

        def close(self) -> None:
            return None

    class FakeSoundDevice:
        CallbackStop = FakeCallbackStop
        RawInputStream = FakeInputStream
        RawOutputStream = FakeOutputStream

        @staticmethod
        def rec(*_args: object, **_kwargs: object) -> None:
            raise TypeError(
                "_CallbackContext.start_stream() got multiple values for argument 'channels'"
            )

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
    playback_thread = threading.Thread(
        target=backend.play,
        args=((AudioFrame(b"\x01\x00" * 1600),),),
    )
    playback_thread.start()
    assert output_started.wait(timeout=1)
    captured = backend.capture(seconds=0.01)
    playback_thread.join(timeout=1)
    streamed: list[AudioFrame] = []
    backend.stream_input(streamed.append, seconds=0.01)

    expected = {"samplerate", "channels", "dtype", "device", "callback"}
    assert input_kwargs.keys() == expected
    assert output_kwargs.keys() == expected
    assert input_kwargs["channels"] == 1
    assert output_kwargs["channels"] == 1
    assert captured
    assert streamed
    assert peak_active_streams >= 2
    assert not playback_thread.is_alive()
