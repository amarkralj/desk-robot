"""Rocky's launcher: the dashboard, always available, with a Start / Stop button for the brain server.

    server/.venv/bin/python server/launcher.py          (or: server/install_launcher.sh, to start it at login)

then open http://localhost:8766/. It serves the dashboard page, starts and stops the brain (`python -m brain.main`)
as a child process, shows the brain's output, and reads / writes the settings (server/settings.json) even while the
brain is stopped. While the brain runs, the live parts of the page (camera, status, controls) are passed through to
the brain's own small web server on 127.0.0.1:8767.

Standard library only, and it never touches the camera, the microphone or the robot itself, so it is cheap to leave
running. Like the brain's server it only answers on this computer: requests must be addressed to a local name, and
anything that changes something needs the console's custom header (a cross-site page can't send one).

The brain's output is kept in memory only (for the Log tab), never written to disk, and speech the brain heard but
ignored (not meant for Rocky) is shown without its words: run `python -m brain.main` in a terminal to see those.
"""

from __future__ import annotations

import collections
import dataclasses
import http.client
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# The environment as this was started, before brain.config copies server/.env into it. Each brain gets this one,
# so it reads .env itself, fresh: with the copy, a key changed in .env stayed the old one until the launcher restarted.
LAUNCH_ENV = dict(os.environ)
from brain import characters, config, faces, settings  # noqa: E402  (all standard-library only)
from deskbot_local.dashboard_content import EditablePhraseLibrary  # noqa: E402
from deskbot_local.dashboard_settings import DeskBotSettingsStore  # noqa: E402
from deskbot_local.dashboard_enrollment import (  # noqa: E402
    FaceEnrollmentSession,
    OpenCVCameraSource,
)
from deskbot_local.identity import (  # noqa: E402
    FaceIdentityService,
    FaceRecognitionError,
    OpenCVSFaceProvider,
    TemplateStore,
)
from deskbot_local.registry import PersonRegistry, RegistryError  # noqa: E402
from brain.face_detector import MODEL as YUNET_MODEL  # noqa: E402
from deskbot_local.setup_face_models import MODEL_DIR  # noqa: E402

PORT = int(os.environ.get("ROCKY_DASHBOARD_PORT", "8766"))
BIND = "127.0.0.1"
BRAIN_PORT = config.LIVE_VIEW_PORT
PAGE = HERE / "brain" / "dashboard.html"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def brain_python() -> str:
    """The venv's Python if there is one (it has the brain's dependencies), else this one."""
    for cand in (HERE / ".venv" / "bin" / "python", HERE / ".venv" / "Scripts" / "python.exe"):
        if cand.exists():
            return str(cand)
    return sys.executable


# Prints this computer's audio inputs as JSON: {"mics": [{"name", "default"}], "error"?}
MIC_LIST = """
import json
try:
    import sounddevice as sd
    d = sd.default.device[0]
    mics = [{"name": x["name"], "default": i == d} for i, x in enumerate(sd.query_devices()) if x["max_input_channels"] > 0]
    print(json.dumps({"mics": mics}))
except Exception as e:
    print(json.dumps({"mics": [], "error": str(e)}))
"""

IGNORED = "(heard, ignoring:"   # main.py's line for speech that wasn't meant for Rocky
SFACE_MODEL = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
_face_enrollment: FaceEnrollmentSession | None = None
_face_enrollment_source: str | None = None
_face_enrollment_lock = threading.Lock()


def face_enrollment_status() -> dict:
    """Return safe capability state without opening a camera or loading a model."""
    settings_now = DeskBotSettingsStore().load()
    session = _face_enrollment
    try:
        import cv2

        opencv_sface = hasattr(cv2, "FaceRecognizerSF")
    except ImportError:
        opencv_sface = False
    model_files_present = YUNET_MODEL.is_file() and SFACE_MODEL.is_file()
    model_available = model_files_present and opencv_sface
    return {
        "model_available": model_available,
        "recognition_enabled": settings_now["recognition_enabled"],
        "privacy_mode": settings_now["privacy_mode"],
        "active": (
            session is not None and session.status()["active"]
        ) or _face_enrollment_source == "robot",
        "robot_camera_available": brain.running() or brain.external(),
        "camera_source": (
            session.status().get("source") if session is not None else _face_enrollment_source
        ),
        "model": (
            "OpenCV SFace (local CPU)" if model_available
            else "Unavailable; local model files are missing" if not model_files_present
            else "Unavailable; this OpenCV build lacks FaceRecognizerSF"
        ),
    }


