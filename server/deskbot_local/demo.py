"""Interactive, offline-only DeskBot behavior and action simulator.

Run from ``server/`` with ``./.venv/bin/python -m deskbot_local.demo``.
The demo uses a temporary registry database and only the dry-run action adapter.
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from .actions import ActionRecord, BehaviorActionExecutor, DryRunRobotAdapter
from .behaviors import (
    answer_joke,
    boss_absent,
    boss_present,
    greet_known,
    greet_unknown,
    idle_reaction,
    offer_joke,
    on_head_tap,
    sneeze,
)
from .content import PhraseCatalog
from .intent import DemoIntent, parse_demo_command
from .models import BehaviorResponse
from .registry import (
    Person,
    PersonRegistry,
    RegistryError,
)
from .scheduler import Scheduler, SchedulerContext, SchedulerSettings

HELP_TEXT = """Commands:
  help                         Show commands
  known <name> [de|en]          Simulate an enrolled, greeting-enabled person event
  unknown [de|en]               Greet without identifying anyone
  pet [de|en]                   Simulate a head-tap reaction (no sensor is used)
  sneeze [de|en]                Select a local sneeze response
  joke [de|en]                  Offer a local joke; follow with yes or no
  yes | no                      Answer the pending joke offer
  owner <name>                  Explicitly configure the demo's owner profile
  boss here | boss away         Change current owner state; away reacts once per transition
  idle [de|en]                  Select a local idle reaction
  mute | unmute                 Suppress/allow spoken output in the simulator
  enroll <name> [de|en]         Explicitly opt in a temporary simulated profile
  greetings <name> on|off       Enable/disable its personalized greeting
  simulate start | stop         Explicitly enable/disable scheduler ticks
  tick [minutes]                Evaluate one scheduled event after advancing simulated time
  quit                          Exit

