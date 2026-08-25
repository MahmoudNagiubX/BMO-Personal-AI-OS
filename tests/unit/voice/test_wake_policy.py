from __future__ import annotations

from personal_ai_os.voice.wake_policy import WakeTemporalPolicy


def test_moving_max_policy_counts_one_long_high_score_as_one_event() -> None:
    policy = WakeTemporalPolicy(
        threshold=0.2,
        mode="moving_max",
        deactivation_threshold=0.05,
    )
    assert policy.stream_event_indices((0.0, 0.4, 0.5, 0.6, 0.01, 0.3)) == (1, 5)


def test_threshold_crossing_requires_bounded_hits() -> None:
    policy = WakeTemporalPolicy(
        threshold=0.5,
        required_hits=2,
        window_frames=3,
    )
    assert policy.accepts_window((0.6, 0.1, 0.7)) is True
    assert policy.accepts_window((0.6, 0.1, 0.2)) is False


def test_moving_average_is_distinct_from_single_frame_threshold() -> None:
    policy = WakeTemporalPolicy(
        threshold=0.5,
        mode="moving_average",
        window_frames=3,
    )
    assert policy.accepts_window((0.4, 0.5, 0.6)) is True
    assert policy.accepts_window((0.1, 0.2, 0.9)) is False
