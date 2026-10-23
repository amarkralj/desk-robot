"""User-owned phrase overrides for dashboard editing."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .content import PHRASE_DIR, USER_PHRASE_DIR, PhraseCatalog

_LANGUAGES = frozenset({"de", "en"})
_MAX_CONTENT_BYTES = 48 * 1024


class EditablePhraseLibrary:
    """Keep dashboard edits out of the version-controlled example library."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = USER_PHRASE_DIR if directory is None else Path(directory)

    def read(self, language: str) -> tuple[str, bool]:
        lang = _validate_language(language)
        override = self.directory / f"{lang}.json"
        source = override if override.is_file() else PHRASE_DIR / f"{lang}.json"
        try:
            return source.read_text(encoding="utf-8"), source == override
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"could not read {lang} phrase library: {exc}") from exc

    def save(self, language: str, text: str) -> None:
        lang = _validate_language(language)
        if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise ValueError("phrase library must be text no larger than 48 KiB")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}") from exc
        PhraseCatalog._validate(raw, lang)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = self.directory / f"{lang}.json"
        fd, temporary_name = tempfile.mkstemp(prefix=f".{lang}-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(raw, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            if os.name == "posix":
                os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def reset(self, language: str) -> None:
        lang = _validate_language(language)
        override = self.directory / f"{lang}.json"
        try:
            override.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValueError(f"could not reset {lang} phrase library: {exc}") from exc


def _validate_language(language: str) -> str:
    if not isinstance(language, str) or language not in _LANGUAGES:
        raise ValueError("language must be 'de' or 'en'")
    return language
