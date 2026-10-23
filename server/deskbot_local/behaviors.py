"""Pure local response selection for DeskBot behavior events."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Protocol, cast

from .content import (
    _COLLECTIONS,
    PhraseCatalog,
    PhraseDataError,
    as_action,
    as_expression,
    event_for_collection,
)
from .models import BehaviorResponse, EventType, Language


class ChoiceSource(Protocol):
    """The small random-selection interface used by behavior primitives."""

    def choice(self, values: Sequence[dict]) -> dict: ...


def _language(value: str) -> Language:
    if value not in ("de", "en"):
        raise ValueError("language must be 'de' or 'en'")
    return cast(Language, value)


def _unavailable(language: Language, event_type: EventType, error: PhraseDataError) -> BehaviorResponse:
    return BehaviorResponse(
        text=None,
        language=language,
        expression="neutral",
        action=None,
        event_type=event_type,
        response_id="content_unavailable",
        error=str(error),
    )


def _select(
    collection: str,
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
    answer: str | None = None,
    person_name: str | None = None,
) -> BehaviorResponse:
    lang = _language(language)
    event_type = cast(EventType, event_for_collection(collection))
    try:
        phrases = (catalog or PhraseCatalog()).load(lang)
        entries = phrases[_COLLECTIONS.get(collection, collection)]
        if answer is not None:
            entries = entries[answer]
        preferred = [entry for entry in entries if not entry["fallback"]]
        if preferred:
            entries = preferred
        entry = (chooser or random).choice(entries)
        text = entry["text"]
        if person_name is not None:
            text = text.replace("{person_name}", person_name.strip())
        return BehaviorResponse(
            text=text,
            language=lang,
            expression=as_expression(entry["expression"]),
            action=as_action(entry.get("action")),
            event_type=event_type,
            response_id=entry["id"],
        )
    except PhraseDataError as error:
        return _unavailable(lang, event_type, error)


def _person_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("person_name must be non-empty text")
    return value.strip()


def greet_known(
    person_name: str,
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Choose a greeting for an explicitly known person."""
    name = _person_name(person_name)
    return _select("greet_known", language, catalog=catalog, chooser=chooser, person_name=name)


def greet_unknown(
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Choose a greeting that makes no identity assumption."""
    return _select("greet_unknown", language, catalog=catalog, chooser=chooser)


def on_head_tap(
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Describe a reaction to a head tap without invoking hardware."""
    return _select("on_head_tap", language, catalog=catalog, chooser=chooser)


def sneeze(
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Choose a sneeze reaction; any animation is only suggested in the result."""
    return _select("sneeze", language, catalog=catalog, chooser=chooser)


def offer_joke(
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Offer a locally stored joke."""
    return _select("offer_joke", language, catalog=catalog, chooser=chooser)


def answer_joke(
    yes_or_no: bool | str,
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Choose the local acceptance or rejection response to a joke offer."""
    if isinstance(yes_or_no, bool):
        answer = "yes" if yes_or_no else "no"
    elif isinstance(yes_or_no, str):
        normalized = yes_or_no.strip().casefold()
        if normalized in {"yes", "ja"}:
            answer = "yes"
        elif normalized in {"no", "nein"}:
            answer = "no"
        else:
            raise ValueError("yes_or_no must be a bool or one of yes/no/ja/nein")
    else:
        raise ValueError("yes_or_no must be a bool or one of yes/no/ja/nein")
    return _select("joke_answer", language, catalog=catalog, chooser=chooser, answer=answer)


def boss_absent(
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Choose a local reaction to the boss being away."""
    return _select("boss_absent", language, catalog=catalog, chooser=chooser)


def boss_present(
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Choose a local reaction to the boss returning."""
    return _select("boss_present", language, catalog=catalog, chooser=chooser)


def idle_reaction(
    language: str,
    *,
    catalog: PhraseCatalog | None = None,
    chooser: ChoiceSource | None = None,
) -> BehaviorResponse:
    """Choose an ambient local reaction."""
    return _select("idle_reaction", language, catalog=catalog, chooser=chooser)
