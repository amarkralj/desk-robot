"""Explicit, deterministic scheduler for opt-in spontaneous DeskBot events.

The scheduler evaluates one supplied context at a time. It creates no thread,
loop, sensor access, or output side effect, and it never schedules greetings.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from math import isfinite
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .behaviors import ChoiceSource, boss_absent, idle_reaction, offer_joke, sneeze
from .models import BehaviorResponse, Language

ScheduledKind = Literal["sneeze_then_reaction", "smile_or_laugh", "joke_offer", "idle_expression"]


class SchedulerRandom(ChoiceSource, Protocol):
    """Random operations required by scheduling and phrase selection."""

    def uniform(self, a: float, b: float) -> float: ...


@dataclass(frozen=True, slots=True)
class SchedulerSettings:
    """Configurable local scheduling policy; times use the selected timezone."""

    active_start: time = time(8, 0)
    active_end: time = time(16, 0)
    quiet_start: time = time(16, 0)
    quiet_end: time = time(8, 0)
    min_interval_minutes: float = 45.0
    max_interval_minutes: float = 120.0
    max_events_per_day: int = 8
    quiet_mode: bool = False
    muted: bool = False
    joke_offers_enabled: bool = False
    idle_expressions_enabled: bool = True
    activity_quiet_minutes: float = 15.0
    timezone_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.active_start, time) or not isinstance(self.active_end, time):
            raise ValueError("active hours must be datetime.time values")
        if not isinstance(self.quiet_start, time) or not isinstance(self.quiet_end, time):
            raise ValueError("quiet hours must be datetime.time values")
        if self.active_start.tzinfo is not None or self.active_end.tzinfo is not None:
            raise ValueError("active hours must not include a timezone")
        if self.quiet_start.tzinfo is not None or self.quiet_end.tzinfo is not None:
            raise ValueError("quiet hours must not include a timezone")
        intervals = (self.min_interval_minutes, self.max_interval_minutes)
        if any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            for value in intervals
        ):
            raise ValueError("event intervals must be finite numbers")
        if self.min_interval_minutes <= 0 or self.max_interval_minutes < self.min_interval_minutes:
            raise ValueError("event intervals must be positive and maximum must be at least minimum")
        if isinstance(self.max_events_per_day, bool) or not isinstance(self.max_events_per_day, int):
            raise ValueError("max_events_per_day must be an integer")
        if self.max_events_per_day < 0:
            raise ValueError("max_events_per_day must not be negative")
        if (
            isinstance(self.activity_quiet_minutes, bool)
            or not isinstance(self.activity_quiet_minutes, (int, float))
            or not isfinite(self.activity_quiet_minutes)
        ):
            raise ValueError("activity_quiet_minutes must be a finite number")
        if self.activity_quiet_minutes < 0:
            raise ValueError("activity_quiet_minutes must not be negative")
        if self.timezone_name:
            try:
                ZoneInfo(self.timezone_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"unknown timezone: {self.timezone_name}") from exc


@dataclass(frozen=True, slots=True)
class SchedulerContext:
    """Current state only; `recent_activity_at` is supplied, never logged."""

    language: Language = "en"
    recent_activity_at: datetime | None = None
    known_person_nearby: bool = False
    owner_present: bool | None = None


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    """One event descriptor and ordered response descriptions for its handler."""

    kind: ScheduledKind | Literal["boss_absent"]
    occurred_at: datetime
    responses: tuple[BehaviorResponse, ...]


class Scheduler:
    """Evaluate at most one spontaneous event per call, with in-memory state."""

    def __init__(
        self,
        settings: SchedulerSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        rng: SchedulerRandom | None = None,
    ) -> None:
        self.settings = settings or SchedulerSettings()
        self._rng = rng or random.Random()
        self._clock = clock or self._local_now
        self._daily_date: date | None = None
        self._events_today = 0
        self._next_random_at: datetime | None = None
        self._last_event_at: datetime | None = None
        self._owner_present: bool | None = None

    def evaluate(self, now: datetime | None, context: SchedulerContext) -> ScheduledEvent | None:
        """Return one due event or ``None``; no internal loop or side effects.

        Pass an aware datetime for precise timezone behavior. Naive datetimes
        are interpreted in the scheduler's configured timezone (or local zone).
        Daily limits use the local calendar date, so DST and midnight are
        handled by ``zoneinfo`` rather than fixed 24-hour arithmetic.
        """
        current = self._normalize(now if now is not None else self._clock())
        local_now = current.astimezone(self._timezone())
        self._reset_daily_count(local_now.date())
        owner_transition = self._observe_owner(context.owner_present)

        if not self._allowed_now(local_now, context):
            return None
        if self._events_today >= self.settings.max_events_per_day:
            return None
        if not self._cooldown_elapsed(local_now):
            return None

        if owner_transition == "absent":
            return self._emit(
                "boss_absent",
                local_now,
                (boss_absent(context.language, chooser=self._rng),),
            )

        if self._next_random_at is None:
            self._next_random_at = local_now + self._random_interval()
            return None
        if local_now < self._next_random_at:
            return None

        kinds: list[ScheduledKind] = ["sneeze_then_reaction", "smile_or_laugh"]
        if self.settings.joke_offers_enabled and context.known_person_nearby:
            kinds.append("joke_offer")
        if self.settings.idle_expressions_enabled:
            kinds.append("idle_expression")
        kind = self._rng.choice(kinds)
        if kind == "sneeze_then_reaction":
            sneeze_response = sneeze(context.language, chooser=self._rng)
            reaction = BehaviorResponse(
                text=None,
                language=context.language,
                expression="happy",
                action="blink",
                event_type="idle_reaction",
                response_id="sneeze_afterglow",
            )
            responses = (sneeze_response, reaction)
        elif kind == "smile_or_laugh":
            action = self._rng.choice(("blink", "laugh"))
            response = BehaviorResponse(
                text=None,
                language=context.language,
                expression="happy",
                action=action,
                event_type="idle_reaction",
                response_id="spontaneous_smile" if action == "blink" else "spontaneous_laugh",
            )
            responses = (response,)
        elif kind == "joke_offer":
            responses = (offer_joke(context.language, chooser=self._rng),)
        else:
            idle = idle_reaction(context.language, chooser=self._rng)
            response = BehaviorResponse(
                text=None,
                language=idle.language,
                expression=idle.expression,
                action=None,
                event_type="idle_reaction",
                response_id=f"idle_expression_{idle.response_id}",
            )
            responses = (response,)
        return self._emit(kind, local_now, responses)

    def _timezone(self) -> tzinfo:
        if self.settings.timezone_name:
            return ZoneInfo(self.settings.timezone_name)
        return datetime.now().astimezone().tzinfo or timezone.utc

    def _normalize(self, value: datetime) -> datetime:
        zone = self._timezone()
        return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)

    def _local_now(self) -> datetime:
        return datetime.now(self._timezone())

    def _reset_daily_count(self, today: date) -> None:
        if self._daily_date is None or today > self._daily_date:
            self._daily_date = today
            self._events_today = 0

    def _observe_owner(self, owner_present: bool | None) -> str | None:
        if owner_present is None:
            return None
        previous = self._owner_present
        self._owner_present = owner_present
        if previous is True and owner_present is False:
            return "absent"
        return None

    def _allowed_now(self, now: datetime, context: SchedulerContext) -> bool:
        policy = self.settings
        if policy.quiet_mode or policy.muted or policy.max_events_per_day == 0:
            return False
        local_time = now.timetz().replace(tzinfo=None)
        if not self._within(local_time, policy.active_start, policy.active_end):
            return False
        if policy.quiet_start != policy.quiet_end and self._within(
            local_time, policy.quiet_start, policy.quiet_end
        ):
            return False
        if context.recent_activity_at is not None:
            activity_at = self._normalize(context.recent_activity_at)
            elapsed = now - activity_at
            if elapsed < timedelta(minutes=policy.activity_quiet_minutes):
                return False
        return True

    @staticmethod
    def _within(current: time, start: time, end: time) -> bool:
        if start == end:
            return True
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def _cooldown_elapsed(self, now: datetime) -> bool:
        if self._last_event_at is None:
            return True
        return now - self._last_event_at >= timedelta(minutes=self.settings.min_interval_minutes)

    def _random_interval(self) -> timedelta:
        minutes = self._rng.uniform(
            self.settings.min_interval_minutes,
            self.settings.max_interval_minutes,
        )
        return timedelta(minutes=minutes)

    def _emit(
        self,
        kind: ScheduledKind | Literal["boss_absent"],
        now: datetime,
        responses: tuple[BehaviorResponse, ...],
    ) -> ScheduledEvent:
        self._events_today += 1
        self._last_event_at = now
        self._next_random_at = now + self._random_interval()
        return ScheduledEvent(kind=kind, occurred_at=now, responses=responses)


def new_scheduler_rng(seed: int | None = None) -> SchedulerRandom:
    """Create an injectable standard-library RNG, optionally seeded for tests."""
    return cast(SchedulerRandom, random.Random(seed))
