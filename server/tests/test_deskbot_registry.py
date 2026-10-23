"""Tests for the local, consent-gated person registry."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from deskbot_local import (
    ConsentRequiredError,
    DuplicatePersonError,
    PersonNotFoundError,
    PersonRegistry,
    RegistryError,
    default_data_directory,
)


class PersonRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "deskbot" / "people.sqlite3"
        self.registry = PersonRegistry(self.database_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_create_get_update_and_list_consented_enrolled_people(self) -> None:
        person = self.registry.create_person(
            " Alex ",
            preferred_language="de",
            role="colleague",
            person_id="person-1",
        )
        self.assertEqual(person.display_name, "Alex")
        self.assertEqual(person.preferred_language, "de")
        self.assertFalse(person.enrolled)
        self.assertFalse(person.opted_in)
        self.assertEqual(self.registry.list_enabled_enrolled_people(), [])

        self.registry.record_opt_in(person.person_id, True)
        enrolled = self.registry.enroll(person.person_id)
        self.assertTrue(enrolled.enrolled)
        self.assertEqual(self.registry.list_enabled_enrolled_people(), [enrolled])

        renamed = self.registry.set_display_name(person.person_id, "Alex M.")
        translated = self.registry.set_preferred_language(person.person_id, "en")
        personalized = self.registry.set_personalized_greetings_enabled(person.person_id, True)
        self.assertEqual(renamed.display_name, "Alex M.")
        self.assertEqual(translated.preferred_language, "en")
        self.assertTrue(personalized.personalized_greetings_enabled)
        self.assertEqual(self.registry.get_person(person.person_id), personalized)

    def test_duplicate_person_id_is_rejected(self) -> None:
        self.registry.create_person("Riley", person_id="same-id")
        with self.assertRaises(DuplicatePersonError):
            self.registry.create_person("Morgan", person_id="same-id")

    def test_missing_person_operations_report_not_found(self) -> None:
        with self.assertRaises(PersonNotFoundError):
            self.registry.get_person("missing")
        with self.assertRaises(PersonNotFoundError):
            self.registry.set_display_name("missing", "Nobody")
        self.assertFalse(self.registry.delete_person("missing"))

    def test_disabled_or_not_enrolled_profiles_cannot_be_resolved(self) -> None:
        person = self.registry.create_person("Sam", person_id="sam")
        self.registry.record_opt_in(person.person_id, True)
        self.assertIsNone(self.registry.get_recognition_candidate(person.person_id))
        self.registry.enroll(person.person_id)
        self.assertEqual(
            self.registry.get_recognition_candidate(person.person_id).person_id,
            person.person_id,
        )
        self.registry.set_enabled(person.person_id, False)
        self.assertIsNone(self.registry.get_recognition_candidate(person.person_id))
        self.assertEqual(self.registry.list_enabled_enrolled_people(), [])
        self.assertIsNone(self.registry.get_recognition_candidate("unknown"))
        self.assertIsNone(self.registry.get_recognition_candidate(""))

    def test_missing_explicit_opt_in_blocks_enrollment_and_personalization(self) -> None:
        person = self.registry.create_person("Jordan", person_id="jordan")
        with self.assertRaises(ConsentRequiredError):
            self.registry.enroll(person.person_id)
        with self.assertRaises(ConsentRequiredError):
            self.registry.set_personalized_greetings_enabled(person.person_id, True)
        self.assertFalse(self.registry.get_person(person.person_id).enrolled)

    def test_withdrawing_opt_in_disables_enrollment_and_personalization(self) -> None:
        person = self.registry.create_person("Taylor", person_id="taylor")
        self.registry.record_opt_in(person.person_id, True)
        self.registry.enroll(person.person_id)
        self.registry.set_personalized_greetings_enabled(person.person_id, True)
        withdrawn = self.registry.record_opt_in(person.person_id, False)
        self.assertFalse(withdrawn.opted_in)
        self.assertFalse(withdrawn.enrolled)
        self.assertFalse(withdrawn.personalized_greetings_enabled)
        self.assertIsNone(self.registry.get_recognition_candidate(person.person_id))

    def test_language_role_and_boolean_values_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.create_person("Casey", preferred_language="fr")
        with self.assertRaises(ValueError):
            self.registry.create_person("Casey", role="manager")
        person = self.registry.create_person("Casey", person_id="casey")
        with self.assertRaises(ValueError):
            self.registry.set_preferred_language(person.person_id, "FR")
        with self.assertRaises(ValueError):
            self.registry.set_enabled(person.person_id, 1)

    def test_owner_must_be_explicit_and_presence_is_current_state_only(self) -> None:
        self.assertIsNone(self.registry.get_configured_owner())
        with self.assertRaises(RegistryError):
            self.registry.set_owner_presence(True)
        colleague = self.registry.create_person("Lee", role="colleague", person_id="lee")
        with self.assertRaises(RegistryError):
            self.registry.set_configured_owner(colleague.person_id)

        owner = self.registry.create_person("Owner", role="owner", person_id="owner-1")
        configured = self.registry.set_configured_owner(owner.person_id)
        self.assertEqual(configured, owner)
        self.assertIsNone(self.registry.get_owner_presence())
        self.registry.set_owner_presence(False)
        self.assertFalse(self.registry.get_owner_presence())
        self.registry.set_owner_presence(True)
        self.assertTrue(self.registry.get_owner_presence())
        with self.assertRaises(RegistryError):
            self.registry.set_role(owner.person_id, "colleague")

        self.assertTrue(self.registry.delete_person(owner.person_id))
        self.assertIsNone(self.registry.get_configured_owner())
        self.assertIsNone(self.registry.get_owner_presence())

    def test_deletion_removes_person_and_invokes_local_data_cleanup(self) -> None:
        deleted_ids: list[str] = []
        registry = PersonRegistry(
            self.database_path.parent / "other.sqlite3",
            recognition_data_deleter=deleted_ids.append,
        )
        person = registry.create_person("Robin", person_id="robin")
        self.assertTrue(registry.delete_person(person.person_id))
        self.assertEqual(deleted_ids, [person.person_id])
        with self.assertRaises(PersonNotFoundError):
            registry.get_person(person.person_id)

    def test_cleanup_failure_preserves_registry_record(self) -> None:
        def fail_cleanup(_person_id: str) -> None:
            raise OSError("local recognition data could not be removed")

        registry = PersonRegistry(
            self.database_path.parent / "cleanup.sqlite3",
            recognition_data_deleter=fail_cleanup,
        )
        person = registry.create_person("Avery", person_id="avery")
        with self.assertRaisesRegex(OSError, "could not be removed"):
            registry.delete_person(person.person_id)
        remaining = registry.get_person(person.person_id)
        self.assertFalse(remaining.enabled)
        self.assertFalse(remaining.enrolled)
        self.assertFalse(remaining.opted_in)
        self.assertNotEqual(remaining, person)

    def test_default_data_directories_follow_platform_conventions(self) -> None:
        home = Path("/users/example")
        self.assertEqual(
            default_data_directory(system="darwin", home=home, environ={}),
            home / "Library" / "Application Support" / "DeskBot",
        )
        self.assertEqual(
            default_data_directory(
                system="win32",
                home=home,
                environ={"LOCALAPPDATA": "C:/Users/example/AppData/Local"},
            ),
            Path("C:/Users/example/AppData/Local") / "DeskBot",
        )
        self.assertEqual(
            default_data_directory(
                system="linux",
                home=home,
                environ={"XDG_DATA_HOME": "/tmp/user-data"},
            ),
            Path("/tmp/user-data/deskbot"),
        )
        self.assertEqual(
            default_data_directory(system="linux", home=home, environ={"XDG_DATA_HOME": "relative"}),
            home / ".local" / "share" / "deskbot",
        )

    @unittest.skipUnless(os.name == "posix", "POSIX file permission check")
    def test_database_file_is_private_on_posix(self) -> None:
        self.assertEqual(self.database_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
