"""Local person registry with explicit consent and no biometric storage.

Creating a profile does not enroll a person. Call :meth:`PersonRegistry.enroll`
only after recording explicit opt-in. Recognition providers must use
``get_recognition_candidate`` and treat ``None`` as unknown.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, cast

from .models import Language

PersonRole = Literal["owner", "colleague", "visitor"]


class RegistryError(Exception):
    """Base error for local registry operations."""


class PersonNotFoundError(RegistryError):
    """The requested person does not exist."""


class DuplicatePersonError(RegistryError):
    """A person with the requested registry ID already exists."""


class ConsentRequiredError(RegistryError):
    """Explicit opt-in is required before enrollment or personalization."""


@dataclass(frozen=True, slots=True)
class Person:
    """A registry profile; it contains no face image or biometric template."""

    person_id: str
    display_name: str
    preferred_language: Language
    role: PersonRole
    enabled: bool
    enrolled: bool
    personalized_greetings_enabled: bool
    opted_in: bool


def default_data_directory(
    *,
    system: str | None = None,
    home: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Return a per-user application data directory without creating it."""
    current_system = sys.platform if system is None else system
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else Path(home)

    if current_system == "darwin":
        return user_home / "Library" / "Application Support" / "DeskBot"
    if current_system.startswith("win"):
        base = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        return (Path(base) if base else user_home / "AppData" / "Local") / "DeskBot"
    xdg_data_home = environment.get("XDG_DATA_HOME")
    if xdg_data_home and Path(xdg_data_home).is_absolute():
        return Path(xdg_data_home) / "deskbot"
    return user_home / ".local" / "share" / "deskbot"


