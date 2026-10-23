"""Typed descriptions of local DeskBot behavior responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Language = Literal["de", "en"]
Expression = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "surprised",
    "sleepy",
    "thinking",
    "curious",
    "skeptical",
    "excited",
    "love",
    "confused",
]
Action = Literal["blink", "nod", "head_tilt", "sneeze_animation", "laugh"]
EventType = Literal[
    "greet_known",
    "greet_unknown",
    "head_tap",
    "sneeze",
    "joke_offer",
    "joke_answer",
    "boss_absent",
    "boss_present",
    "idle_reaction",
]


@dataclass(frozen=True, slots=True)
class BehaviorResponse:
    """A response suggestion; a caller decides whether and how to play it."""

    text: str | None
    language: Language
    expression: Expression
    action: Action | None
    event_type: EventType
    response_id: str
    error: str | None = None
