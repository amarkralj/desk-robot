"""Load and validate editable English and German behavior phrase files.

Each language JSON file has ``schema_version``, ``language``, and a non-empty
list for each behavior collection. Entries contain a stable ``id``, ``text``,
an existing face ``expression``, optional ``action`` (JSON null means no
action), and a ``fallback`` boolean. Each response list has exactly one
fallback entry. ``greet_known`` text uses ``{person_name}``; ``joke_answer``
is an object with separate ``yes`` and ``no`` response lists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from .models import Action, Expression, Language
from .registry import default_data_directory

PHRASE_DIR = Path(__file__).resolve().parent / "content"
USER_PHRASE_DIR = default_data_directory() / "content"

_EXPRESSIONS = frozenset(
    {
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
    }
)
_ACTIONS = frozenset({"blink", "nod", "head_tilt", "sneeze_animation", "laugh"})
_EVENTS = frozenset(
    {
        "greet_known",
        "greet_unknown",
        "head_tap",
        "sneeze",
        "joke_offer",
        "joke_answer",
        "boss_absent",
        "boss_present",
        "idle_reaction",
    }
)
_RESPONSE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COLLECTIONS = {
    "greet_known": "greet_known",
    "greet_unknown": "greet_unknown",
    "on_head_tap": "head_tap",
    "sneeze": "sneeze",
    "offer_joke": "joke_offer",
    "boss_absent": "boss_absent",
    "boss_present": "boss_present",
    "idle_reaction": "idle_reaction",
}


class PhraseDataError(ValueError):
    """Phrase content is missing or does not match the documented schema."""


class PhraseCatalog:
    """Read phrase data on demand; construction and imports do no file I/O."""

    def __init__(self, phrase_dir: Path | str | None = None) -> None:
        self.phrase_dir = PHRASE_DIR if phrase_dir is None else Path(phrase_dir)
        self.user_phrase_dir = USER_PHRASE_DIR if phrase_dir is None else None

    def load(self, language: Language) -> dict:
        path = self.phrase_dir / f"{language}.json"
        if self.user_phrase_dir is not None:
            override = self.user_phrase_dir / f"{language}.json"
            if override.is_file():
                path = override
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PhraseDataError(f"could not read phrase data for {language}: {exc}") from exc
        return self._validate(raw, language)

    @staticmethod
    def _validate(raw: object, language: Language) -> dict:
        if not isinstance(raw, dict) or raw.get("schema_version") != 1 or raw.get("language") != language:
            raise PhraseDataError(f"{language} phrase file must have schema_version 1 and matching language")

        ids: set[str] = set()
        for collection in _COLLECTIONS.values():
            PhraseCatalog._validate_entries(raw.get(collection), collection, ids)

        joke_answers = raw.get("joke_answer")
        if not isinstance(joke_answers, dict) or set(joke_answers) != {"yes", "no"}:
            raise PhraseDataError("joke_answer must contain exactly 'yes' and 'no' lists")
        PhraseCatalog._validate_entries(joke_answers["yes"], "joke_answer.yes", ids)
        PhraseCatalog._validate_entries(joke_answers["no"], "joke_answer.no", ids)
        owner_greetings = raw.get("owner_greetings")
        if owner_greetings is not None:
            PhraseCatalog._validate_entries(owner_greetings, "owner_greetings", ids)
            if len(owner_greetings) < 4:
                raise PhraseDataError("owner_greetings must contain at least four entries")
        return raw

    @staticmethod
    def _validate_entries(entries: object, name: str, ids: set[str]) -> None:
        if not isinstance(entries, list) or not entries:
            raise PhraseDataError(f"{name} must be a non-empty list")
        fallback_count = 0
        for entry in entries:
            if not isinstance(entry, dict):
                raise PhraseDataError(f"{name} entries must be objects")
            response_id = entry.get("id")
            text = entry.get("text")
            expression = entry.get("expression")
            action = entry.get("action")
            if not isinstance(response_id, str) or not _RESPONSE_ID.fullmatch(response_id):
                raise PhraseDataError(f"{name} entries need a stable lowercase id")
            if response_id in ids:
                raise PhraseDataError(f"duplicate response id {response_id!r}")
            ids.add(response_id)
            if not isinstance(text, str) or not text.strip():
                raise PhraseDataError(f"{name}.{response_id} needs non-empty text")
            if name == "owner_greetings" and "Chef" not in text:
                raise PhraseDataError(f"{name}.{response_id} must address the configured owner as Chef")
            if not isinstance(expression, str) or expression not in _EXPRESSIONS:
                raise PhraseDataError(f"{name}.{response_id} has an unsupported expression")
            if action is not None and (not isinstance(action, str) or action not in _ACTIONS):
                raise PhraseDataError(f"{name}.{response_id} has an unsupported action")
            fallback = entry.get("fallback")
            if not isinstance(fallback, bool):
                raise PhraseDataError(f"{name}.{response_id} needs a fallback boolean")
            fallback_count += fallback
            if name == "greet_known" and "{person_name}" not in text:
                raise PhraseDataError(f"{name}.{response_id} text must include {{person_name}}")
        if fallback_count != 1:
            raise PhraseDataError(f"{name} must have exactly one fallback entry")


def as_expression(value: str) -> Expression:
    """Narrow an expression already checked by PhraseCatalog."""
    return cast(Expression, value)


def as_action(value: str | None) -> Action | None:
    """Narrow an action already checked by PhraseCatalog."""
    return cast(Action | None, value)


def event_for_collection(collection: str) -> str:
    """Return the event type associated with a phrase collection."""
    event = _COLLECTIONS.get(collection, collection).split(".", maxsplit=1)[0]
    if event not in _EVENTS:
        raise PhraseDataError(f"unknown phrase collection: {collection}")
    return event
