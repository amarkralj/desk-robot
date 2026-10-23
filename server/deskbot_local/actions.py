"""Injected robot-action interface and safe, non-connecting dry-run adapter."""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TextIO

from .models import BehaviorResponse, Expression, Language

PAN_MIN_DEG = -95.0
PAN_MAX_DEG = 95.0
TILT_MIN_DEG = -85.0
TILT_MAX_DEG = 85.0


class ActionCapability(StrEnum):
    """How an action relates to commands or hardware in the existing firmware."""

    WEBSOCKET = "documented_websocket"
    FIRMWARE_CONSOLE = "firmware_console_only"
    AUDIO_STREAM = "firmware_audio_stream_requires_tts"
    LOCAL_ONLY = "local_policy_only"
    SIMULATED = "simulated_only"


@dataclass(frozen=True, slots=True)
class ActionRecord:
    """One action intent recorded by an adapter."""

    action: str
    description: str
    capability: ActionCapability
    protocol_message: str | None = None
    enabled: bool = True

    def message_dict(self) -> dict[str, object] | None:
        """Decode the documented JSON message, if this action has one."""
        if self.protocol_message is None:
            return None
        return json.loads(self.protocol_message)


class RobotActionAdapter(Protocol):
    """Side-effect boundary used by behavior orchestration."""

    def set_expression(self, expression: Expression) -> ActionRecord: ...

    def blink(self) -> ActionRecord: ...

    def pan(self, degrees: float) -> ActionRecord: ...

    def tilt(self, degrees: float) -> ActionRecord: ...

    def speak_phrase(self, phrase: str, language: Language) -> ActionRecord: ...

    def react_to_head_tap(self, response: BehaviorResponse) -> tuple[ActionRecord, ...]: ...

    def animate_sneeze(self) -> ActionRecord: ...

    def animate_laugh(self) -> ActionRecord: ...

    def set_idle(self, idle: bool) -> ActionRecord: ...

    def set_quiet(self, quiet: bool) -> ActionRecord: ...

    def execute_response(self, response: BehaviorResponse) -> tuple[ActionRecord, ...]: ...

_EXPRESSIONS = frozenset(
    {
        "neutral", "happy", "sad", "angry", "surprised", "sleepy",
        "thinking", "curious", "skeptical", "excited", "love", "confused",
    }
)
_ACTIONS = frozenset(
    {
        "set_expression",
        "blink",
        "pan",
        "tilt",
        "speak_phrase",
        "head_tap",
        "sneeze_animation",
        "laugh_animation",
        "set_idle",
        "set_quiet",
    }
)


