from __future__ import annotations

from personal_ai_os.voice.adapters import installed_version


def test_optional_voice_inventory_is_scalar_and_non_secret() -> None:
    assert installed_version("package-that-does-not-exist-for-bmo") is None
