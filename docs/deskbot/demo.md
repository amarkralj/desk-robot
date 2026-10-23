# Offline DeskBot CLI demo

## Start and exit

From the `server/` directory, run:

```bash
./.venv/bin/python -m deskbot_local.demo
```

For repeatable random phrase and event selection:

```bash
./.venv/bin/python -m deskbot_local.demo --seed 37
```

At the `deskbot>` prompt, type `quit` and press Enter to exit. Ctrl-D also
exits at the prompt; Ctrl-C interrupts and exits. The registry database is
created in a temporary directory and removed when the demo exits.

## Commands

Type `help` in the simulator for the complete list. Examples:

```text
unknown de
enroll "Alex Morgan" de
greetings "Alex Morgan" on
known "Alex Morgan"
joke en
yes
owner Morgan
boss here
boss away
simulate start
tick 45
simulate stop
quit
```

`known` is a typed simulation of a person event, not face recognition. It uses
only a profile explicitly enrolled during this demo and only produces a
personalized greeting after `greetings <name> on`. Demo enrollment records
explicit opt-in in a temporary registry but captures no image and stores no
biometric template.

Owner identity is configured only by the explicit `owner <name>` command;
presence changes are explicit `boss here` / `boss away` commands. The
simulator reports a reaction once per transition. Before the scheduler is
started, these explicit commands exercise owner reactions directly. After
`simulate start`, owner-state transitions are evaluated by the scheduler on
the explicit command/tick evaluation path.

The spontaneous scheduler is stopped at startup. `simulate start` must be
entered before `tick` is accepted. Each `tick` advances simulated time (one
minute by default); configured demo events are eligible after 45 simulated
minutes. The scheduler has no background loop and cannot trigger an event
between commands.

All behavior selection uses the local bilingual content library and the
existing behavior functions. Intended output is passed to
`DryRunRobotAdapter`, which prints and records what would happen. No command
starts `brain.main`, an LLM, a network client, camera, microphone, serial port,
or physical robot. Speech, touch reactions, and unsupported animations are
simulated only.

## Automated tests

From the repository root:

```bash
cd server
./.venv/bin/python -m unittest tests.test_deskbot_demo -v
```
