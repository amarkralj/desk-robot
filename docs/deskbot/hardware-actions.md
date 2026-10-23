# DeskBot hardware action adapter

`server/deskbot_local/actions.py` defines a `RobotActionAdapter` boundary,
`BehaviorActionExecutor`, and `DryRunRobotAdapter`. Behavior responses remain
descriptions; the executor receives the adapter by dependency injection. The
default executor creates only a dry-run adapter. No serial port, WebSocket,
camera, microphone, audio device, or physical output is opened.

The dry-run adapter records each intent in memory and prints a readable
`[dry-run]` line. A record may include a JSON message as a reference to an
existing protocol command; the dry-run implementation never transmits it.
There is no physical/WebSocket adapter in this phase.

## Existing mappings and capabilities

| Action | Current outcome | Existing firmware/protocol basis |
|---|---|---|
| Set face expression | Documented WebSocket message | `emotion` with one of the documented expression names |
| Pan head | Documented WebSocket message | `pan`, limited to -95 through +95 degrees |
| Tilt head | Documented WebSocket message | `tilt`, limited to -85 through +85 degrees |
| Blink | Dry-run only in this adapter; firmware console has `blink` | No documented server-to-robot blink WebSocket message |
| Speak phrase | Dry-run prints the text | Firmware accepts `speak_begin`/`speak_end` and binary PCM audio; text-to-speech generation/transport is not part of this adapter |
| Head-tap reaction | Simulated response only | No touch sensor or head-tap protocol event is present |
| Sneeze animation | Simulated response only | No dedicated firmware animation command |
| Laugh animation | Simulated response only | No dedicated firmware animation command; expression can be set separately |
| Enter/leave idle | Existing `asleep` WebSocket message | Firmware sleep face and centered head behavior; not a generic idle-animation command |
| Quiet mode | Local policy in the adapter suppresses phrase output | No dedicated quiet-mode protocol message |

The V2 head is not unrestricted 360-degree rotation. Firmware limits are
enforced before any action record is created; out-of-range and non-finite
angles raise `ValueError` rather than being clamped.

The existing serial console's `raw pan|tilt` calibration command bypasses
limits. It is intentionally not exposed by the action interface. Physical
head-tap sensing and animation support require hardware/firmware changes and
must not be claimed until separately validated.

The interface has no dependency on the LLM. Callers must supply an actual
head-tap behavior response; the adapter never attempts to detect a tap.
Nothing automatically consumes spontaneous scheduler events.