def _start_face_enrollment(body: dict) -> FaceEnrollmentSession:
    global _face_enrollment
    if set(body) - {
        "mode", "source", "camera_index", "display_name", "role",
        "consent_confirmed", "configure_owner",
    }:
        raise ValueError("unknown face-enrollment field")
    mode = body.get("mode", "enroll")
    source_name = body.get("source", "mac")
    if mode not in ("enroll", "test"):
        raise ValueError("mode must be enroll or test")
    if source_name != "mac":
        raise ValueError("robot camera sessions must use the existing tracker pipeline")

    if mode == "enroll":
        name = body.get("display_name")
        role = body.get("role")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            raise ValueError("display name must contain 1 to 80 characters")
        if role not in ("owner", "person"):
            raise ValueError("role must be owner or person")
        if body.get("consent_confirmed") is not True:
            raise ValueError("explicit opt-in is required before face enrollment")
        configure_owner = body.get("configure_owner", False)
        if not isinstance(configure_owner, bool):
            raise ValueError("configure_owner must be true or false")
        if configure_owner and role != "owner":
            raise ValueError("only an owner profile can be configured as owner")
    else:
        name = ""
        role = "person"
        configure_owner = False
        if set(body) - {"mode", "source", "camera_index"}:
            raise ValueError("recognition test does not accept profile or consent fields")

    camera_index = body.get("camera_index", 0)
    if isinstance(camera_index, bool) or not isinstance(camera_index, int) or not 0 <= camera_index <= 16:
        raise ValueError("camera_index must be an integer between 0 and 16")
    deskbot_settings = DeskBotSettingsStore().load()
    if deskbot_settings["privacy_mode"]:
        raise ValueError("Turn off privacy mode explicitly before starting local face enrollment or testing")
    if not deskbot_settings["recognition_enabled"]:
        raise ValueError("Enable local identity recognition explicitly before starting this camera workflow")
    if not YUNET_MODEL.is_file() or not SFACE_MODEL.is_file():
        raise FaceRecognitionError("local recognition is unavailable; provision the documented YuNet and SFace models")
    try:
        import cv2
    except ImportError as exc:
        raise FaceRecognitionError("OpenCV is unavailable for local face recognition") from exc
    if not hasattr(cv2, "FaceRecognizerSF"):
        raise FaceRecognitionError("this OpenCV build does not include FaceRecognizerSF")
    with _face_enrollment_lock:
        if _face_enrollment is not None and _face_enrollment.status()["active"]:
            raise ValueError("A camera workflow is already active; cancel it before starting another")
        registry = PersonRegistry()
        templates = TemplateStore()
        registry.add_recognition_data_deleter(templates.delete_person)
        provider = OpenCVSFaceProvider(YUNET_MODEL, SFACE_MODEL)
        identity_service = FaceIdentityService(
            registry,
            provider,
            templates,
            minimum_similarity=deskbot_settings["recognition_threshold"],
            privacy_mode=False,
        )
        source = OpenCVCameraSource(camera_index)
        session = FaceEnrollmentSession(
            source=source,
            provider=provider,
            identity_service=identity_service,
            registry=registry,
            mode=mode,
            camera_source=source_name,
            display_name=name,
            role=role,
            consent_confirmed=body.get("consent_confirmed") is True,
            make_configured_owner=configure_owner,
        )
        session.start()
        _face_enrollment = session
        return session


def _stop_face_enrollment(session: FaceEnrollmentSession | None = None) -> None:
    global _face_enrollment, _face_enrollment_source
    with _face_enrollment_lock:
        current = _face_enrollment
        if session is not None and current is not session:
            return
        _face_enrollment = None
        _face_enrollment_source = None
    if current is not None:
        current.stop()


