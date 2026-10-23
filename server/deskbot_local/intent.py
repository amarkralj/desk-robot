"""Small parser for the explicit local DeskBot command-line demo."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Literal

DemoCommand = Literal[
    "help",
    "known",
    "unknown",
    "pet",
    "sneeze",
    "joke",
    "yes",
    "no",
    "boss_away",
    "boss_here",
    "idle",
    "mute",
    "unmute",
    "enroll",
    "greetings",
    "owner",
    "simulate_start",
    "simulate_stop",
    "tick",
    "quit",
]


@dataclass(frozen=True, slots=True)
class DemoIntent:
    """A parsed command and its positional arguments."""

    command: DemoCommand
    arguments: tuple[str, ...] = ()


_LANGUAGES = {"de", "en"}


def _optional_language(tokens: list[str], command: str) -> DemoIntent:
    language = "en"
    if tokens and tokens[-1].casefold() in _LANGUAGES:
        language = tokens.pop().casefold()
    if tokens:
        raise ValueError(f"usage: {command} [de|en]")
    return DemoIntent(command, (language,))


def parse_demo_command(line: str) -> DemoIntent:
    """Parse one command. Free-form names can be quoted or contain spaces."""
    if not isinstance(line, str):
        raise ValueError("command must be text")
    try:
        tokens = shlex.split(line)
    except ValueError as exc:
        raise ValueError(f"could not parse command: {exc}") from exc
    if not tokens:
        return DemoIntent("help")

    command, *arguments = tokens
    command = command.casefold()
    if command in {"help", "quit", "yes", "no", "mute", "unmute", "idle"}:
        if arguments:
            raise ValueError(f"usage: {command}")
        return DemoIntent(command)  # type: ignore[arg-type]
    if command in {"known", "enroll"}:
        if not arguments:
            raise ValueError(f"usage: {command} <name> [de|en]")
        language: str | None = "en" if command == "enroll" else None
        if arguments[-1].casefold() in _LANGUAGES:
            language = arguments.pop().casefold()
        if not arguments:
            raise ValueError(f"usage: {command} <name> [de|en]")
        return DemoIntent(command, (" ".join(arguments), language or ""))
    if command in {"unknown", "pet", "sneeze", "joke"}:
        return _optional_language(arguments, command)  # type: ignore[arg-type]
    if command == "boss":
        if arguments == ["away"]:
            return DemoIntent("boss_away")
        if arguments == ["here"]:
            return DemoIntent("boss_here")
        raise ValueError("usage: boss away | boss here")
    if command == "owner":
        if not arguments:
            raise ValueError("usage: owner <name>")
        return DemoIntent("owner", (" ".join(arguments),))
    if command == "greetings":
        if len(arguments) < 2 or arguments[-1].casefold() not in {"on", "off"}:
            raise ValueError("usage: greetings <name> on|off")
        action = arguments.pop().casefold()
        return DemoIntent("greetings", (" ".join(arguments), action))
    if command == "simulate":
        if arguments == ["start"]:
            return DemoIntent("simulate_start")
        if arguments == ["stop"]:
            return DemoIntent("simulate_stop")
        raise ValueError("usage: simulate start | simulate stop")
    if command == "tick":
        if len(arguments) > 1:
            raise ValueError("usage: tick [minutes]")
        if arguments:
            try:
                minutes = int(arguments[0])
            except ValueError as exc:
                raise ValueError("tick minutes must be a positive integer") from exc
            if minutes <= 0:
                raise ValueError("tick minutes must be a positive integer")
            return DemoIntent("tick", (str(minutes),))
        return DemoIntent("tick", ("1",))
    raise ValueError(f"unknown command: {tokens[0]}")
