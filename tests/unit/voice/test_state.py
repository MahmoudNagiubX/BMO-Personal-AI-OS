from __future__ import annotations

import pytest

from personal_ai_os.voice.contracts import VoiceState
from personal_ai_os.voice.state import InvalidVoiceTransition, VoiceEvent, VoiceStateMachine


def test_hands_free_state_path_and_follow_up_timeout() -> None:
    machine = VoiceStateMachine()
    for event in (
        VoiceEvent.WAKE_WORD,
        VoiceEvent.WAKE_READY,
        VoiceEvent.SPEECH_START,
        VoiceEvent.SPEECH_END,
        VoiceEvent.TRANSCRIPT_READY,
        VoiceEvent.CORE_SUBMITTED,
        VoiceEvent.RESPONSE_READY,
        VoiceEvent.FOLLOW_UP_READY,
        VoiceEvent.FOLLOW_UP_SILENCE,
    ):
        machine.transition(event)
    assert machine.state is VoiceState.SLEEPING


def test_barge_in_has_explicit_interrupted_state_and_recovery() -> None:
    machine = VoiceStateMachine(VoiceState.SPEAKING)
    assert machine.transition(VoiceEvent.BARGE_IN) is VoiceState.INTERRUPTED
    assert machine.transition(VoiceEvent.INTERRUPTION_READY) is VoiceState.LISTENING


def test_illegal_transition_is_rejected() -> None:
    with pytest.raises(InvalidVoiceTransition):
        VoiceStateMachine().transition(VoiceEvent.SPEECH_START)


def test_degraded_recovery_is_explicit() -> None:
    machine = VoiceStateMachine(VoiceState.WAITING_FOR_RESPONSE)
    assert machine.degrade() is VoiceState.DEGRADED
    assert machine.recover() is VoiceState.SLEEPING