class DryRunRobotAdapter:
    """Record and print intended actions; never opens or sends to hardware.

    Dry-run is the only implementation in this module and is the safe default.
    Names in ``disabled_actions`` are recorded as disabled without performing
    the intent. Quiet mode locally suppresses spoken phrases.
    """

    def __init__(
        self,
        *,
        output: TextIO | None = None,
        disabled_actions: Collection[str] = (),
    ) -> None:
        unknown = set(disabled_actions) - _ACTIONS
        if unknown:
            raise ValueError(f"unknown disabled action(s): {', '.join(sorted(unknown))}")
        self.output = sys.stdout if output is None else output
        self.disabled_actions = frozenset(disabled_actions)
        self.records: list[ActionRecord] = []
        self.quiet = False

    def set_expression(self, expression: Expression) -> ActionRecord:
        if expression not in _EXPRESSIONS:
            raise ValueError(f"unsupported expression: {expression}")
        return self._record(
            "set_expression",
            f"Set face expression to {expression}",
            ActionCapability.WEBSOCKET,
            {"type": "emotion", "name": expression},
        )

    def blink(self) -> ActionRecord:
        return self._record(
            "blink",
            "Blink the face",
            ActionCapability.FIRMWARE_CONSOLE,
        )

    def pan(self, degrees: float) -> ActionRecord:
        value = self._angle(degrees, PAN_MIN_DEG, PAN_MAX_DEG, "pan")
        return self._record(
            "pan",
            f"Pan head to {value:g} degrees",
            ActionCapability.WEBSOCKET,
            {"type": "pan", "deg": value},
        )

    def tilt(self, degrees: float) -> ActionRecord:
        value = self._angle(degrees, TILT_MIN_DEG, TILT_MAX_DEG, "tilt")
        return self._record(
            "tilt",
            f"Tilt head to {value:g} degrees",
            ActionCapability.WEBSOCKET,
            {"type": "tilt", "deg": value},
        )

    def speak_phrase(self, phrase: str, language: Language) -> ActionRecord:
        if language not in ("de", "en"):
            raise ValueError("language must be 'de' or 'en'")
        if not isinstance(phrase, str) or not phrase.strip():
            raise ValueError("phrase must not be empty")
        phrase = phrase.strip()
        if self.quiet:
            return self._record(
                "speak_phrase",
                f"Speech suppressed by quiet mode ({language}): {phrase}",
                ActionCapability.AUDIO_STREAM,
                enabled=False,
            )
        return self._record(
            "speak_phrase",
            f"Would speak [{language}]: {phrase}",
            ActionCapability.AUDIO_STREAM,
        )

    def react_to_head_tap(self, response: BehaviorResponse) -> tuple[ActionRecord, ...]:
        """Run a caller-provided response; does not sense or claim touch hardware."""
        if response.event_type != "head_tap":
            raise ValueError("head-tap reaction requires a head_tap behavior response")
        receipt = self._record(
            "head_tap",
            "Simulate a head-tap reaction (no touch sensor or protocol event exists)",
            ActionCapability.SIMULATED,
        )
        if not receipt.enabled:
            return (receipt,)
        return (receipt, *self._perform_response(response))

    def animate_sneeze(self) -> ActionRecord:
        return self._record(
            "sneeze_animation",
            "Simulate sneeze animation (no dedicated firmware animation command)",
            ActionCapability.SIMULATED,
        )

    def animate_laugh(self) -> ActionRecord:
        return self._record(
            "laugh_animation",
            "Simulate laugh animation (no dedicated firmware animation command)",
            ActionCapability.SIMULATED,
        )

    def set_idle(self, idle: bool) -> ActionRecord:
        self._validate_bool(idle, "idle")
        return self._record(
            "set_idle",
            "Enter firmware sleep/idle state" if idle else "Wake firmware face from sleep/idle",
            ActionCapability.WEBSOCKET,
            {"type": "asleep", "on": idle},
        )

    def set_quiet(self, quiet: bool) -> ActionRecord:
        self._validate_bool(quiet, "quiet")
        self.quiet = quiet
        return self._record(
            "set_quiet",
            "Enable local quiet policy (speech suppressed)" if quiet
            else "Disable local quiet policy (speech allowed)",
            ActionCapability.LOCAL_ONLY,
        )

    def execute_response(self, response: BehaviorResponse) -> tuple[ActionRecord, ...]:
        """Apply a behavior description through this injected adapter only."""
        if response.event_type == "head_tap":
            return self.react_to_head_tap(response)
        return self._perform_response(response)

    def _perform_response(self, response: BehaviorResponse) -> tuple[ActionRecord, ...]:
        result: list[ActionRecord] = []
        result.append(self.set_expression(response.expression))
        if response.action == "blink":
            result.append(self.blink())
        elif response.action == "sneeze_animation":
            result.append(self.animate_sneeze())
        elif response.action == "laugh":
            result.append(self.animate_laugh())
        elif response.action in ("nod", "head_tilt"):
            result.append(
                self._record(
                    response.action,
                    f"Simulate {response.action.replace('_', ' ')} (no angle requested)",
                    ActionCapability.SIMULATED,
                )
            )
        if response.text:
            result.append(self.speak_phrase(response.text, response.language))
        return tuple(result)

    def _record(
        self,
        action: str,
        description: str,
        capability: ActionCapability,
        message: Mapping[str, object] | None = None,
        *,
        enabled: bool = True,
    ) -> ActionRecord:
        is_enabled = enabled and action not in self.disabled_actions
        if not is_enabled and enabled:
            description = f"Disabled: {description}"
        record = ActionRecord(
            action=action,
            description=description,
            capability=capability,
            protocol_message=(
                json.dumps(message, separators=(",", ":"), ensure_ascii=True)
                if message is not None
                else None
            ),
            enabled=is_enabled,
        )
        self.records.append(record)
        print(f"[dry-run] {record.description}", file=self.output)
        return record

    @staticmethod
    def _angle(value: float, minimum: float, maximum: float, axis: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{axis} angle must be a finite number")
        if not minimum <= value <= maximum:
            raise ValueError(f"{axis} angle must be between {minimum:g} and {maximum:g} degrees")
        return float(value)

    @staticmethod
    def _validate_bool(value: bool, name: str) -> None:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")


class BehaviorActionExecutor:
    """Connect pure behavior functions to an explicitly injected adapter."""

    def __init__(self, adapter: RobotActionAdapter | None = None) -> None:
        self.adapter = DryRunRobotAdapter() if adapter is None else adapter

    def execute(self, response: BehaviorResponse) -> tuple[ActionRecord, ...]:
        return self.adapter.execute_response(response)
