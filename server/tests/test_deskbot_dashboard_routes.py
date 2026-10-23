"""Local launcher route tests for DeskBot configuration (no brain or devices)."""

from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import launcher
from deskbot_local.dashboard_content import EditablePhraseLibrary
from deskbot_local.dashboard_settings import DeskBotSettingsStore
from deskbot_local.registry import PersonRegistry


class DeskBotDashboardRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.patches = [
            patch.object(launcher, "DeskBotSettingsStore", lambda: DeskBotSettingsStore(root / "settings.json")),
            patch.object(launcher, "PersonRegistry", lambda: PersonRegistry(root / "people.sqlite3")),
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
