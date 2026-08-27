"""Deterministic streaming wake temporal policies.

The model score is only a candidate signal.  This module owns the bounded
temporal decision, refractory behavior, and continuous-stream event counting
so benchmark and runtime semantics cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

WakePolicyMode = Literal["threshold_crossing", "moving_average", "moving_max"]


@dataclass(frozen=True, slots=True)
class WakeTemporalPolicy:
    """Bounded score policy for one streaming wake candidate."""

    threshold: float
    window_frames: int = 3
    required_hits: int = 1
    mode: WakePolicyMode = "threshold_crossing"
    deactivation_threshold: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("wake threshold must be between 0 and 1")
        if self.window_frames < 1:
            raise ValueError("wake window must be positive")
        if not 1 <= self.required_hits <= self.window_frames:
            raise ValueError("wake required hits must fit inside the window")
        if not 0.0 <= self.deactivation_threshold <= self.threshold:
            raise ValueError("wake deactivation threshold must fit below activation threshold")

    def accepts_window(self, scores: Sequence[float]) -> bool:
        """Return whether a bounded score history contains one activation."""

        if not scores:
            return False
        if self.mode == "moving_max":
            return max(scores[-self.window_frames :]) >= self.threshold
        if self.mode == "moving_average":
            window = scores[-self.window_frames :]
            return sum(window) / len(window) >= self.threshold
        window = scores[-self.window_frames :]
        return sum(score >= self.threshold for score in window) >= self.required_hits

    def stream_event_indices(self, scores: Sequence[float]) -> tuple[int, ...]:
        """Count distinct wake events in one continuous score stream.

        A high score arms one event and the detector stays disarmed until the
        score falls to the deactivation threshold.  This prevents one long
        high-score interval from being counted as many false wakes.
        """

        history: list[float] = []
        armed = True
        events: list[int] = []
        for index, score in enumerate(scores):
            bounded_score = min(1.0, max(0.0, float(score)))
            if not armed:
                if bounded_score <= self.deactivation_threshold:
                    armed = True
                    history.clear()
                continue
            history.append(bounded_score)
            if self.accepts_window(history):
                events.append(index)
                armed = False
                history.clear()
        return tuple(events)


__all__ = ["WakePolicyMode", "WakeTemporalPolicy"]