def _brain_json_post(path: str, payload: dict) -> tuple[int, str, bytes]:
    body = json.dumps(payload).encode("utf-8")
    connection, response = brain_request(
        "POST",
        path,
        body,
        {
            "X-Rocky-Console": "1",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )
    try:
        return response.status, response.getheader("Content-Type") or "application/json", response.read()
    finally:
        connection.close()


class Brain:
    """The brain server as a child process, plus the last few thousand lines it printed (in memory only)."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.lines: collections.deque[tuple[int, str]] = collections.deque(maxlen=3000)
        self.seq = 0
        self.started_at: float | None = None
        self.exit_code: int | None = None
        self.lock = threading.Lock()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def external(self) -> bool:
        """A brain we didn't start (someone ran it in a terminal) is answering on its port."""
        if self.running():
            return False
        try:
            c = http.client.HTTPConnection("127.0.0.1", BRAIN_PORT, timeout=0.4)
            c.request("GET", "/status", headers={"Host": f"localhost:{BRAIN_PORT}"})
            r = c.getresponse()
            r.read()
            c.close()
            return r.status == 200
        except OSError:
            return False

    def log(self, text: str) -> None:
        if text.lstrip().startswith(IGNORED):
            text = "(heard speech that wasn't for Rocky; not shown)"   # don't keep what the room says
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, text))

    def start(self) -> str:
        if self.running():
            return "already running"
        if self.external():
            return "a brain started elsewhere is already running"
        env = dict(LAUNCH_ENV, PYTHONUNBUFFERED="1")
        self.log("── launcher: starting the server ──")
        self.proc = subprocess.Popen(
            [brain_python(), "-u", "-m", "brain.main"], cwd=HERE, env=env, text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.started_at = time.time()
        self.exit_code = None
        proc = self.proc

        def read() -> None:
            for line in proc.stdout:
                self.log(line.rstrip("\n"))
            code = proc.wait()
            self.exit_code = code
            self.log(f"── launcher: server stopped (exit code {code}) ──")

        threading.Thread(target=read, daemon=True).start()
        return "started"

    def stop(self) -> str:
        if not self.running():
            return "a brain started elsewhere: stop it where it runs" if self.external() else "not running"
        proc = self.proc
        self.log("── launcher: stopping the server ──")
        try:
            proc.stdin.write("quit\n")       # the brain's own console: shuts down cleanly
            proc.stdin.flush()
            proc.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            proc.terminate()
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=4)
        return "stopped"

    def send(self, line: str) -> None:
        if not self.running():
            raise ValueError("the server isn't running")
        line = line.replace("\n", " ").strip()
        if not line or len(line) > 300:
            raise ValueError("a command is 1 to 300 characters")
        self.log(f"> {line}")
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def state(self) -> dict:
        running = self.running()
        return {
            "running": running,
            "external": (not running) and self.external(),
            "pid": self.proc.pid if running else None,
            "uptime_s": round(time.time() - self.started_at) if running and self.started_at else None,
            "exit_code": self.exit_code,
            "log_seq": self.seq,
        }

    def lines_after(self, after: int) -> dict:
        with self.lock:
            lines = [t for s, t in self.lines if s > after]
            seq = self.seq
        return {"seq": seq, "lines": lines[-400:]}


brain = Brain()


def schema_meta() -> dict:
    """The settings schema for the page: kind, default and limits / choices of every setting."""
    out = {}
    for sec, keys in settings.SCHEMA.items():
        out[sec] = {}
        for k, (default, kind, extra) in keys.items():
            m = {"kind": kind, "default": default, "restart": (sec, k) in settings.RESTART_NEEDED}
            if kind in ("int", "float"):
                m["min"], m["max"] = extra
            elif kind == "choice":
                m["choices"] = list(extra)
            elif kind == "str":
                m["max_len"] = extra
            out[sec][k] = m
    return out


def env_value(key: str) -> str:
    """A key from server/.env, read fresh (so one added while this runs counts), else from the environment this was
    started in (exported in the shell); "" if neither has it."""
    found = ""
    try:
        for line in config._ENV_FILE.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == key:
                found = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return LAUNCH_ENV.get(key) or found


def spotify_key_set() -> bool:
    """Whether server/.env has a Spotify key (read fresh, so the page notices one added while this runs)."""
    return bool(env_value("SPOTIFY_CLIENT_ID") and env_value("SPOTIFY_CLIENT_SECRET"))


def active_name() -> str:
    return characters.name_of(settings.load()["character"]["id"])


def restart_brain() -> bool:
    """Restart a brain we started, so it picks up a new character. False if it isn't running here."""
    if not brain.running():
        return False
    brain.stop()
    time.sleep(0.5)
    brain.start()
    return True


