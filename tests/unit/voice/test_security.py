from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_voice_path_has_no_direct_model_or_shell_authority() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/personal_ai_os/voice").rglob("*.py")
    )
    assert "personal_ai_os.model_gateway" not in source
    assert "subprocess" not in source
    assert "powershell" not in source.casefold()
    assert "ollama" not in source.casefold()


def test_voice_docs_and_code_keep_audio_in_memory_only() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/personal_ai_os/voice").rglob("*.py")
    )
    assert "open(" not in source
    assert "write_bytes" not in source
    assert "write_text" not in source
