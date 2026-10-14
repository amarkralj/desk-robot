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
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from brain import config, faces, settings  # noqa: E402  (all standard-library only)

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


IGNORED = "(heard, ignoring:"   # main.py's line for speech that wasn't meant for Rocky


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
        env = dict(os.environ, PYTHONUNBUFFERED="1")
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


def spotify_key_set() -> bool:
    """Whether server/.env has a Spotify key (read fresh, so the page notices one added while this runs)."""
    found = {}
    try:
        for line in config._ENV_FILE.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
                found[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return bool(found.get("SPOTIFY_CLIENT_ID") and found.get("SPOTIFY_CLIENT_SECRET"))


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
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._reply(code, "application/json", json.dumps(obj).encode())

    # ── routes ──
    def do_GET(self) -> None:
        if not self._local():
            return
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            try:
                page = PAGE.read_text().replace("{name}", config.ROBOT_NAME).encode()
            except OSError as e:
                return self._reply(500, "text/plain", f"dashboard page missing: {e}".encode())
            return self._reply(200, "text/html; charset=utf-8", page)
        if url.path == "/launcher/state":
            return self._json(200, brain.state())
        if url.path == "/launcher/log":
            try:
                after = int((q.get("after") or ["0"])[0])
            except ValueError:
                after = 0
            return self._json(200, brain.lines_after(after))
        if url.path == "/launcher/settings":
            defaults_now = {k: getattr(config, k, None) for sec in ("listening", "voice") for k in settings.SCHEMA[sec]}
            return self._json(200, {"settings": settings.load(), "schema": schema_meta(),
                                    "computer_timezone": settings.computer_timezone(),
                                    "spotify_key": spotify_key_set(),
                                    "config_defaults": defaults_now})
        if url.path == "/launcher/faces":
            return self._json(200, {"packs": faces.list_packs(), "active": settings.load()["face"]["pack"],
                                    "emotions": faces.EMOTIONS, "fx": faces.FX})
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
        if url.path in ("/status", "/frame", "/stream"):
            return self._proxy_get(url.path)
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._local() or not self._console():
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/launcher/start":
                return self._json(200, {"ok": True, "result": brain.start()})
            if path == "/launcher/stop":
                return self._json(200, {"ok": True, "result": brain.stop()})
            if path == "/launcher/restart":
                brain.stop()
                time.sleep(0.5)
                return self._json(200, {"ok": True, "result": brain.start()})
            if path == "/launcher/console":
                brain.send(str(self._body().get("line", "")))
                return self._json(200, {"ok": True})
            if path == "/launcher/settings":
                new = settings.update(self._body().get("changes", {}))
                return self._json(200, {"ok": True, "settings": new, "applied_live": reload_brain()})
            if path == "/launcher/faces/save":
                body = self._body()
                pack_id = faces.save_custom(body.get("pack"), body.get("id") or None)
                live = settings.load()["face"]["pack"] == pack_id and reload_brain()
                return self._json(200, {"ok": True, "id": pack_id, "applied_live": live})
            if path == "/launcher/faces/delete":
                pack_id = str(self._body().get("id", ""))
                faces.delete_custom(pack_id)
                if settings.load()["face"]["pack"] == pack_id:
                    settings.update({"face": {"pack": faces.DEFAULT_PACK}})
                    reload_brain()
                return self._json(200, {"ok": True})
            if path.startswith("/api/"):
                return self._proxy_post(path)
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except json.JSONDecodeError as e:
            return self._json(400, {"error": f"bad request: {e}"})
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

    def _proxy_post(self, path: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 <= length <= 64 * 1024:
            return self._json(400, {"error": "bad content length"})
        body = self.rfile.read(length)
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
        if brain.running():
            brain.stop()


if __name__ == "__main__":
    main()