Enrollment and recognition are simulated: no face image/template is captured.
All hardware actions and speech remain dry-run; no physical output is sent."""


class DeskBotDemo:
    """One interactive session with ephemeral registry data and explicit ticks."""

    def __init__(
        self,
        *,
        seed: int | None = None,
        output: TextIO | None = None,
        registry: PersonRegistry | None = None,
        now: datetime | None = None,
    ) -> None:
        self.output = sys.stdout if output is None else output
        self.rng = random.Random(seed)
        self.catalog = PhraseCatalog()
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        if registry is None:
            self._temporary_directory = tempfile.TemporaryDirectory(prefix="deskbot-demo-")
            registry = PersonRegistry(Path(self._temporary_directory.name) / "people.sqlite3")
        self.registry = registry
        self.adapter = DryRunRobotAdapter(output=self.output)
        self.executor = BehaviorActionExecutor(self.adapter)
        self.scheduler = Scheduler(
            SchedulerSettings(
                active_start=datetime.min.time(),
                active_end=datetime.min.time(),
                quiet_start=datetime.min.time(),
                quiet_end=datetime.min.time(),
                min_interval_minutes=45,
                max_interval_minutes=45,
                max_events_per_day=100,
                joke_offers_enabled=True,
                timezone_name="UTC",
            ),
            rng=self.rng,
        )
        self.simulated_now = now or datetime.now().astimezone()
        self.simulation_started = False
        self.pending_joke_language: str | None = None
        self.owner: Person | None = None
        self.enrolled_by_name: dict[str, Person] = {}
        self._should_quit = False

    def close(self) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
            self._temporary_directory = None

    def run_command(self, line: str) -> bool:
        """Execute one input line. Return false when the session should exit."""
        try:
            intent = parse_demo_command(line)
            self._dispatch(intent)
        except (ValueError, RegistryError) as exc:
            print(f"Error: {exc}", file=self.output)
        return not self._should_quit

    def _dispatch(self, intent: DemoIntent) -> None:
        command, args = intent.command, intent.arguments
        if command == "help":
            print(HELP_TEXT, file=self.output)
        elif command == "quit":
            self._should_quit = True
        elif command == "known":
            self._known(args[0], args[1] or None)
        elif command == "unknown":
            self._respond(greet_unknown(args[0], catalog=self.catalog, chooser=self.rng))
        elif command == "pet":
            self._respond(on_head_tap(args[0], catalog=self.catalog, chooser=self.rng))
        elif command == "sneeze":
            self._respond(sneeze(args[0], catalog=self.catalog, chooser=self.rng))
        elif command == "joke":
            language = args[0]
            self.pending_joke_language = language
            self._respond(offer_joke(language, catalog=self.catalog, chooser=self.rng))
            print("Answer with yes or no.", file=self.output)
        elif command in {"yes", "no"}:
            if self.pending_joke_language is None:
                raise ValueError("there is no pending joke offer; use joke first")
            response = answer_joke(
                command == "yes",
                self.pending_joke_language,
                catalog=self.catalog,
                chooser=self.rng,
            )
            self.pending_joke_language = None
            self._respond(response)
        elif command == "owner":
            self._configure_owner(args[0])
        elif command in {"boss_here", "boss_away"}:
            self._set_owner_presence(command == "boss_here")
        elif command == "idle":
            self._respond(idle_reaction(args[0], catalog=self.catalog, chooser=self.rng))
        elif command == "mute":
            self.adapter.set_quiet(True)
        elif command == "unmute":
            self.adapter.set_quiet(False)
        elif command == "enroll":
            self._enroll_simulated(args[0], args[1])
        elif command == "greetings":
            self._set_greeting_preference(args[0], args[1] == "on")
        elif command == "simulate_start":
            self._start_simulation()
        elif command == "simulate_stop":
            self.simulation_started = False
            print("Scheduler simulation stopped.", file=self.output)
        elif command == "tick":
            self._tick(int(args[0]))

    def _known(self, name: str, language: str | None) -> None:
        normalized_name = name.casefold()
        person = next(
            (
                candidate
                for candidate in self.registry.list_enabled_enrolled_people()
                if candidate.display_name.casefold() == normalized_name
            ),
            None,
        )
        if person is None or not person.personalized_greetings_enabled:
            print(
                f"Unknown in this demo: {name!r}. Use enroll <name> [de|en], "
                f"then greetings <name> on to enable a simulated personal greeting.",
                file=self.output,
            )
            fallback_language = (
                language
                or (person.preferred_language if person is not None else "en")
            )
            self._respond(greet_unknown(fallback_language, catalog=self.catalog, chooser=self.rng))
            return
        response_language = person.preferred_language if language is None else language
        self._respond(
            greet_known(
                person.display_name,
                response_language,
                catalog=self.catalog,
                chooser=self.rng,
            )
        )

    def _enroll_simulated(self, name: str, language: str) -> None:
        key = name.casefold()
        existing = self.enrolled_by_name.get(key)
        if existing is None:
            person = self.registry.create_person(
                name,
                preferred_language=language,
                role="colleague",
            )
            self.registry.record_opt_in(person.person_id, True)
            person = self.registry.enroll(person.person_id)
            self.enrolled_by_name[key] = person
        print(
            f"Simulated profile enrolled for {name!r} ({language}); explicit consent was "
            "given by this enroll command. No biometric data was captured.",
            file=self.output,
        )

    def _set_greeting_preference(self, name: str, enabled: bool) -> None:
        person = self.enrolled_by_name.get(name.casefold())
        if person is None:
            raise ValueError("enroll this simulated profile first")
        updated = self.registry.set_personalized_greetings_enabled(person.person_id, enabled)
        self.enrolled_by_name[name.casefold()] = updated
        print(
            f"Personalized greetings {'enabled' if enabled else 'disabled'} for {name}.",
            file=self.output,
        )

    def _configure_owner(self, name: str) -> None:
        person = self.registry.create_person(name, role="owner")
        self.registry.set_configured_owner(person.person_id)
        self.owner = person
        print(f"Configured demo owner: {person.display_name}.", file=self.output)

    def _set_owner_presence(self, present: bool) -> None:
        if self.owner is None:
            raise ValueError("configure the owner explicitly first with: owner <name>")
        previous = self.registry.get_owner_presence()
        self.registry.set_owner_presence(present)
        self.simulated_now += timedelta(minutes=1)
        if self.simulation_started:
            event = self.scheduler.evaluate(
                self.simulated_now,
                SchedulerContext(
                    language=self.owner.preferred_language,
                    owner_present=present,
                ),
            )
            if event is not None and event.kind == "boss_absent":
                for response in event.responses:
                    self._respond(response)
            elif event is not None:
                print(f"Scheduled event: {event.kind}", file=self.output)
                for response in event.responses:
                    self._respond(response)
            elif previous is not present and present:
                self._respond(boss_present(self.owner.preferred_language, catalog=self.catalog, chooser=self.rng))
            elif previous is not present and not present:
                self._respond(boss_absent(self.owner.preferred_language, catalog=self.catalog, chooser=self.rng))
            else:
                print(f"Owner is still {'here' if present else 'away'}; no transition reaction.", file=self.output)
        elif previous is not present:
            response = (
                boss_present(self.owner.preferred_language, catalog=self.catalog, chooser=self.rng)
                if present
                else boss_absent(self.owner.preferred_language, catalog=self.catalog, chooser=self.rng)
            )
            self._respond(response)
        else:
            print(f"Owner is still {'here' if present else 'away'}; no transition reaction.", file=self.output)

    def _start_simulation(self) -> None:
        self.simulation_started = True
        self.scheduler.evaluate(
            self.simulated_now,
            self._scheduler_context(),
        )
        print(
            "Scheduler simulation started. It runs only on explicit tick commands; "
            "the first default event is due after 45 simulated minutes.",
            file=self.output,
        )

    def _tick(self, minutes: int) -> None:
        if not self.simulation_started:
            raise ValueError("scheduler is stopped; use simulate start before tick")
        self.simulated_now += timedelta(minutes=minutes)
        event = self.scheduler.evaluate(self.simulated_now, self._scheduler_context())
        if event is None:
            print("No scheduled event.", file=self.output)
            return
        print(f"Scheduled event: {event.kind}", file=self.output)
        for response in event.responses:
            self._respond(response)

    def _scheduler_context(self) -> SchedulerContext:
        return SchedulerContext(
            language=self.owner.preferred_language if self.owner is not None else "en",
            known_person_nearby=bool(self.registry.list_enabled_enrolled_people()),
            owner_present=self.registry.get_owner_presence(),
        )

    def _respond(self, response: BehaviorResponse) -> tuple[ActionRecord, ...]:
        print(f"Response [{response.response_id}]: {response.text or '(no spoken text)'}", file=self.output)
        print(f"Event: {response.event_type}", file=self.output)
        print(f"Language: {response.language}", file=self.output)
        print(f"Expression: {response.expression}", file=self.output)
        print(f"Intended head/animation action: {response.action or 'none'}", file=self.output)
        records = self.executor.execute(response)
        capabilities = ", ".join(sorted({record.capability.value for record in records})) or "none"
        print(
            f"Execution: simulated (dry-run; not physically executed; capabilities: {capabilities})",
            file=self.output,
        )
        return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline DeskBot behavior simulator")
    parser.add_argument("--seed", type=int, default=None, help="seed random phrase/event selection")
    args = parser.parse_args(argv)
    demo = DeskBotDemo(seed=args.seed)
    print("DeskBot offline demo. Type help for commands; quit or Ctrl-D to exit.")
    try:
        while True:
            try:
                line = input("deskbot> ")
            except EOFError:
                print()
                break
            if not demo.run_command(line):
                break
    except KeyboardInterrupt:
        print()
    finally:
        demo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