def reload_brain() -> bool:
    """Tell a running brain the settings or the face pack changed. True if it took them."""
    if not (brain.running() or brain.external()):
        return False
    try:
        c, r = brain_request("POST", "/api/settings_reload", b"{}",
                             {"X-Rocky-Console": "1", "Content-Type": "application/json"})
        r.read()
        c.close()
        return r.status == 200
    except OSError:
        return False


def brain_request(method: str, path: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 10):
    c = http.client.HTTPConnection("127.0.0.1", BRAIN_PORT, timeout=timeout)
    h = {"Host": f"localhost:{BRAIN_PORT}", **(headers or {})}
    c.request(method, path, body=body, headers=h)
    return c, c.getresponse()


class Handler(BaseHTTPRequestHandler):
    server_version = "desk-robot"
    sys_version = ""

    def log_message(self, *args) -> None:
        pass

    # ── guards (same rules as the brain's own server) ──
    def _local(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in LOCAL_HOSTS:
            self._json(403, {"error": "forbidden"})
            return False
        # Another site's page can still make the browser fetch our URLs (an <img> pointed at /launcher/mics
        # starts a process each time). Opening the dashboard from a link is fine; anything else from another
        # site isn't.
        if (self.headers.get("Sec-Fetch-Site") == "cross-site"
                and self.headers.get("Sec-Fetch-Dest", "document") != "document"):
            self._json(403, {"error": "forbidden"})
            return False
        return True

    def _console(self) -> bool:
        origin = (self.headers.get("Origin") or "").lower()
        origin_host = origin.split("://", 1)[-1].rsplit(":", 1)[0].strip("[]")
        if self.headers.get("X-Rocky-Console") != "1" or (origin and origin_host not in LOCAL_HOSTS):
            self._json(403, {"error": "not the console"})
            return False
        return True

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= 64 * 1024:
            raise ValueError("bad content length")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def _reply(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")                          # no framing (clickjacking)
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._reply(code, "application/json", json.dumps(obj).encode())

    # ── routes ──
    def do_GET(self) -> None:
        global _face_enrollment_source
        if not self._local():
            return
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            try:
                page = PAGE.read_text().replace("{name}", active_name()).encode()
            except OSError as e:
                return self._reply(500, "text/plain", f"dashboard page missing: {e}".encode())
            return self._reply(200, "text/html; charset=utf-8", page)
        if url.path == "/launcher/state":
            # with the active personality's name, so an open page follows a switch or a rename without a reload
            return self._json(200, {**brain.state(), "name": active_name()})
        if url.path == "/launcher/log":
            try:
                after = int((q.get("after") or ["0"])[0])
            except ValueError:
                after = 0
            return self._json(200, brain.lines_after(after))
        if url.path == "/launcher/deskbot":
            try:
                registry = PersonRegistry()
                owner = registry.get_configured_owner()
                return self._json(200, {
                    "settings": DeskBotSettingsStore().load(),
                    "people": [dataclasses.asdict(person) for person in registry.list_people()],
                    "owner": None if owner is None else dataclasses.asdict(owner),
                })
            except (ValueError, RegistryError) as exc:
                return self._json(400, {"error": str(exc)})
        if url.path == "/launcher/face-enrollment/status":
            status = face_enrollment_status()
            if _face_enrollment_source == "robot":
                try:
                    touch_code, _, _ = _brain_json_post(
                        "/api/identity/enrollment/touch", {}
                    )
                    if touch_code >= 300:
                        raise OSError("robot enrollment session is no longer active")
                    connection, response = brain_request("GET", "/status")
                    try:
                        live_status = json.loads(response.read())
                    finally:
                        connection.close()
                    status["session"] = live_status.get("identity_enrollment")
                    status["robot_camera_available"] = (
                        live_status.get("frame_age_s") is not None
                        and live_status["frame_age_s"] <= 2.0
                    )
                except (OSError, ValueError, TypeError):
                    status["session"] = None
                    status["active"] = False
                    status["robot_camera_available"] = False
                    _face_enrollment_source = None
            elif _face_enrollment is not None:
                _face_enrollment.touch()
                status["session"] = _face_enrollment.status()
            return self._json(200, status)
        if url.path == "/launcher/face-enrollment/frame":
            if _face_enrollment_source == "robot":
                return self._proxy_get("/frame")
            session = _face_enrollment
            frame = None if session is None else session.preview()
            if frame is None:
                return self._json(503, {"error": "No active camera preview"})
            session.touch()
            return self._reply(200, "image/jpeg", frame)
        if url.path == "/launcher/deskbot/content":
            language = (q.get("language") or [""])[0]
            try:
                text, customized = EditablePhraseLibrary().read(language)
                return self._json(200, {"language": language, "content": text, "customized": customized})
            except ValueError as exc:
                return self._json(400, {"error": str(exc)})
        if url.path == "/launcher/deskbot/export":
            try:
                registry = PersonRegistry()
                libraries = EditablePhraseLibrary()
                owner = registry.get_configured_owner()
                bundle = {
                    "schema_version": 1,
                    "settings": DeskBotSettingsStore().export(),
                    "people": [dataclasses.asdict(person) for person in registry.list_people()],
                    "owner": None if owner is None else dataclasses.asdict(owner),
                    "content": {lang: json.loads(libraries.read(lang)[0]) for lang in ("de", "en")},
                }
                body = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
            except (ValueError, RegistryError) as exc:
                return self._json(400, {"error": str(exc)})
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="deskbot-backup.json"')
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path == "/launcher/settings":
            defaults_now = {k: getattr(config, k, None) for sec in ("listening", "voice") for k in settings.SCHEMA[sec]}
            return self._json(200, {"settings": settings.load(), "schema": schema_meta(),
                                    "computer_timezone": settings.computer_timezone(),
                                    "spotify_key": spotify_key_set(),
                                    "config_defaults": defaults_now})
        if url.path == "/launcher/faces":
            return self._json(200, {"packs": faces.list_packs(), "active": settings.load()["face"]["pack"],
                                    "emotions": faces.EMOTIONS, "fx": faces.FX})
        if url.path == "/launcher/characters":
            return self._json(200, {"characters": characters.list_all(), "active": settings.load()["character"]["id"],
                                    "emotions": faces.EMOTIONS, "acting_models": list(characters.ACTING_MODELS),
                                    "external": brain.external()})
        if url.path == "/launcher/geocode":
            try:
                return self._json(200, {"results": settings.geocode((q.get("q") or [""])[0])})
            except OSError as e:
                return self._json(502, {"error": f"place search failed: {e}"})
        if url.path == "/launcher/shortcuts":
            # the Apple Shortcuts on this Mac, so the page can offer them by name (Rocky may run only the ones picked)
            if sys.platform != "darwin":
                return self._json(200, {"shortcuts": [], "error": "Shortcuts are a Mac thing"})
            try:
                out = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=10).stdout
            except (OSError, subprocess.SubprocessError) as e:
                return self._json(502, {"error": f"couldn't list your shortcuts: {e}"})
            return self._json(200, {"shortcuts": [n.strip() for n in out.splitlines() if n.strip()][:200]})
        if url.path == "/launcher/mics":
            # this computer's inputs, for the mic picker. Asked in a fresh process (the brain's Python, which has
            # sounddevice): PortAudio only looks for devices when it starts, so this also finds one just plugged in
            try:
                out = subprocess.run([brain_python(), "-c", MIC_LIST], capture_output=True, text=True, timeout=15)
                return self._json(200, json.loads(out.stdout))
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                return self._json(200, {"mics": [], "error": f"couldn't list this computer's mics: {e}"})
        if url.path in ("/status", "/frame", "/stream"):
            return self._proxy_get(url.path)
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        global _face_enrollment_source
        if not self._local() or not self._console():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/launcher/start":
                return self._json(200, {"ok": True, "result": brain.start()})
            if path == "/launcher/stop":
                result = brain.stop()
                _face_enrollment_source = None
                return self._json(200, {"ok": True, "result": result})
            if path == "/launcher/restart":
                brain.stop()
                _face_enrollment_source = None
                time.sleep(0.5)
                return self._json(200, {"ok": True, "result": brain.start()})
            if path == "/launcher/console":
                brain.send(str(self._body().get("line", "")))
                return self._json(200, {"ok": True})
            if path == "/launcher/settings":
                new = settings.update(self._body().get("changes", {}))
                return self._json(200, {"ok": True, "settings": new, "applied_live": reload_brain()})
            if path == "/launcher/deskbot/settings":
                new = DeskBotSettingsStore().update(self._body().get("changes", {}))
                if new["privacy_mode"] or not new["recognition_enabled"]:
                    if _face_enrollment_source == "robot":
                        code, content_type, response_body = _brain_json_post(
                            "/api/identity/enrollment/cancel", {}
                        )
                        if code >= 300:
                            return self._reply(code, content_type, response_body)
                        _face_enrollment_source = None
                    _stop_face_enrollment()
                applied_live = False
                if brain.running() or brain.external():
                    payload = json.dumps({"changes": new}).encode("utf-8")
                    try:
                        connection, response = brain_request(
                            "POST",
                            "/api/identity/settings",
                            payload,
                            {
                                "X-Rocky-Console": "1",
                                "Content-Type": "application/json",
                                "Content-Length": str(len(payload)),
                            },
                        )
                    except OSError as exc:
                        return self._json(503, {"error": f"settings saved locally but could not update running brain: {exc}"})
                    response_body = response.read()
                    applied_live = response.status == 200
                    connection.close()
                    if not applied_live:
                        return self._reply(
                            response.status,
                            response.getheader("Content-Type") or "application/json",
                            response_body,
                        )
                return self._json(200, {"ok": True, "settings": new, "applied_live": applied_live})
            if path == "/launcher/deskbot/owner":
                body = self._body()
                if set(body) - {"person_id"}:
                    raise ValueError("unknown owner field")
                person_id = body.get("person_id")
                if person_id is not None and not isinstance(person_id, str):
                    raise ValueError("person_id must be a string or null")
                owner = PersonRegistry().set_configured_owner(person_id)
                return self._json(200, {"ok": True, "owner": None if owner is None else dataclasses.asdict(owner)})
            if path == "/launcher/deskbot/people":
                body = self._body()
                unknown = set(body) - {"display_name", "preferred_language", "role", "opted_in"}
                if unknown:
                    raise ValueError(f"unknown person field(s): {', '.join(sorted(unknown))}")
                opted_in = body.get("opted_in", False)
                if not isinstance(opted_in, bool):
                    raise ValueError("opted_in must be true or false")
                registry = PersonRegistry()
                person = registry.create_person(
                    body.get("display_name", ""),
                    preferred_language=body.get("preferred_language", "en"),
                    role=body.get("role", "colleague"),
                )
                if opted_in:
                    person = registry.record_opt_in(person.person_id, True)
                return self._json(201, {"ok": True, "person": dataclasses.asdict(person)})
            if path == "/launcher/deskbot/people/update":
                body = self._body()
                unknown = set(body) - {
                    "person_id", "display_name", "preferred_language", "role", "enabled", "opted_in",
                    "personalized_greetings_enabled",
                }
                if unknown:
                    raise ValueError(f"unknown person field(s): {', '.join(sorted(unknown))}")
                person_id = body.get("person_id")
                if not isinstance(person_id, str):
                    raise ValueError("person_id is required")
                registry = PersonRegistry()
                person = registry.get_person(person_id)
                if "display_name" in body:
                    person = registry.set_display_name(person_id, body["display_name"])
                if "preferred_language" in body:
                    person = registry.set_preferred_language(person_id, body["preferred_language"])
                if "role" in body:
                    person = registry.set_role(person_id, body["role"])
                if "enabled" in body:
                    person = registry.set_enabled(person_id, body["enabled"])
                if "opted_in" in body:
                    if body["opted_in"] is False:
                        registry.add_recognition_data_deleter(TemplateStore().delete_person)
                    person = registry.record_opt_in(person_id, body["opted_in"])
                if "personalized_greetings_enabled" in body:
                    person = registry.set_personalized_greetings_enabled(
                        person_id, body["personalized_greetings_enabled"]
                    )
                return self._json(200, {"ok": True, "person": dataclasses.asdict(person)})
            if path == "/launcher/deskbot/people/delete":
                person_id = self._body().get("person_id")
                if not isinstance(person_id, str):
                    raise ValueError("person_id is required")
                registry = PersonRegistry()
                registry.add_recognition_data_deleter(TemplateStore().delete_person)
                if not registry.delete_person(person_id):
                    return self._json(404, {"error": "person not found"})
                return self._json(200, {"ok": True})
            if path == "/launcher/deskbot/enroll":
                body = self._body()
                if set(body) != {"person_id", "consent_confirmed"}:
                    raise ValueError("person_id and consent_confirmed are required")
                if not isinstance(body["person_id"], str) or not body["person_id"].strip():
                    raise ValueError("person_id must be non-empty text")
                if body["consent_confirmed"] is not True:
                    raise ValueError("explicit enrollment confirmation is required")
                return self._proxy_post(
                    "/api/identity/enroll",
                    json.dumps(body).encode("utf-8"),
                )
            if path == "/launcher/face-enrollment/start":
                body = self._body()
                if body.get("source", "mac") == "robot":
                    if _face_enrollment is not None and _face_enrollment.status()["active"]:
                        raise ValueError("A camera workflow is already active; cancel it before starting another")
                    if _face_enrollment_source is not None:
                        raise ValueError("A camera workflow is already active; cancel it before starting another")
                    if not (brain.running() or brain.external()):
                        raise ValueError("Start the server explicitly and connect the robot camera before choosing this source")
                    remote_body = {key: value for key, value in body.items() if key not in {"source", "camera_index"}}
                    code, content_type, response_body = _brain_json_post(
                        "/api/identity/enrollment/start", remote_body
                    )
                    if code < 300:
                        _face_enrollment_source = "robot"
                    return self._reply(code, content_type, response_body)
                session = _start_face_enrollment(body)
                return self._json(200, {"ok": True, "session": session.status()})
            if path == "/launcher/face-enrollment/capture":
                body = self._body()
                if set(body) != {"step"}:
                    raise ValueError("step is required")
                if _face_enrollment_source == "robot":
                    code, content_type, response_body = _brain_json_post(
                        "/api/identity/enrollment/capture", body
                    )
                    return self._reply(code, content_type, response_body)
                session = _face_enrollment
                if session is None:
                    raise ValueError("No active enrollment session")
                return self._json(200, {"ok": True, "session": session.capture_pose(body["step"])})
            if path == "/launcher/face-enrollment/save":
                body = self._body()
                if set(body) != {"confirmed"}:
                    raise ValueError("final confirmation is required")
                if _face_enrollment_source == "robot":
                    code, content_type, response_body = _brain_json_post(
                        "/api/identity/enrollment/save", body
                    )
                    if code < 300:
                        _face_enrollment_source = None
                    return self._reply(code, content_type, response_body)
                session = _face_enrollment
                if session is None:
                    raise ValueError("No active enrollment session")
                result = session.save(body["confirmed"])
                _stop_face_enrollment(session)
                return self._json(201, {"ok": True, "person": result})
            if path == "/launcher/face-enrollment/cancel":
                if self._body():
                    raise ValueError("cancel does not accept fields")
                if _face_enrollment_source == "robot":
                    code, content_type, response_body = _brain_json_post(
                        "/api/identity/enrollment/cancel", {}
                    )
                    if code < 300:
                        _face_enrollment_source = None
                    return self._reply(code, content_type, response_body)
                _stop_face_enrollment()
                return self._json(200, {"ok": True})
            if path == "/launcher/deskbot/content":
                body = self._body()
                if set(body) - {"language", "content"}:
                    raise ValueError("unknown phrase-library field")
                EditablePhraseLibrary().save(body.get("language"), body.get("content"))
                return self._json(200, {"ok": True})
            if path == "/launcher/deskbot/content/reset":
                body = self._body()
                if set(body) - {"language"}:
                    raise ValueError("unknown phrase-library field")
                language = body.get("language")
                EditablePhraseLibrary().reset(language)
                return self._json(200, {"ok": True})
            if path == "/launcher/faces/save":
                body = self._body()
                pack_id = faces.save_custom(body.get("pack"), str(body.get("id") or "") or None)
                live = settings.load()["face"]["pack"] == pack_id and reload_brain()
                return self._json(200, {"ok": True, "id": pack_id, "applied_live": live})
            if path == "/launcher/faces/delete":
                pack_id = str(self._body().get("id", ""))
                faces.delete_custom(pack_id)
                if settings.load()["face"]["pack"] == pack_id:
                    settings.update({"face": {"pack": faces.DEFAULT_PACK}})
                    reload_brain()
                return self._json(200, {"ok": True})
            if path == "/launcher/characters/save":
                body = self._body()
                cid = characters.save(body.get("character"), str(body.get("id") or "") or None)
                restarted = settings.load()["character"]["id"] == cid and restart_brain()
                return self._json(200, {"ok": True, "id": cid, "restarted": restarted, "name": active_name()})
            if path == "/launcher/characters/use":
                cid = str(self._body().get("id") or "")
                if cid != characters.DEFAULT:
                    characters.load(cid)     # raises if it's missing or broken: don't switch to Rocky by accident
                settings.update({"character": {"id": cid}})
                return self._json(200, {"ok": True, "restarted": restart_brain(), "external": brain.external(),
                                        "name": active_name()})
            if path == "/launcher/characters/delete":
                cid = str(self._body().get("id") or "")
                characters.delete(cid)
                restarted = False
                if settings.load()["character"]["id"] == cid:
                    settings.update({"character": {"id": characters.DEFAULT}})
                    restarted = restart_brain()
                return self._json(200, {"ok": True, "restarted": restarted, "name": active_name()})
            if path == "/launcher/characters/draft":
                # the language model writes the character from a short description (takes 10-30 s)
                body = self._body()
                out = characters.draft(
                    str(body.get("name") or ""), str(body.get("description") or ""),
                    body.get("tts_model") in characters.ACTING_MODELS, faces.EMOTIONS,
                    base_url=env_value("LLM_BASE_URL") or "https://openrouter.ai/api/v1",
                    model=env_value("LLM_MODEL") or config.MODEL, api_key=env_value("LLM_API_KEY"))
                return self._json(200, {"ok": True, "draft": out})
            if path == "/launcher/characters/voice":
                # a sample of a Fish voice as MP3, played by the page (works with the server stopped)
                body = self._body()
                audio = characters.voice_sample(str(body.get("voice_id") or ""), str(body.get("tts_model") or ""),
                                                str(body.get("text") or ""), env_value("FISH_AUDIO_API_KEY"))
                return self._reply(200, "audio/mpeg", audio)
            if path.startswith("/api/"):
                return self._proxy_post(path)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except RegistryError as e:
            return self._json(400, {"error": str(e)})
        except FaceRecognitionError as e:
            return self._json(503, {"error": str(e)})
        except sqlite3.Error as e:
            return self._json(503, {"error": f"local recognition storage is unavailable: {e}"})
        except (OSError, RuntimeError) as e:
            return self._json(503, {"error": f"local camera workflow unavailable: {e}"})
        except (RecursionError, TypeError, AttributeError, UnicodeError) as e:     # absurdly nested JSON, wrong value types
            return self._json(400, {"error": f"bad request: {type(e).__name__}"})
        self._json(404, {"error": "no such control"})

    # ── passing the live parts through to the brain ──
    def _proxy_get(self, path: str) -> None:
        try:
            c, r = brain_request("GET", path, timeout=10 if path != "/stream" else 30)
        except OSError:
            return self._json(503, {"error": "the server is stopped", "stopped": True})
        if path != "/stream":
            body = r.read()
            c.close()
            return self._reply(r.status, r.getheader("Content-Type") or "application/octet-stream", body)
        self.send_response(r.status)
        self.send_header("Content-Type", r.getheader("Content-Type") or "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            while True:
                chunk = r.read1(65536) if hasattr(r, "read1") else r.read(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException):
            pass
        finally:
            c.close()

    def _proxy_post(self, path: str, body: bytes | None = None) -> None:
        if body is None:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= 64 * 1024:
                return self._json(400, {"error": "bad content length"})
            body = self.rfile.read(length)
        elif len(body) > 64 * 1024:
            return self._json(400, {"error": "bad content length"})
        try:
            c, r = brain_request("POST", path, body, {"X-Rocky-Console": "1", "Content-Type": "application/json",
                                                      "Content-Length": str(len(body))})
        except OSError:
            return self._json(503, {"error": "the server is stopped", "stopped": True})
        data = r.read()
        c.close()
        self._reply(r.status, r.getheader("Content-Type") or "application/json", data)


def main() -> None:
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    print(f"{config.ROBOT_NAME} dashboard: http://localhost:{PORT}/  (this computer only)")
    if os.environ.get("ROCKY_START_BRAIN") == "1":
        brain.start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_face_enrollment()
        if brain.running():
            brain.stop()


if __name__ == "__main__":
    main()
