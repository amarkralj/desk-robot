# DeskBot dashboard configuration

The DeskBot tab is an isolated local configuration surface served by the existing launcher. It uses the launcher's loopback binding and its existing local Host, cross-site fetch, and `X-Rocky-Console: 1` mutation guards. Opening the tab only reads local configuration and editable phrase files; it does not start `brain.main`, the scheduler, a camera, a microphone, recognition, audio, or hardware.

## Storage and privacy

On macOS the files are stored below `~/Library/Application Support/DeskBot/`; the registry module selects platform-appropriate per-user data directories on other operating systems.

- `deskbot-settings.json`: language, event settings, active hours, quiet mode, future touch-sensitivity preference, and privacy/recognition preferences. Defaults keep spontaneous behavior off, privacy mode on, and recognition off.
- `people.sqlite3`: locally entered profiles, explicit opt-in, and the explicitly configured owner. It contains no raw images or biometric templates in this phase.
- `content/{en,de}.json`: validated user phrase-library overrides. Example content stays version-controlled in `server/deskbot_local/content/`; resetting an override returns to that example.

The backup downloads a JSON bundle containing preferences, registry records (including names and consent state), owner selection, and the active phrase libraries. Store that file carefully because it contains personal data. No API keys or legacy brain settings are included.

Recognition is not activated by the dashboard: it remains an unintegrated preference only. Enabling it requires privacy mode to be off, but does not open a camera or run inference. Personalized identity recognition continues to require explicit opt-in and future verified enrollment. Touch sensitivity is also stored only; the firmware has no verified touch sensor.

## Routes

All routes are served by `server/launcher.py`.

| Method and route | Purpose |
|---|---|
| `GET /launcher/deskbot` | Read DeskBot preferences, registry profiles, and configured owner. |
| `POST /launcher/deskbot/settings` | Validate and save DeskBot-only settings. Body: `{"changes": {...}}`. |
| `POST /launcher/deskbot/owner` | Explicitly select or clear the owner. Body: `{"person_id": "..."}` or `null`. |
| `POST /launcher/deskbot/people` | Add a profile. Body accepts `display_name`, `role`, `preferred_language`, and `opted_in`. |
| `POST /launcher/deskbot/people/update` | Update an existing profile and consent state. |
| `POST /launcher/deskbot/people/delete` | Delete a profile and invoke any configured local recognition-data cleanup. |
| `GET /launcher/deskbot/content?language=en` | Read the effective example or local override. Use `de` for German. |
| `POST /launcher/deskbot/content` | Validate against the existing phrase schema and save a user override. |
| `POST /launcher/deskbot/content/reset` | Remove the selected override and restore the version-controlled example. |
| `GET /launcher/deskbot/export` | Download a local JSON backup. |

Mutations require the launcher's custom console header, local Host validation, and existing cross-site protections. Server-side validation applies independently of browser controls.

## Controls and validation

The tab provides robot language; spontaneous-event enablement; minimum and maximum event interval; active start/end time; quiet mode; touch sensitivity (future hardware only); privacy and recognition preferences; owner selection; local profile creation/update/consent/deletion; bilingual JSON phrase editing/reset; and backup export.

Settings require `de` or `en`, strict booleans, 24-hour `HH:MM` times, 1–1440 minute intervals with maximum not below minimum, and integer touch sensitivity from 0–100. Recognition cannot be enabled while privacy mode is enabled. Phrase JSON is limited to 48 KiB and is checked by the same `PhraseCatalog` validator used by the offline behavior engine before saving.

## Validation commands

From `server/`:

```sh
./.venv/bin/python -m unittest tests.test_deskbot_dashboard_settings tests.test_deskbot_dashboard_routes -v
./.venv/bin/python -m unittest discover -s tests -v
```

The route tests bind only a temporary loopback HTTP server and replace all DeskBot storage with temporary paths; they fail if a live brain request is attempted.