class PersonRegistry:
    """SQLite-backed profiles and current owner state, isolated from UI/sensors.

    ``database_path`` is injectable for tests. ``recognition_data_deleter`` is
    an optional future-provider cleanup hook; it receives the registry ID before
    the profile is removed and should be idempotent. This registry itself never
    stores images, embeddings, or biometric templates.
    """

    def __init__(
        self,
        database_path: Path | str | None = None,
        *,
        recognition_data_deleter: Callable[[str], None] | None = None,
    ) -> None:
        self.database_path = (
            Path(database_path)
            if database_path is not None
            else default_data_directory() / "people.sqlite3"
        )
        self._recognition_data_deleters = (
            [] if recognition_data_deleter is None else [recognition_data_deleter]
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            descriptor = os.open(self.database_path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(descriptor)
            self.database_path.chmod(0o600)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS people (
                    person_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL CHECK(length(trim(display_name)) > 0),
                    preferred_language TEXT NOT NULL CHECK(preferred_language IN ('de', 'en')),
                    role TEXT NOT NULL CHECK(role IN ('owner', 'colleague', 'visitor')),
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                    enrolled INTEGER NOT NULL DEFAULT 0 CHECK(enrolled IN (0, 1)),
                    personalized_greetings_enabled INTEGER NOT NULL DEFAULT 0
                        CHECK(personalized_greetings_enabled IN (0, 1)),
                    opted_in INTEGER NOT NULL DEFAULT 0 CHECK(opted_in IN (0, 1)),
                    CHECK(enrolled = 0 OR opted_in = 1),
                    CHECK(personalized_greetings_enabled = 0 OR (enrolled = 1 AND opted_in = 1))
                );
                CREATE TABLE IF NOT EXISTS registry_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    owner_person_id TEXT REFERENCES people(person_id) ON DELETE SET NULL,
                    owner_present INTEGER CHECK(owner_present IN (0, 1))
                );
                INSERT OR IGNORE INTO registry_state (singleton, owner_person_id, owner_present)
                VALUES (1, NULL, NULL);
                """
            )

    @staticmethod
    def _validate_language(language: str) -> Language:
        if language not in ("de", "en"):
            raise ValueError("preferred_language must be 'de' or 'en'")
        return cast(Language, language)

    @staticmethod
    def _validate_role(role: str) -> PersonRole:
        if role not in ("owner", "colleague", "visitor"):
            raise ValueError("role must be 'owner', 'colleague', or 'visitor'")
        return cast(PersonRole, role)

    @staticmethod
    def _validate_person_id(person_id: str) -> str:
        if not isinstance(person_id, str) or not person_id.strip() or len(person_id) > 128:
            raise ValueError("person_id must be a non-empty string of at most 128 characters")
        return person_id

    @staticmethod
    def _validate_display_name(display_name: str) -> str:
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError("display_name must not be empty")
        return display_name.strip()

    @staticmethod
    def _as_person(row: sqlite3.Row) -> Person:
        return Person(
            person_id=row["person_id"],
            display_name=row["display_name"],
            preferred_language=row["preferred_language"],
            role=row["role"],
            enabled=bool(row["enabled"]),
            enrolled=bool(row["enrolled"]),
            personalized_greetings_enabled=bool(row["personalized_greetings_enabled"]),
            opted_in=bool(row["opted_in"]),
        )

    def create_person(
        self,
        display_name: str,
        *,
        preferred_language: str = "en",
        role: str = "visitor",
        person_id: str | None = None,
    ) -> Person:
        """Create a profile only; enrollment and consent remain separate actions."""
        name = self._validate_display_name(display_name)
        language = self._validate_language(preferred_language)
        valid_role = self._validate_role(role)
        identifier = self._validate_person_id(str(uuid.uuid4()) if person_id is None else person_id)
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO people (person_id, display_name, preferred_language, role)
                    VALUES (?, ?, ?, ?)
                    """,
                    (identifier, name, language, valid_role),
                )
                row = connection.execute(
                    "SELECT * FROM people WHERE person_id = ?", (identifier,)
                ).fetchone()
        except sqlite3.IntegrityError as exc:
            if "people.person_id" in str(exc) or "UNIQUE constraint failed" in str(exc):
                raise DuplicatePersonError(f"person ID already exists: {identifier}") from exc
            raise RegistryError(f"could not create person: {exc}") from exc
        if row is None:
            raise RegistryError("person was inserted but could not be retrieved")
        return self._as_person(row)

    def get_person(self, person_id: str) -> Person:
        identifier = self._validate_person_id(person_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM people WHERE person_id = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise PersonNotFoundError(f"person not found: {identifier}")
        return self._as_person(row)

    def list_enabled_enrolled_people(self) -> list[Person]:
        """List only enabled profiles that are enrolled and explicitly opted in."""
        return [person for person in self.list_people() if person.enabled and person.enrolled and person.opted_in]

    def list_people(self) -> list[Person]:
        """List local profiles for registry-management interfaces."""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM people ORDER BY display_name COLLATE NOCASE, person_id
                """
            ).fetchall()
        return [self._as_person(row) for row in rows]

    def set_display_name(self, person_id: str, display_name: str) -> Person:
        return self._update_person(person_id, "display_name", self._validate_display_name(display_name))

    def set_preferred_language(self, person_id: str, language: str) -> Person:
        return self._update_person(person_id, "preferred_language", self._validate_language(language))

    def set_role(self, person_id: str, role: str) -> Person:
        valid_role = self._validate_role(role)
        with self._connection() as connection:
            self._require_person(connection, person_id)
            owner_id = self._owner_id(connection)
            if owner_id == person_id and valid_role != "owner":
                raise RegistryError("the configured owner cannot be changed to another role")
            connection.execute("UPDATE people SET role = ? WHERE person_id = ?", (valid_role, person_id))
            row = connection.execute("SELECT * FROM people WHERE person_id = ?", (person_id,)).fetchone()
        return self._as_person(row)

    def set_enabled(self, person_id: str, enabled: bool) -> Person:
        self._validate_bool(enabled, "enabled")
        return self._update_person(person_id, "enabled", int(enabled))

    def record_opt_in(self, person_id: str, opted_in: bool) -> Person:
        """Record an explicit consent choice; withdrawal disables personalization."""
        self._validate_bool(opted_in, "opted_in")
        identifier = self._validate_person_id(person_id)
        with self._connection() as connection:
            self._require_person(connection, identifier)
            if opted_in:
                connection.execute("UPDATE people SET opted_in = 1 WHERE person_id = ?", (identifier,))
            else:
                connection.execute(
                    """
                    UPDATE people
                    SET opted_in = 0, enrolled = 0, personalized_greetings_enabled = 0
                    WHERE person_id = ?
                    """,
                    (identifier,),
                )
        if not opted_in:
            self._delete_recognition_data(identifier)
        return self.get_person(identifier)

    def add_recognition_data_deleter(self, deleter: Callable[[str], None]) -> None:
        """Register local biometric cleanup to run before a profile is removed or opted out."""
        if deleter not in self._recognition_data_deleters:
            self._recognition_data_deleters.append(deleter)

    def enroll(self, person_id: str) -> Person:
        """Mark a voluntarily opted-in profile enrolled; stores no biometric data."""
        identifier = self._validate_person_id(person_id)
        with self._connection() as connection:
            person = self._require_person(connection, identifier)
            if not person["opted_in"]:
                raise ConsentRequiredError("explicit opt-in is required before enrollment")
            connection.execute("UPDATE people SET enrolled = 1 WHERE person_id = ?", (identifier,))
            row = connection.execute("SELECT * FROM people WHERE person_id = ?", (identifier,)).fetchone()
        return self._as_person(row)

    def set_personalized_greetings_enabled(self, person_id: str, enabled: bool) -> Person:
        self._validate_bool(enabled, "enabled")
        identifier = self._validate_person_id(person_id)
        with self._connection() as connection:
            person = self._require_person(connection, identifier)
            if enabled and not (person["opted_in"] and person["enrolled"]):
                raise ConsentRequiredError("opt-in and enrollment are required for personalized greetings")
            connection.execute(
                "UPDATE people SET personalized_greetings_enabled = ? WHERE person_id = ?",
                (int(enabled), identifier),
            )
            row = connection.execute("SELECT * FROM people WHERE person_id = ?", (identifier,)).fetchone()
        return self._as_person(row)

    def get_recognition_candidate(self, person_id: str) -> Person | None:
        """Resolve a provider-supplied registry ID, failing closed to unknown."""
        try:
            person = self.get_person(person_id)
        except (PersonNotFoundError, ValueError):
            return None
        if not person.enabled or not person.enrolled or not person.opted_in:
            return None
        return person

    def delete_person(self, person_id: str) -> bool:
        """Remove a person and invoke the optional local-data cleanup hook."""
        identifier = self._validate_person_id(person_id)
        with self._connection() as connection:
            person = connection.execute(
                "SELECT 1 FROM people WHERE person_id = ?", (identifier,)
            ).fetchone()
            if person is None:
                return False
            connection.execute(
                """
                UPDATE people
                SET enabled = 0, enrolled = 0, opted_in = 0,
                    personalized_greetings_enabled = 0
                WHERE person_id = ?
                """,
                (identifier,),
            )
            connection.execute(
                """
                UPDATE registry_state
                SET owner_person_id = NULL, owner_present = NULL
                WHERE owner_person_id = ?
                """,
                (identifier,),
            )
        self._delete_recognition_data(identifier)
        with self._connection() as connection:
            cursor = connection.execute("DELETE FROM people WHERE person_id = ?", (identifier,))
            return cursor.rowcount == 1

    def set_configured_owner(self, person_id: str | None) -> Person | None:
        """Explicitly configure the owner identity, or clear the configuration."""
        identifier = None if person_id is None else self._validate_person_id(person_id)
        with self._connection() as connection:
            if identifier is None:
                connection.execute(
                    "UPDATE registry_state SET owner_person_id = NULL, owner_present = NULL WHERE singleton = 1"
                )
                return None
            person = self._require_person(connection, identifier)
            if person["role"] != "owner":
                raise RegistryError("configured owner must have the owner role")
            connection.execute(
                "UPDATE registry_state SET owner_person_id = ?, owner_present = NULL WHERE singleton = 1",
                (identifier,),
            )
            row = connection.execute(
                "SELECT * FROM people WHERE person_id = ?", (identifier,)
            ).fetchone()
        return self._as_person(row)

    def get_configured_owner(self) -> Person | None:
        with self._connection() as connection:
            owner_id = self._owner_id(connection)
        return None if owner_id is None else self.get_person(owner_id)

    def set_owner_presence(self, present: bool) -> None:
        """Set current owner state only; no attendance history is retained."""
        self._validate_bool(present, "present")
        with self._connection() as connection:
            if self._owner_id(connection) is None:
                raise RegistryError("configure an owner before setting owner presence")
            connection.execute(
                "UPDATE registry_state SET owner_present = ? WHERE singleton = 1",
                (int(present),),
            )

    def get_owner_presence(self) -> bool | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT owner_present FROM registry_state WHERE singleton = 1"
            ).fetchone()
        value = row["owner_present"]
        return None if value is None else bool(value)

    def _update_person(self, person_id: str, field: str, value: object) -> Person:
        identifier = self._validate_person_id(person_id)
        if field not in {"display_name", "preferred_language", "enabled"}:
            raise ValueError("unsupported person field")
        with self._connection() as connection:
            self._require_person(connection, identifier)
            connection.execute(f"UPDATE people SET {field} = ? WHERE person_id = ?", (value, identifier))
            row = connection.execute("SELECT * FROM people WHERE person_id = ?", (identifier,)).fetchone()
        return self._as_person(row)

    def _delete_recognition_data(self, person_id: str) -> None:
        for deleter in self._recognition_data_deleters:
            deleter(person_id)

    @staticmethod
    def _owner_id(connection: sqlite3.Connection) -> str | None:
        row = connection.execute(
            "SELECT owner_person_id FROM registry_state WHERE singleton = 1"
        ).fetchone()
        return row["owner_person_id"]

    @classmethod
    def _require_person(cls, connection: sqlite3.Connection, person_id: str) -> sqlite3.Row:
        identifier = cls._validate_person_id(person_id)
        row = connection.execute("SELECT * FROM people WHERE person_id = ?", (identifier,)).fetchone()
        if row is None:
            raise PersonNotFoundError(f"person not found: {identifier}")
        return row

    @staticmethod
    def _validate_bool(value: bool, name: str) -> None:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
