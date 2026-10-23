"""Debounced identity status and consent-gated owner greeting selection."""

from __future__ import annotations

import random
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from .content import PhraseCatalog, PhraseDataError
from .identity import IdentityResult
from .models import Expression, Language
from .registry import Person, PersonRegistry


class ChoiceSource(Protocol):
    def choice(self, values: Sequence[dict]) -> dict: ...


@dataclass(frozen=True, slots=True)
class OwnerGreeting:
    text: str
    expression: Expression
    response_id: str


class RecognitionRuntime:
    """Stabilize caller-supplied match results and greet only a configured owner.

    Similarity is exposed as a score, not a calibrated probability. This
    runtime never obtains frames, accesses sensors, or speaks by itself.
    """

    def __init__(
        self,
        registry: PersonRegistry | None,
        on_greeting: Callable[[OwnerGreeting], None],
        *,
        catalog: PhraseCatalog | None = None,
        chooser: ChoiceSource | None = None,
        clock: Callable[[], float] = time.monotonic,
        model_available: bool = False,
        enabled: bool = False,
        privacy_mode: bool = True,
        automatic_greetings: bool = False,
        stable_frames: int = 4,
        presence_reset_frames: int = 5,
        cooldown_seconds: int = 900,
    ) -> None:
        if not isinstance(stable_frames, int) or isinstance(stable_frames, bool) or stable_frames < 1:
            raise ValueError("stable_frames must be a positive integer")
        if not isinstance(presence_reset_frames, int) or isinstance(presence_reset_frames, bool) or presence_reset_frames < 1:
            raise ValueError("presence_reset_frames must be a positive integer")
        if not isinstance(cooldown_seconds, int) or isinstance(cooldown_seconds, bool) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be a non-negative integer")
        self.registry = registry
        self.on_greeting = on_greeting
        self.catalog = catalog or PhraseCatalog()
        self.chooser = chooser or random
        self.clock = clock
        self.model_available = model_available
        self.enabled = enabled
        self.privacy_mode = privacy_mode
        self.automatic_greetings = automatic_greetings
        self.stable_frames = stable_frames
        self.presence_reset_frames = presence_reset_frames
        self.cooldown_seconds = cooldown_seconds
        self._candidate_id: str | None = None
        self._candidate_count = 0
        self._unknown_count = 0
        self._stable_person: Person | None = None
        self._last_greeting_at: float | None = None
        self._recent_greetings: deque[str] = deque(maxlen=3)
        self._similarity_score: float | None = None
        self._reason = "disabled"
        self._unavailable_reason = "" if model_available else "model_missing"

    def update_settings(
        self,
        *,
        enabled: bool,
        privacy_mode: bool,
        automatic_greetings: bool,
    ) -> None:
        self.enabled = enabled
        self.privacy_mode = privacy_mode
        self.automatic_greetings = automatic_greetings
        if not enabled or privacy_mode:
            self._clear_presence()
            self._reason = "privacy_mode" if privacy_mode else "disabled"

    def set_unavailable(self, reason: str) -> None:
        """Fail closed if the local model or encrypted store becomes unavailable."""
        self.model_available = False
        self._unavailable_reason = reason
        self._reason = reason
        self._clear_presence()

    def set_available(self) -> None:
        self.model_available = True
        self._unavailable_reason = ""
        self._reason = "unknown"

    def process(self, result: IdentityResult) -> dict[str, object]:
        """Consume one per-frame identity result and return dashboard-safe status."""
        self._similarity_score = None
        if self.privacy_mode:
            self._reason = "privacy_mode"
            self._clear_presence()
            return self.status()
        if not self.enabled:
            self._reason = "disabled"
            self._clear_presence()
            return self.status()
        if not self.model_available:
            self._reason = self._unavailable_reason or "model_missing"
            self._clear_presence()
            return self.status()

        person = None
        if self.registry is not None and result.status == "recognized" and result.person_id is not None:
            person = self.registry.get_recognition_candidate(result.person_id)
        if person is None:
            self._reason = result.reason or "unknown"
            self._unknown_count += 1
            self._candidate_id = None
            self._candidate_count = 0
            if (
                self._stable_person is not None
                and (
                    self.registry is None
                    or self.registry.get_recognition_candidate(self._stable_person.person_id) is None
                )
            ):
                self._clear_presence()
                self._unknown_count = self.presence_reset_frames
            if self._unknown_count >= self.presence_reset_frames:
                self._stable_person = None
                self._similarity_score = result.confidence
            return self.status()

        self._reason = ""
        self._unknown_count = 0
        self._similarity_score = result.confidence
        if person.person_id == self._candidate_id:
            self._candidate_count += 1
        else:
            self._candidate_id = person.person_id
            self._candidate_count = 1
        if self._candidate_count < self.stable_frames:
            return self.status()

        previous_id = self._stable_person.person_id if self._stable_person else None
        self._stable_person = person
        if person.person_id != previous_id and self._is_configured_owner(person):
            self._maybe_greet_owner()
        return self.status()

    def status(self) -> dict[str, object]:
        if self.privacy_mode:
            current = "disabled"
        elif not self.enabled:
            current = "disabled"
        elif not self.model_available:
            current = "unavailable"
        elif self._stable_person is None:
            current = "unknown"
        else:
            current = "recognized"
        return {
            "enabled": self.enabled,
            "privacy_mode": self.privacy_mode,
            "model_available": self.model_available,
            "status": current,
            "display_name": self._stable_person.display_name if self._stable_person else "Unknown",
            "similarity_score": self._similarity_score,
            "reason": self._reason,
        }

    def _is_configured_owner(self, person: Person) -> bool:
        if self.registry is None:
            return False
        owner = self.registry.get_configured_owner()
        return owner is not None and owner.person_id == person.person_id and owner.role == "owner"

    def _maybe_greet_owner(self) -> None:
        if not self.automatic_greetings:
            return
        if self.registry is None:
            return
        owner = self.registry.get_configured_owner()
        if owner is None or not owner.personalized_greetings_enabled:
            return
        now = self.clock()
        if self._last_greeting_at is not None and now - self._last_greeting_at < self.cooldown_seconds:
            return
        try:
            entries = self.catalog.load(cast(Language, "de")).get("owner_greetings")
            if not isinstance(entries, list):
                raise PhraseDataError("German phrase file has no owner_greetings list")
            candidates = [entry for entry in entries if entry["id"] not in self._recent_greetings]
            if not candidates:
                raise PhraseDataError("no non-repeating owner greeting is available")
            selected = self.chooser.choice(candidates)
            greeting = OwnerGreeting(
                selected["text"],
                cast(Expression, selected["expression"]),
                selected["id"],
            )
        except (PhraseDataError, KeyError, TypeError) as exc:
            self._reason = f"greeting_content_unavailable: {exc}"
            return
        self._recent_greetings.append(greeting.response_id)
        self._last_greeting_at = now
        self.on_greeting(greeting)

    def _clear_presence(self) -> None:
        self._candidate_id = None
        self._candidate_count = 0
        self._unknown_count = 0
        self._stable_person = None
