"""Loopback-only desktop web application with per-launch request authentication."""
import argparse
import fcntl
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import signal
import sys
import threading
import urllib.parse

from . import __version__
from .agent import Agent, AgentError, provider_endpoint
from .memory import MemoryStore
from .models import CATALOG, ModelManager
from .tools import TOOL_DEFINITIONS, execute_tool
from .workspace import WorkspaceStore
from .planning import TaskController
from .awareness import capability_snapshot, self_description


ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 24 * 1024 * 1024


class Settings:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "settings.json"
        self.lock = threading.RLock()
        self.value = {"runtime_path": "", "provider_url": "https://api.openai.com/v1", "provider_model": "",
                      "provider_key": "", "provider_vision": False, "preferred_backend": "local"}
        if self.path.exists():
            if self.path.stat().st_size > 65536:
                raise ValueError("Settings file is too large; restore a valid settings.json.")
            saved = json.loads(self.path.read_text())
            if not isinstance(saved, dict):
                raise ValueError("Invalid settings file.")
            self.update(saved, save=False)

    def get(self, private=False):
        with self.lock:
            value = dict(self.value)
        key = value.pop("provider_key")
        value["provider_key_set"] = bool(key)
        value["configured"] = bool(value["provider_url"] and value["provider_model"])
        if private:
            value["provider_key"] = key
        return value

    def update(self, changes, save=True):
        if not isinstance(changes, dict):
            raise ValueError("Settings must be an object.")
        with self.lock:
            value = dict(self.value)
            for key in value:
                if key not in changes:
                    continue
                item = changes[key]
                if key == "provider_vision":
                    if type(item) is not bool:
                        raise ValueError("provider_vision must be true or false.")
                else:
                    if not isinstance(item, str) or len(item) > 4096 or any(ord(c) < 32 for c in item):
                        raise ValueError("Settings contain an invalid value.")
                    item = item.strip()
                if key == "provider_key" and not item and save:
                    continue  # empty password form preserves an existing key
                value[key] = item
            if changes.get("clear_provider_key") is True:
                value["provider_key"] = ""
            if value["preferred_backend"] not in ("local", "provider"):
                raise ValueError("Choose local or provider as the chat backend.")
            if value["provider_url"]:
                provider_endpoint(value["provider_url"])
            if value["runtime_path"]:
                path = Path(value["runtime_path"]).expanduser()
                if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
                    raise ValueError("Runtime path must point to an executable llama-server file.")
                value["runtime_path"] = str(path.resolve())
            if save:
                temporary = self.path.with_suffix(".tmp")
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as stream:
                    json.dump(value, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self.path.chmod(0o600)
            self.value = value
        return self.get()


class Application:
    def __init__(self, data_dir, runtime_path=None):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        # Acquire ownership before recovery, which must never interrupt a live
        # executor merely because a second process tried to start on another port.
        self.instance_fd = os.open(self.data_dir / "application.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.instance_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.instance_fd)
            self.instance_fd = None
            raise ValueError("SOLRDM is already using this data directory. Open the running app or stop it first.") from None
        try:
            self._initialize(runtime_path)
        except Exception:
            self.close()
            raise

    def _initialize(self, runtime_path):
        self.settings = Settings(self.data_dir)
        self.models = ModelManager(self.data_dir, runtime_path=runtime_path or self.settings.get()["runtime_path"] or None)
        self.memory = MemoryStore(self.data_dir)
        self.workspace = WorkspaceStore(self.data_dir)
        self.agent = Agent(self.models, self.memory, lambda: self.settings.get(private=True), awareness=self.awareness)
        self.tasks = TaskController(self.agent, self.workspace, self.memory)
        self.token = secrets.token_urlsafe(32)
        self.bridge = None
        for candidate in (ROOT / "engine", ROOT.parent / "app/src/main/python"):
            if candidate.is_dir():
                sys.path.insert(0, str(candidate))
                break
        try:
            self.bridge = importlib.import_module("android_bridge")
            result = self.engine("status", "")
            if not result.get("ok"):
                self.bridge = None
        except (ImportError, ValueError, OSError):
            self.bridge = None

    def awareness(self):
        snapshot = capability_snapshot(self.models.status(), self.settings.get(), self.memory.stats(), self.workspace.stats())
        return {**snapshot, "description": self_description(snapshot)}

    def engine(self, command, payload):
        if not self.bridge:
            raise ValueError("The supplied SOLRDM Python engine is missing from this installation.")
        if isinstance(payload, dict):
            payload = json.dumps(payload, allow_nan=False)
        return json.loads(self.bridge.execute(str(self.data_dir / "engine.sqlite3"), command, payload))

    def status(self):
        settings = self.settings.get()
        return {"app": "SOLRDM Pi Agent", "version": __version__, "models": self.models.status(),
                "provider": {"configured": settings["configured"], "model": settings["provider_model"],
                             "vision": settings["provider_vision"], "verified": False},
                "preferred_backend": settings["preferred_backend"],
                "engine": {"available": self.bridge is not None, "full_integration": False,
                           "commands": list(self.bridge.COMMANDS) if self.bridge else []},
                "capabilities": {"pdf_text": bool(shutil.which("pdftotext")), "local_vision": False,
                                 "online_search": "Crossref and Wikipedia; internet required",
                                 "learning": "User-reviewed notebook, not model weight training",
                                 "task_actions": "Bounded search, calculation, simulation and notebook tools"}}

    def dispatch(self, method, path, query, data):
        if method == "GET":
            if path == "/api/status":
                return self.status()
            if path == "/api/awareness":
                return self.awareness()
            if path == "/api/tasks":
                return {"tasks": self.workspace.summaries(limit=100)}
            if path.startswith("/api/tasks/"):
                return {"task": self.workspace.get(int(path.removeprefix("/api/tasks/")))}
            if path == "/api/models":
                return {"models": self.models.list_models()}
            if path == "/api/catalog":
                return {"models": [dict(item, size_bytes=item["size"], description=item["notes"]) for item in CATALOG]}
            if path == "/api/settings":
                return self.settings.get()
            if path == "/api/tools":
                return {"tools": TOOL_DEFINITIONS}
            if path == "/api/memory":
                return {"items": self.memory.list()}
            if path == "/api/jobs":
                return {"jobs": self.models.list_jobs()}
            if path.startswith("/api/jobs/"):
                return self.models.job(path.removeprefix("/api/jobs/"))
            if path == "/api/diagnostics":
                return {**self.status(), "python": sys.version.split()[0], "platform": sys.platform,
                        "architecture": os.uname().machine, "data_dir": str(self.data_dir),
                        "disk_free_bytes": shutil.disk_usage(self.data_dir).free,
                        "engine_status": self.engine("status", "") if self.bridge else None}
        if method == "PUT" and path.startswith("/api/models/upload/"):
            job_id = path.removeprefix("/api/models/upload/")
            offset = int(query.get("offset", ["-1"])[0])
            return self.models.upload_chunk(job_id, offset, data)
        if method != "POST":
            raise LookupError("Route not found.")
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        if path == "/api/models/attach":
            return self.models.attach(data.get("path", ""), name=data.get("name", ""), role=data.get("role", "language"))
        if path == "/api/models/import":
            if data.get("catalog_id"):
                return self.models.import_catalog(data["catalog_id"])
            return self.models.import_url(data.get("url", ""), name=data.get("name", ""), sha256=data.get("sha256", ""), role=data.get("role", "language"))
        if path == "/api/models/upload/start":
            return self.models.begin_upload(data.get("name", ""), data.get("total_bytes"), sha256=data.get("sha256", ""), role=data.get("role", "language"))
        if path.startswith("/api/models/upload/") and path.endswith("/finish"):
            return self.models.finish_upload(path[len("/api/models/upload/"):-len("/finish")])
        if path == "/api/models/start":
            return self.models.start(data.get("model_id", ""))
        if path == "/api/models/stop":
            return self.models.stop()
        if path == "/api/models/transfers/cancel":
            return self.models.cancel_transfer(data.get("id", ""))
        if path == "/api/settings":
            old = self.settings.get()["runtime_path"]
            result = self.settings.update(data)
            if old != result["runtime_path"]:
                self.models.close()
                self.models = ModelManager(self.data_dir, runtime_path=result["runtime_path"] or None)
                self.agent.models = self.models
            return result
        if path == "/api/chat":
            return self.agent.run(data)
        if path == "/api/tasks/plan":
            return {"task": self.tasks.plan(data.get("goal"))}
        if path in ("/api/tasks/run", "/api/tasks/resume", "/api/tasks/retry"):
            return {"task": self.tasks.run(data.get("id"), path.rsplit("/", 1)[-1])}
        if path in ("/api/tasks/pause", "/api/tasks/cancel"):
            return {"task": getattr(self.workspace, path.rsplit("/", 1)[-1])(data.get("id"))}
        if path == "/api/tasks/reflect":
            return {"task": self.tasks.reflect(data.get("id"))}
        if path == "/api/tasks/delete":
            return self.workspace.delete(data.get("id"))
        if path == "/api/tools":
            return {"receipt": execute_tool(data.get("name"), data.get("args", {}), memory=self.memory)}
        if path == "/api/memory":
            return self.memory.add(data.get("text"), source=data.get("source", ""), origin="user")
        if path == "/api/memory/review":
            return self.memory.review(data.get("id"), data.get("approved"))
        if path == "/api/memory/delete":
            return self.memory.delete(data.get("id"))
        if path == "/api/engine":
            return self.engine(data.get("command"), data.get("payload", ""))
        raise LookupError("Route not found.")

    def close(self):
        if hasattr(self, "tasks"):
            self.tasks.close()
        if hasattr(self, "models"):
            self.models.close()
        if self.instance_fd is not None:
            descriptor = self.instance_fd
            self.instance_fd = None
            worker = self.tasks.worker if hasattr(self, "tasks") else None
            if worker and worker.is_alive():
                # A closing in-process app may still owe an actual receipt.
                # Keep its data ownership until that worker exits; process exit
                # releases the descriptor and startup then recovers interruption.
                def release_after_worker():
                    worker.join()
                    os.close(descriptor)
                threading.Thread(target=release_after_worker, daemon=True).start()
            else:
                os.close(descriptor)


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SOLRDM"
        sys_version = ""

        def log_message(self, fmt, *args):
            # URLs, headers, API keys, prompts, attachments and paths are not logs.
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def send_bytes(self, code, body, mime="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, code, value):
            self.send_bytes(code, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

        def request(self):
            host = self.headers.get("Host", "")
            expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in expected:
                return self.json(403, {"error": "Open the app through its localhost address."})
            try:
                parsed = urllib.parse.urlsplit(self.path)
            except ValueError:
                return self.json(400, {"error": "Invalid request path."})
            path = parsed.path
            if self.command == "GET" and path == "/health":
                return self.json(200, {"ok": True, "app": "SOLRDM Pi Agent", "version": __version__})
            if path.startswith("/api/"):
                token = self.headers.get("X-SOLRDM-Token", "")
                if not hmac.compare_digest(token.encode("utf-8"), app.token.encode("utf-8")):
                    return self.json(403, {"error": "Reload the app page to renew its local session."})
                origin = self.headers.get("Origin")
                if origin and origin not in {"http://" + h for h in expected}:
                    return self.json(403, {"error": "Cross-origin API access is blocked."})
                data = None
                if self.command != "GET":
                    if self.headers.get("Transfer-Encoding"):
                        return self.json(400, {"error": "Use a Content-Length request."})
                    try:
                        length = int(self.headers.get("Content-Length", "-1"))
                    except ValueError:
                        length = -1
                    maximum = 1024 * 1024 if self.command == "PUT" else MAX_BODY
                    if not 0 <= length <= maximum:
                        return self.json(413, {"error": "Request is missing its length or exceeds the size limit."})
                    raw = self.rfile.read(length)
                    if len(raw) != length:
                        return self.json(400, {"error": "Incomplete request body."})
                    try:
                        data = raw if self.command == "PUT" else json.loads(raw or b"{}", parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite number")))
                    except (UnicodeError, ValueError, RecursionError):
                        return self.json(400, {"error": "Expected valid JSON with finite numbers."})
                try:
                    value = app.dispatch(self.command, path, urllib.parse.parse_qs(parsed.query), data)
                    return self.json(200, value)
                except LookupError:
                    return self.json(404, {"error": "Item or route not found."})
                except (ValueError, TypeError, OSError, RuntimeError) as exc:
                    return self.json(400, {"error": str(exc)[:800]})
                except Exception:
                    return self.json(500, {"error": "The operation failed. Check Diagnostics and retry; no completion is being claimed."})
            if self.command != "GET":
                return self.json(404, {"error": "Route not found."})
            resources = {"/": "index.html", "/index.html": "index.html", "/style.css": "style.css", "/app.js": "app.js"}
            name = resources.get(path)
            if not name:
                return self.json(404, {"error": "Route not found."})
            file = ROOT / "web" / name
            if not file.is_file():
                return self.json(503, {"error": "Application assets are missing; reinstall the complete package."})
            body = file.read_bytes()
            if name == "index.html":
                body = body.replace(b"__SOLRDM_TOKEN__", app.token.encode())
            return self.send_bytes(200, body, (mimetypes.guess_type(name)[0] or "text/plain") + "; charset=utf-8")

        do_GET = request
        do_POST = request
        do_PUT = request
    return Handler


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser(description="SOLRDM Raspberry Pi desktop application")
    parser.add_argument("--data-dir", default=str(Path.home() / ".local/share/solrdm-pi/data"))
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--runtime-path")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    os.umask(0o077)
    app = Application(args.data_dir, args.runtime_path)
    server = LocalServer(("127.0.0.1", args.port), make_handler(app))
    def terminate(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, terminate)
    print(f"SOLRDM Pi Agent {__version__}: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
