"""Local launcher route tests for DeskBot configuration (no brain or devices)."""

from __future__ import annotations

import http.client
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

import launcher
from deskbot_local.dashboard_content import EditablePhraseLibrary
from deskbot_local.dashboard_settings import DeskBotSettingsStore
from deskbot_local.identity import TemplateStore
from deskbot_local.registry import PersonRegistry


class TestTemplateKey:
    def get_or_create_key(self) -> bytes:
        return b"0123456789abcdef0123456789abcdef"


class DeskBotDashboardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.patches = [
            patch.object(launcher, "DeskBotSettingsStore", lambda: DeskBotSettingsStore(root / "settings.json")),
            patch.object(launcher, "PersonRegistry", lambda: PersonRegistry(root / "people.sqlite3")),
            patch.object(
                launcher,
                "TemplateStore",
                lambda: TemplateStore(root / "templates.sqlite3", key_provider=TestTemplateKey()),
            ),
            patch.object(launcher, "EditablePhraseLibrary", lambda: EditablePhraseLibrary(root / "content")),
            patch.object(launcher, "brain_request", side_effect=AssertionError("offline config must not call brain")),
        ]
        for active_patch in self.patches:
            active_patch.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), launcher.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.temporary_directory.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, *, host: str | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        headers = {"Host": host or f"localhost:{self.port}"}
        payload = None
        if body is not None:
            headers.update({"Content-Type": "application/json", "X-Rocky-Console": "1"})
            payload = json.dumps(body)
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        result = response.read()
        status, response_headers = response.status, response.headers
        connection.close()
        return status, response_headers, result

    def test_routes_validate_update_people_content_and_export_without_brain(self) -> None:
        status, _, raw = self.request("GET", "/launcher/deskbot")
        self.assertEqual(status, 200)
        initial = json.loads(raw)
        self.assertFalse(initial["settings"]["spontaneous_events_enabled"])
        self.assertEqual(initial["people"], [])
        self.assertIsNone(initial["owner"])

        status, _, raw = self.request("POST", "/launcher/deskbot/people", {
            "display_name": "Sam", "role": "owner", "preferred_language": "de", "opted_in": True,
        })
        self.assertEqual(status, 201)
        person = json.loads(raw)["person"]
        self.assertTrue(person["opted_in"])
        status, _, raw = self.request("POST", "/launcher/deskbot/owner", {"person_id": person["person_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["owner"]["display_name"], "Sam")

        status, _, raw = self.request("POST", "/launcher/deskbot/settings", {
            "changes": {"language": "de", "quiet_mode": True},
        })
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["settings"]["language"], "de")
        status, _, _ = self.request("POST", "/launcher/deskbot/settings", {"changes": {"language": "fr"}})
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/launcher/deskbot/settings", {
            "changes": {"recognition_threshold": 1.2},
        })
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/launcher/deskbot/people", {
            "display_name": "Nope", "extra": True,
        })
        self.assertEqual(status, 400)

        status, _, raw = self.request("GET", "/launcher/deskbot/content?language=en")
        self.assertEqual(status, 200)
        content = json.loads(raw)["content"]
        status, _, _ = self.request("POST", "/launcher/deskbot/content", {
            "language": "en", "content": content.replace('"language": "en"', '"language": "fr"', 1),
        })
        self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/launcher/deskbot/content", {"language": "en", "content": content})
        self.assertEqual(status, 200)
        status, _, raw = self.request("GET", "/launcher/deskbot/content?language=en")
        self.assertTrue(json.loads(raw)["customized"])
        status, _, _ = self.request("POST", "/launcher/deskbot/content/reset", {"language": "en"})
        self.assertEqual(status, 200)
        status, _, raw = self.request("GET", "/launcher/deskbot/content?language=en")
        self.assertFalse(json.loads(raw)["customized"])

        status, headers, raw = self.request("GET", "/launcher/deskbot/export")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Disposition"), 'attachment; filename="deskbot-backup.json"')
        self.assertEqual(json.loads(raw)["owner"]["person_id"], person["person_id"])
        status, _, _ = self.request("POST", "/launcher/deskbot/people/delete", {"person_id": person["person_id"]})
        self.assertEqual(status, 200)
        status, _, raw = self.request("GET", "/launcher/deskbot")
        self.assertEqual(json.loads(raw)["people"], [])
        self.assertIsNone(json.loads(raw)["owner"])

    def test_owner_enrollment_requires_explicit_confirmation_without_starting_brain(self) -> None:
        status, _, _ = self.request("POST", "/launcher/deskbot/enroll", {
            "person_id": "not-enrolled", "consent_confirmed": False,
        })
        self.assertEqual(status, 400)

    def test_face_enrollment_status_is_passive_and_start_requires_consent(self) -> None:
        with patch.object(launcher.brain, "external", return_value=False), patch.object(
            launcher, "OpenCVCameraSource"
        ) as camera_source:
            status, _, raw = self.request("GET", "/launcher/face-enrollment/status")
            self.assertEqual(status, 200)
            capability = json.loads(raw)
            self.assertFalse(capability["recognition_enabled"])
            self.assertFalse(capability["active"])
            camera_source.assert_not_called()

            status, _, _ = self.request("POST", "/launcher/face-enrollment/start", {
                "mode": "enroll", "source": "mac", "display_name": "Sam", "role": "owner",
                "consent_confirmed": False,
            })
            self.assertEqual(status, 400)
            camera_source.assert_not_called()

    def test_dashboard_serves_the_german_people_enrollment_interface(self) -> None:
        status, _, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        page = raw.decode("utf-8")
        for text in (
            'id="t-people"',
            'id="p-people"',
            "Gesicht erfolgreich gespeichert",
            "DSGVO Artikel 9",
            "/launcher/face-enrollment/start",
        ):
            self.assertIn(text, page)

    def test_robot_camera_workflow_uses_running_brain_api_and_can_cancel(self) -> None:
        calls: list[tuple[str, dict]] = []

        def brain_post(path: str, payload: dict) -> tuple[int, str, bytes]:
            calls.append((path, payload))
            return 200, "application/json", json.dumps({"session": {"mode": "test"}}).encode()

        with patch.object(launcher.brain, "running", return_value=True), patch.object(
            launcher.brain, "external", return_value=False
        ), patch.object(launcher, "_brain_json_post", side_effect=brain_post), patch.object(
            launcher, "OpenCVCameraSource"
        ) as mac_camera:
            status, _, raw = self.request("POST", "/launcher/face-enrollment/start", {
                "mode": "test", "source": "robot", "camera_index": 0,
            })
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["session"]["mode"], "test")
            self.assertEqual(calls[0], ("/api/identity/enrollment/start", {"mode": "test"}))
            self.assertEqual(launcher._face_enrollment_source, "robot")
            mac_camera.assert_not_called()

            status, _, _ = self.request("POST", "/launcher/face-enrollment/cancel", {})
            self.assertEqual(status, 200)
            self.assertEqual(calls[1], ("/api/identity/enrollment/cancel", {}))
            self.assertIsNone(launcher._face_enrollment_source)

    def test_robot_session_status_refreshes_heartbeat(self) -> None:
        brain_status = {
            "frame_age_s": 0.1,
            "identity_enrollment": {"active": True, "mode": "test"},
        }
        connection = Mock()
        with (
            patch.object(launcher, "_face_enrollment_source", "robot"),
            patch.object(launcher.brain, "running", return_value=True),
            patch.object(launcher.brain, "external", return_value=False),
            patch.object(
                launcher,
                "_brain_json_post",
                return_value=(200, "application/json", b'{"touched": true}'),
            ) as post,
            patch.object(
                launcher,
                "brain_request",
                return_value=(connection, io.BytesIO(json.dumps(brain_status).encode())),
            ),
        ):
            status, _, raw = self.request("GET", "/launcher/face-enrollment/status")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["session"]["active"])
        post.assert_called_once_with("/api/identity/enrollment/touch", {})
        connection.close.assert_called_once()

    def test_withdrawing_consent_from_dashboard_removes_encrypted_templates(self) -> None:
        status, _, raw = self.request("POST", "/launcher/deskbot/people", {
            "display_name": "Consented", "opted_in": True,
        })
        self.assertEqual(status, 201)
        person_id = json.loads(raw)["person"]["person_id"]
        store = launcher.TemplateStore()
        store.add(person_id, "mock-v1", (1.0, 0.0, 0.0))
        self.assertEqual(len(store.list_all("mock-v1")), 1)

        status, _, _ = self.request("POST", "/launcher/deskbot/people/update", {
            "person_id": person_id, "opted_in": False,
        })
        self.assertEqual(status, 200)
        self.assertEqual(store.list_all("mock-v1"), [])

    def test_local_host_and_mutation_header_guards_apply(self) -> None:
        status, _, _ = self.request("GET", "/launcher/deskbot", host="example.com")
        self.assertEqual(status, 403)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        connection.request("POST", "/launcher/deskbot/settings", body="{}", headers={
            "Host": f"localhost:{self.port}", "Content-Type": "application/json",
        })
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 403)
