"""Explicit, deterministic evaluation of spontaneous offline behavior."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from deskbot_local import Scheduler, SchedulerContext, SchedulerSettings


class FixedRandom:
    def __init__(self, selected_kind: str | None = None) -> None:
        self.selected_kind = selected_kind

    def uniform(self, a: float, b: float) -> float:
        return a

    def choice(self, values):
        if self.selected_kind in values:
            return self.selected_kind
        return values[0]


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.zone = ZoneInfo("Europe/Berlin")
        self.start = datetime(2026, 10, 23, 8, 0, tzinfo=self.zone)
        self.settings = SchedulerSettings(
            active_start=time(8),
            active_end=time(16),
            quiet_start=time(16),
            quiet_end=time(8),
            min_interval_minutes=45,
            max_interval_minutes=120,
            max_events_per_day=8,
            timezone_name="Europe/Berlin",
        )

    def scheduler(self, settings=None, rng=None, clock=None) -> Scheduler:
        return Scheduler(settings or self.settings, rng=rng or FixedRandom(), clock=clock)

    def context(self, **overrides) -> SchedulerContext:
        return SchedulerContext(**overrides)

    def test_defaults_are_conservative_and_configurable(self) -> None:
        defaults = SchedulerSettings()
        self.assertEqual(defaults.active_start, time(8))
        self.assertEqual(defaults.active_end, time(16))
        self.assertEqual(defaults.min_interval_minutes, 45)
        self.assertEqual(defaults.max_interval_minutes, 120)
        self.assertEqual(defaults.max_events_per_day, 8)
        self.assertFalse(defaults.joke_offers_enabled)

    def test_injected_clock_is_used_when_now_is_none(self) -> None:
        times = iter((self.start, self.start + timedelta(minutes=45)))
        scheduler = self.scheduler(clock=lambda: next(times))
        self.assertIsNone(scheduler.evaluate(None, self.context()))
        self.assertIsNotNone(scheduler.evaluate(None, self.context()))

    def test_cooldown_prevents_rapid_repeated_events(self) -> None:
        scheduler = self.scheduler()
        self.assertIsNone(scheduler.evaluate(self.start, self.context()))
        due = self.start + timedelta(minutes=45)
        event = scheduler.evaluate(due, self.context())
        self.assertIsNotNone(event)
        self.assertIsNone(scheduler.evaluate(due + timedelta(seconds=1), self.context()))
        self.assertIsNone(scheduler.evaluate(due + timedelta(minutes=44), self.context()))
        self.assertIsNotNone(scheduler.evaluate(due + timedelta(minutes=45), self.context()))

    def test_active_and_quiet_hours_gate_events(self) -> None:
        scheduler = self.scheduler()
        before_open = self.start.replace(hour=7, minute=59)
        self.assertIsNone(scheduler.evaluate(before_open, self.context()))

        scheduler = self.scheduler()
        self.assertIsNone(scheduler.evaluate(self.start, self.context()))
        outside = self.start.replace(hour=16)
        self.assertIsNone(scheduler.evaluate(outside, self.context()))

        policy = replace(self.settings, quiet_start=time(9), quiet_end=time(10))
        scheduler = self.scheduler(policy)
        self.assertIsNone(scheduler.evaluate(self.start, self.context()))
        self.assertIsNone(scheduler.evaluate(self.start.replace(hour=9), self.context()))
        self.assertIsNotNone(scheduler.evaluate(self.start.replace(hour=10), self.context()))

    def test_quiet_mode_and_mute_mode_suppress_events(self) -> None:
        for change in ({"quiet_mode": True}, {"muted": True}):
            with self.subTest(change=change):
                policy = replace(self.settings, **change)
                scheduler = self.scheduler(policy)
                self.assertIsNone(scheduler.evaluate(self.start, self.context()))

    def test_recent_activity_suppresses_events_without_being_recorded(self) -> None:
        scheduler = self.scheduler()
        activity = self.start + timedelta(minutes=45)
        self.assertIsNone(scheduler.evaluate(self.start, self.context()))
        self.assertIsNone(
            scheduler.evaluate(activity, self.context(recent_activity_at=activity - timedelta(minutes=2)))
        )
        self.assertIsNotNone(
            scheduler.evaluate(activity + timedelta(minutes=15), self.context(recent_activity_at=activity))
        )

    def test_daily_limit_resets_on_local_day_boundary(self) -> None:
        policy = SchedulerSettings(
            active_start=time(0),
            active_end=time(0),
            quiet_start=time(0),
            quiet_end=time(0),
            min_interval_minutes=1,
            max_interval_minutes=1,
            max_events_per_day=1,
            timezone_name="Europe/Berlin",
        )
        scheduler = self.scheduler(policy)
        before_midnight = datetime(2026, 10, 23, 23, 58, tzinfo=self.zone)
        self.assertIsNone(scheduler.evaluate(before_midnight, self.context()))
        self.assertIsNotNone(scheduler.evaluate(before_midnight + timedelta(minutes=1), self.context()))
        next_day = datetime(2026, 10, 24, 0, 0, tzinfo=self.zone)
        self.assertIsNotNone(scheduler.evaluate(next_day, self.context()))
        self.assertIsNone(scheduler.evaluate(next_day + timedelta(minutes=1), self.context()))

    def test_event_randomness_is_injectable(self) -> None:
        settings = SchedulerSettings(
            active_start=time(8),
            active_end=time(16),
            quiet_start=time(16),
            quiet_end=time(8),
            min_interval_minutes=1,
            max_interval_minutes=1,
            timezone_name="Europe/Berlin",
        )
        scheduler = self.scheduler(settings, FixedRandom("smile_or_laugh"))
        self.assertIsNone(scheduler.evaluate(self.start, self.context()))
        event = scheduler.evaluate(self.start + timedelta(minutes=1), self.context())
        self.assertEqual(event.kind, "smile_or_laugh")
        self.assertIsNone(event.responses[0].text)
        self.assertIn(event.responses[0].action, ("blink", "laugh"))

    def test_sneeze_has_ordered_nonverbal_after_reaction(self) -> None:
        settings = SchedulerSettings(
            active_start=time(8),
            active_end=time(16),
            quiet_start=time(16),
            quiet_end=time(8),
            min_interval_minutes=1,
            max_interval_minutes=1,
            timezone_name="Europe/Berlin",
        )
        scheduler = self.scheduler(settings, FixedRandom("sneeze_then_reaction"))
        self.assertIsNone(scheduler.evaluate(self.start, self.context()))
        event = scheduler.evaluate(self.start + timedelta(minutes=1), self.context())
        self.assertEqual(event.kind, "sneeze_then_reaction")
        self.assertEqual(event.responses[0].event_type, "sneeze")
        self.assertEqual(event.responses[0].action, "sneeze_animation")
        self.assertEqual(event.responses[1].response_id, "sneeze_afterglow")
        self.assertIsNone(event.responses[1].text)

    def test_joke_offer_requires_both_opt_in_and_known_person_nearby(self) -> None:
        policy = SchedulerSettings(
            active_start=time(8),
            active_end=time(16),
            quiet_start=time(16),
            quiet_end=time(8),
            min_interval_minutes=1,
            max_interval_minutes=1,
            joke_offers_enabled=True,
            timezone_name="Europe/Berlin",
        )
        scheduler = self.scheduler(policy, FixedRandom("joke_offer"))
        context = self.context(known_person_nearby=False)
        self.assertIsNone(scheduler.evaluate(self.start, context))
        event = scheduler.evaluate(self.start + timedelta(minutes=1), context)
        self.assertNotEqual(event.kind, "joke_offer")

        scheduler = self.scheduler(policy, FixedRandom("joke_offer"))
        context = self.context(known_person_nearby=True)
        self.assertIsNone(scheduler.evaluate(self.start, context))
        event = scheduler.evaluate(self.start + timedelta(minutes=1), context)
        self.assertEqual(event.kind, "joke_offer")

    def test_known_greeting_is_never_a_random_scheduler_event(self) -> None:
        scheduler = self.scheduler()
        self.assertIsNone(scheduler.evaluate(self.start, self.context(known_person_nearby=True)))
        event = scheduler.evaluate(self.start + timedelta(minutes=45), self.context(known_person_nearby=True))
        self.assertNotEqual(event.kind, "greet_known")
        self.assertNotIn("greet_known", {response.event_type for response in event.responses})

    def test_owner_absence_emits_once_per_present_to_absent_transition(self) -> None:
        settings = SchedulerSettings(
            active_start=time(8),
            active_end=time(16),
            quiet_start=time(16),
            quiet_end=time(8),
            min_interval_minutes=45,
            max_interval_minutes=45,
            timezone_name="Europe/Berlin",
        )
        scheduler = self.scheduler(settings)
        self.assertIsNone(scheduler.evaluate(self.start, self.context(owner_present=True)))
        absent = self.start + timedelta(minutes=1)
        event = scheduler.evaluate(absent, self.context(owner_present=False))
        self.assertEqual(event.kind, "boss_absent")
        self.assertEqual(event.responses[0].event_type, "boss_absent")
        self.assertIsNone(scheduler.evaluate(absent + timedelta(minutes=1), self.context(owner_present=False)))
        returned = absent + timedelta(minutes=44)
        self.assertIsNone(scheduler.evaluate(returned, self.context(owner_present=True)))
        second_absence = returned + timedelta(minutes=1)
        repeated_transition = scheduler.evaluate(
            second_absence,
            self.context(owner_present=False),
        )
        self.assertEqual(repeated_transition.kind, "boss_absent")

    def test_owner_absence_does_not_bypass_daily_limit(self) -> None:
        settings = SchedulerSettings(
            active_start=time(8),
            active_end=time(16),
            quiet_start=time(16),
            quiet_end=time(8),
            min_interval_minutes=1,
            max_interval_minutes=1,
            max_events_per_day=1,
            timezone_name="Europe/Berlin",
        )
        scheduler = self.scheduler(settings, FixedRandom("smile_or_laugh"))
        self.assertIsNone(scheduler.evaluate(self.start, self.context(owner_present=True)))
        self.assertIsNotNone(
            scheduler.evaluate(self.start + timedelta(minutes=1), self.context(owner_present=True))
        )
        self.assertIsNone(
            scheduler.evaluate(self.start + timedelta(minutes=2), self.context(owner_present=False))
        )

    def test_settings_reject_invalid_interval_and_timezone(self) -> None:
        with self.assertRaises(ValueError):
            SchedulerSettings(min_interval_minutes=120, max_interval_minutes=45)
        with self.assertRaises(ValueError):
            SchedulerSettings(timezone_name="Not/A_Zone")
        with self.assertRaises(ValueError):
            SchedulerSettings(max_events_per_day=1.5)
        with self.assertRaises(ValueError):
            SchedulerSettings(min_interval_minutes=float("nan"))


if __name__ == "__main__":
    unittest.main()
