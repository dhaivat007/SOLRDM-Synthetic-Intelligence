"""Local GGUF registry, verified downloads, and a real llama.cpp process.

Only text-only GGUF language models are supported. A role is a user-facing
selection label, not a promise that a model's answers are correct.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

MAX_MODEL_BYTES = 6 * 1024 ** 3
MAX_UPLOAD_CHUNK = 8 * 1024 ** 2


class ModelReply(str):
    """A normal string that also records provider-reported incomplete output."""
    def __new__(cls, text, incomplete=False):
        reply = super().__new__(cls, text)
        reply.incomplete = bool(incomplete)
        return reply


CATALOG = [
    {"id": "qwen25-language-1.5b", "name": "Qwen 2.5 Instruct 1.5B · language",
     "role": "language", "size": 1117320736, "license": "Apache-2.0",
     "sha256": "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
     "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/dd26da440ef0330c47919d1ecae0966d24022222/qwen2.5-1.5b-instruct-q4_k_m.gguf",
     "source": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF",
     "notes": "Official Qwen conversion. Text only; can make factual and reasoning errors."},
    {"id": "qwen25-math-1.5b", "name": "Qwen 2.5 Math Instruct 1.5B · mathematics",
     "role": "mathematics", "size": 986048544, "license": "Apache-2.0",
     "sha256": "336d6f6973034fea14fae3164649dd8d81fb1df06dee3aa12de26cfb04715759",
     "url": "https://huggingface.co/second-state/Qwen2.5-Math-1.5B-Instruct-GGUF/resolve/14a9fbcfbd3bb7ad26297d7725b790dce07ee51a/Qwen2.5-Math-1.5B-Instruct-Q4_K_M.gguf",
     "source": "https://huggingface.co/second-state/Qwen2.5-Math-1.5B-Instruct-GGUF",
     "notes": "Second State GGUF conversion of Qwen's mathematics model. Check answers with calculation tools."},
    {"id": "qwen25-small-0.5b", "name": "Qwen 2.5 Instruct 0.5B · small / test",
     "role": "language", "size": 491400032, "license": "Apache-2.0",
     "sha256": "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db",
     "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/6dd44a1fb35d11b5d1b28902876ce3cc9e882d0e/qwen2.5-0.5b-instruct-q4_k_m.gguf",
     "source": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF",
     "notes": "Lower memory use; substantially weaker answers than the 1.5B profiles."},
]


def _atomic_json(path: Path, value):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _name(value):
    if not isinstance(value, str) or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise ValueError("Model name must be at most 120 printable characters.")
    return value.strip()


def _role(value):
    if value not in {"language", "mathematics", "science", "research", "general"}:
        raise ValueError("Unknown model role.")
    return value


def _checksum(value):
    if not isinstance(value, str) or (value and not re.fullmatch(r"[0-9a-fA-F]{64}", value)):
        raise ValueError("SHA-256 must contain exactly 64 hexadecimal characters.")
    return value.lower()


def inspect_gguf(path: Path, expected_sha256=""):
    """Check the container header and every byte; llama.cpp validates tensors."""
    if not path.is_file():
        raise ValueError("Select an existing GGUF file.")
    size = path.stat().st_size
    if size < 24 or size > MAX_MODEL_BYTES:
        raise ValueError("GGUF file must be between 24 bytes and 6 GiB.")
    digest = hashlib.sha256()
    measured = 0
    with path.open("rb") as handle:
        header = handle.read(24)
        if header[:4] != b"GGUF" or struct.unpack("<I", header[4:8])[0] not in (2, 3):
            raise ValueError("This file is not a supported GGUF v2/v3 model.")
        digest.update(header)
        measured = len(header)
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            measured += len(chunk)
            if measured > MAX_MODEL_BYTES:
                raise ValueError("Model changed size or exceeds 6 GiB.")
            digest.update(chunk)
    if measured != size or path.stat().st_size != size:
        raise ValueError("The model file changed while it was being verified. Try again after copying finishes.")
    actual = digest.hexdigest()
    if expected_sha256 and not secrets.compare_digest(actual, expected_sha256):
        raise ValueError("Model SHA-256 does not match. The file was not registered.")
    return size, actual


def _public_url(url):
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url):
        raise ValueError("Enter a public HTTPS model URL.")
    parsed = urlsplit(url)
    try:
        valid_port = parsed.port in (None, 443)
    except ValueError:
        valid_port = False
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.fragment or not valid_port or "%" in parsed.hostname):
        raise ValueError("Cloud imports require a public HTTPS URL on port 443 without credentials.")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Cloud URLs must resolve only to public internet addresses.")
    return parsed, ips


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated address while keeping TLS hostname verification.

    Pinning the resolved address prevents a second DNS lookup from turning a
    public URL into a request to a private address.
    """
    def __init__(self, hostname, addresses, timeout=60):
        super().__init__(hostname, 443, timeout=timeout, context=ssl.create_default_context())
        self.addresses = addresses

    def connect(self):
        last_error = None
        for address in self.addresses:
            try:
                connection = socket.create_connection((address, 443), self.timeout)
                try:
                    self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
                except Exception:
                    connection.close()
                    raise
                return
            except OSError as exc:
                last_error = exc
        raise OSError("Could not connect to the public model host.") from last_error


class _NoRuntimeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # The bearer credential belongs only to this exact local process.
        return None


def _open_public(url):
    for _ in range(6):
        parsed, addresses = _public_url(url)
        connection = _PublicHTTPSConnection(parsed.hostname, addresses)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        try:
            connection.request("GET", target, headers={"User-Agent": "SOLRDM-Pi/0.9", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                response.close()
                connection.close()
                if not location:
                    raise ValueError("Model host returned a redirect without a destination.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                response.close()
                connection.close()
                raise ValueError(f"Model host returned HTTP {response.status}.")
            if response.getheader("Content-Encoding", "identity").lower() not in ("identity", ""):
                raise ValueError("Compressed HTTP model downloads are not supported.")
            return connection, response
        except Exception:
            connection.close()
            raise
    raise ValueError("The model URL redirected too many times.")


class ModelManager:
    def __init__(self, data_dir, runtime_path=None, port=18081):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.model_dir = self.data_dir / "models"
        self.model_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.data_dir, 0o700)
        os.chmod(self.model_dir, 0o700)
        self.registry_path = self.data_dir / "models.json"
        self._lock = threading.RLock()
        self._chat_lock = threading.Lock()
        self._models = []
        if self.registry_path.exists():
            try:
                self._models = json.loads(self.registry_path.read_text(encoding="utf-8"))
                if not isinstance(self._models, list) or len(self._models) > 1000:
                    raise ValueError("Invalid model registry.")
                for record in self._models:
                    if (not isinstance(record, dict) or not isinstance(record.get("path"), str)
                            or not isinstance(record.get("id"), str) or not record.get("sha256")):
                        raise ValueError("Invalid model registry entry.")
                    _checksum(record["sha256"])
            except (ValueError, OSError) as exc:
                raise ValueError("Cannot read the model registry; preserve models.json and repair it before starting.") from exc
        self._jobs = {}
        self._process = None
        self._log = None
        self._generation = 0
        self._api_key = ""
        self._api_key_file = None
        self._state = "stopped"
        self._active = None
        self._error = None
        self.port = int(port)
        if not 1024 <= self.port <= 65535:
            raise ValueError("Invalid model runtime port.")
        candidates = [runtime_path, os.environ.get("SOLRDM_LLAMA_SERVER"),
                      Path(__file__).resolve().parents[1] / "runtime/bin/llama-server",
                      self.data_dir / "runtime/bin/llama-server", shutil.which("llama-server")]
        self.runtime_path = next((str(Path(p).expanduser().resolve()) for p in candidates
                                  if p and Path(p).expanduser().is_file() and os.access(Path(p).expanduser(), os.X_OK)), None)

    def list_models(self):
        with self._lock:
            return [dict(model, available=Path(model["path"]).is_file()) for model in self._models]

    def attach(self, path, name="", role="language", sha256=""):
        if not isinstance(path, (str, Path)) or not str(path):
            raise ValueError("Select an existing GGUF model file.")
        path = Path(path).expanduser().resolve()
        name, role, expected = _name(name), _role(role), _checksum(sha256)
        size, digest = inspect_gguf(path, expected)
        with self._lock:
            for record in self._models:
                if record["sha256"] == digest and record["path"] == str(path):
                    return dict(record)
            if len(self._models) >= 1000:
                raise ValueError("The model registry is full.")
            record = {"id": secrets.token_hex(8), "name": name or path.name[:120], "path": str(path),
                      "role": role, "size": size, "sha256": digest, "added_at": int(time.time()),
                      "verification": "GGUF header and SHA-256 checked; inference not yet tested"}
            self._models.append(record)
            try:
                _atomic_json(self.registry_path, self._models)
            except Exception:
                self._models.pop()
                raise
            return dict(record)

    def _new_job(self, name, role, expected, kind, total=None):
        with self._lock:
            if sum(j["state"] in ("uploading", "downloading", "verifying") for j in self._jobs.values()) >= 2:
                raise ValueError("Two model transfers are already running. Wait for one to finish.")
            while len(self._jobs) >= 100:
                old = next((key for key, job in self._jobs.items() if job["state"] in ("completed", "failed")), None)
                if old is None:
                    raise ValueError("Too many model transfers.")
                del self._jobs[old]
            job_id = secrets.token_hex(12)
            job = {"id": job_id, "kind": kind, "state": "uploading" if kind == "upload" else "downloading",
                   "name": _name(name), "role": _role(role), "sha256": _checksum(expected), "received": 0,
                   "total": total, "error": None, "model_id": None}
            self._jobs[job_id] = job
            return job

    def _part_path(self, job_id):
        return self.model_dir / (job_id + ".part")

    def job(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError("Unknown model transfer.")
            return dict(self._jobs[job_id])

    def list_jobs(self):
        with self._lock:
            return [dict(job) for job in self._jobs.values()]

    def begin_upload(self, name, total_bytes, sha256="", role="language"):
        if isinstance(total_bytes, bool) or not isinstance(total_bytes, int) or not 24 <= total_bytes <= MAX_MODEL_BYTES:
            raise ValueError("Select a GGUF file no larger than 6 GiB.")
        if shutil.disk_usage(self.model_dir).free < total_bytes + 64 * 1024 ** 2:
            raise ValueError("Not enough disk space to copy this model.")
        job = self._new_job(name, role, sha256, "upload", total_bytes)
        with self._part_path(job["id"]).open("xb") as handle:
            os.chmod(handle.name, 0o600)
        return dict(job)

    def upload_chunk(self, job_id, offset, data):
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_UPLOAD_CHUNK:
            raise ValueError("Each model upload chunk must contain 1 byte to 8 MiB.")
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["state"] != "uploading":
                raise ValueError("This model upload is not active.")
            if isinstance(offset, bool) or not isinstance(offset, int) or offset != job["received"]:
                raise ValueError("Upload offset does not match the bytes already received.")
            if offset + len(data) > job["total"]:
                raise ValueError("Upload is larger than the declared model size.")
            with self._part_path(job_id).open("ab") as handle:
                handle.write(data)
            job["received"] += len(data)
            return dict(job)

    def _complete(self, job_id):
        with self._lock:
            job = self._jobs[job_id]
            if job["state"] not in ("uploading", "downloading"):
                raise ValueError("This model transfer is no longer active.")
            if job["total"] is not None and job["received"] != job["total"]:
                raise ValueError("Model transfer ended before the declared file size was received.")
            job["state"] = "verifying"
        part = self._part_path(job_id)
        try:
            _, digest = inspect_gguf(part, job["sha256"])
            destination = self.model_dir / (digest + ".gguf")
            part.replace(destination)
            record = self.attach(destination, job["name"], job["role"], digest)
            with self._lock:
                job.update(state="completed", model_id=record["id"], sha256=digest)
            return record
        except Exception as exc:
            part.unlink(missing_ok=True)
            with self._lock:
                job.update(state="failed", error=str(exc))
            raise

    def finish_upload(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["state"] != "uploading":
                raise ValueError("This model upload is not active.")
        return self._complete(job_id)

    def cancel_transfer(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError("Unknown model transfer.")
            if job["state"] in ("uploading", "downloading"):
                job.update(state="failed", error="Model transfer was cancelled.")
                self._part_path(job_id).unlink(missing_ok=True)
            elif job["state"] == "verifying":
                raise ValueError("The file is being verified. Wait for verification to finish.")
            return dict(job)

    def import_url(self, url, name="", sha256="", role="language"):
        # Validate syntax synchronously; DNS/network work remains in the worker.
        if not isinstance(url, str) or not url.startswith("https://") or len(url) > 8192:
            raise ValueError("Enter a public HTTPS model URL.")
        job = self._new_job(name, role, sha256, "download")
        threading.Thread(target=self._download, args=(job["id"], url), daemon=True,
                         name="solrdm-model-download").start()
        return self.job(job["id"])

    def import_catalog(self, catalog_id):
        model = next((m for m in CATALOG if m["id"] == catalog_id), None)
        if not model:
            raise ValueError("Unknown model catalog entry.")
        return self.import_url(model["url"], model["name"], model["sha256"], model["role"])

    def _download(self, job_id, url):
        connection = response = None
        job = self._jobs[job_id]
        part = self._part_path(job_id)
        try:
            connection, response = _open_public(url)
            length = response.getheader("Content-Length")
            if length is not None:
                try:
                    total = int(length)
                except ValueError as exc:
                    raise ValueError("Model host returned an invalid file size.") from exc
                if not 24 <= total <= MAX_MODEL_BYTES:
                    raise ValueError("Model file must be no larger than 6 GiB.")
                if shutil.disk_usage(self.model_dir).free < total + 64 * 1024 ** 2:
                    raise ValueError("Not enough disk space to download this model.")
                with self._lock:
                    job["total"] = total
            deadline = time.monotonic() + 2 * 60 * 60
            with part.open("xb") as handle:
                os.chmod(part, 0o600)
                while True:
                    if time.monotonic() > deadline:
                        raise ValueError("Model download exceeded two hours. Try a faster connection or attach a local file.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    with self._lock:
                        if job["state"] != "downloading":
                            raise ValueError("Model download was cancelled.")
                        if not job["received"] and (len(chunk) < 24 or chunk[:4] != b"GGUF"
                                or struct.unpack("<I", chunk[4:8])[0] not in (2, 3)):
                            raise ValueError("The URL did not return a supported GGUF v2/v3 file.")
                        received = job["received"] + len(chunk)
                        if received > MAX_MODEL_BYTES or (job["total"] is not None and received > job["total"]):
                            raise ValueError("Model download exceeded its size limit.")
                        job["received"] = received
                    if shutil.disk_usage(self.model_dir).free < len(chunk) + 64 * 1024 ** 2:
                        raise ValueError("Not enough disk space to finish this model download.")
                    handle.write(chunk)
            self._complete(job_id)
        except Exception as exc:
            part.unlink(missing_ok=True)
            with self._lock:
                # Do not expose signed redirect URLs or request headers in errors.
                message = str(exc) if isinstance(exc, ValueError) else f"Download failed ({type(exc).__name__}). Check connectivity and the public URL."
                job.update(state="failed", error=message)
        finally:
            if response:
                response.close()
            if connection:
                connection.close()

    def status(self):
        with self._lock:
            if self._process and self._process.poll() is not None and self._state in ("loading", "ready"):
                self._state, self._error = "error", "The model runtime exited. Check available memory and model compatibility."
            return {"state": self._state, "ready": self._state == "ready", "model_id": self._active,
                    "model_name": next((m["name"] for m in self._models if m["id"] == self._active), None),
                    "runtime_available": bool(self.runtime_path), "error": self._error,
                    "context_tokens": 4096, "threads": 4, "local_only": True}

    def start(self, model_id):
        with self._lock:
            model = next((m for m in self._models if m["id"] == model_id), None)
            if not model:
                raise ValueError("Choose a registered model.")
            if not self.runtime_path:
                raise ValueError("llama-server is not installed. Install the SOLRDM Pi runtime package first.")
            if self._state in ("loading", "ready") and self._active == model_id:
                return self.status()
            self.stop()
            self._generation += 1
            generation = self._generation
            self._active, self._state, self._error = model_id, "loading", None
            threading.Thread(target=self._launch, args=(dict(model), generation), daemon=True,
                             name="solrdm-model-runtime").start()
            return self.status()

    def _launch(self, model, generation):
        try:
            inspect_gguf(Path(model["path"]), model["sha256"])
            with self._lock:
                if generation != self._generation:
                    return
                self._api_key = secrets.token_urlsafe(32)
                self._api_key_file = self.data_dir / ("runtime-key-" + secrets.token_hex(8) + ".txt")
                descriptor = os.open(self._api_key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as key_file:
                    key_file.write(self._api_key + "\n")
                log_path = self.data_dir / "llama-server.log"
                self._log = log_path.open("wb")
                os.chmod(log_path, 0o600)
                command = [self.runtime_path, "-m", model["path"], "--host", "127.0.0.1", "--port", str(self.port),
                           "-c", "4096", "-t", "4", "-ngl", "0", "--parallel", "1",
                           "--api-key-file", str(self._api_key_file)]
                self._process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=self._log,
                                                 stderr=subprocess.STDOUT, start_new_session=True)
                process = self._process
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                with self._lock:
                    if generation != self._generation:
                        return
                    if process.poll() is not None:
                        raise ValueError("llama-server could not load this model. Check compatibility, free RAM, and llama-server.log.")
                try:
                    health = self._runtime_json("/health", timeout=2)
                    if health.get("status") == "ok":
                        listing = self._runtime_json("/v1/models", timeout=2)
                        if not isinstance(listing.get("data"), list) or not listing["data"]:
                            raise ValueError("The model runtime did not return its authenticated model list.")
                        # An old unauthenticated server on this port must not
                        # satisfy readiness before our child reports bind failure.
                        try:
                            self._runtime_json("/v1/models", timeout=2, api_key="wrong-" + secrets.token_urlsafe(32))
                        except HTTPError as auth_error:
                            if auth_error.code not in (401, 403):
                                raise
                            auth_error.close()
                        else:
                            raise ValueError("The service on the model port does not enforce authentication.")
                        with self._lock:
                            if generation == self._generation and process.poll() is None:
                                self._state = "ready"
                        return
                except Exception:
                    pass
                time.sleep(0.5)
            raise ValueError("The model did not become ready within four minutes. Try the smaller model.")
        except Exception as exc:
            with self._lock:
                if generation == self._generation:
                    self._terminate()
                    self._state = "error"
                    self._error = str(exc) if isinstance(exc, ValueError) else f"Model startup failed ({type(exc).__name__})."

    def _terminate(self):
        if self._process:
            if self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5)
            self._process = None
        if self._log:
            self._log.close()
            self._log = None
        if self._api_key_file:
            self._api_key_file.unlink(missing_ok=True)
            self._api_key_file = None
        self._api_key = ""

    def stop(self):
        with self._lock:
            self._generation += 1
            self._terminate()
            self._state, self._active, self._error = "stopped", None, None
            self._api_key = ""
            return self.status()

    def close(self):
        self.stop()
        with self._lock:
            for job_id, job in self._jobs.items():
                if job["state"] in ("uploading", "downloading"):
                    self.cancel_transfer(job_id)

    def _runtime_json(self, path, payload=None, timeout=180, api_key=None):
        request = Request(f"http://127.0.0.1:{self.port}{path}",
                          data=json.dumps(payload).encode("utf-8") if payload is not None else None,
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " +
                                   (self._api_key if api_key is None else api_key)})
        # Never send the local runtime credential through a configured HTTP proxy.
        with build_opener(ProxyHandler({}), _NoRuntimeRedirect()).open(request, timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024 + 1)
            if len(body) > 4 * 1024 * 1024:
                raise ValueError("The model returned an oversized response.")
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError("The model runtime returned an invalid response.")
            return result

    def chat(self, messages, max_tokens=512, temperature=0.7, timeout=180, response_schema=None):
        if not isinstance(messages, list) or not 1 <= len(messages) <= 40:
            raise ValueError("Chat requires 1 to 40 text messages.")
        total = 0
        for message in messages:
            if (not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant"}
                    or not isinstance(message.get("content"), str)):
                raise ValueError("This local model accepts text messages only.")
            total += len(message["content"])
        if total > 20000:
            raise ValueError("This conversation is too long for the local model. Start a shorter conversation.")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 2048:
            raise ValueError("Invalid model response length.")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= temperature <= 2:
            raise ValueError("Invalid sampling temperature.")
        if response_schema is not None:
            if not isinstance(response_schema, dict):
                raise ValueError("The model response schema must be a JSON object.")
            try:
                encoded_schema = json.dumps(response_schema, allow_nan=False)
            except (TypeError, ValueError, RecursionError) as exc:
                raise ValueError("The model response schema must contain valid JSON.") from exc
            if len(encoded_schema) > 20000:
                raise ValueError("The model response schema exceeds 20,000 characters.")
        if not self._chat_lock.acquire(blocking=False):
            raise ValueError("The local model is already answering. Wait for it to finish.")
        try:
            if not self.status()["ready"]:
                raise ValueError("Load a model and wait until it is ready before chatting.")
            generation = self._generation
            try:
                payload = {
                    "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
                    "stream": False}
                if response_schema is not None:
                    payload["response_format"] = {"type": "json_schema", "json_schema": {
                        "name": "solrdm_action", "strict": True, "schema": response_schema}}
                result = self._runtime_json("/v1/chat/completions", payload, timeout=timeout)
            except Exception as exc:
                raise ValueError("The local model could not finish this request. Try a shorter message or check runtime status.") from exc
            if generation != self._generation:
                raise ValueError("The model changed while answering. Send the message again.")
            choices = result.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ValueError("The model returned no answer.")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError("The model runtime returned an invalid answer.")
            answer = message.get("content")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("The model returned an empty answer.")
            if len(answer) > 100000:
                raise ValueError("The model returned an oversized answer.")
            return ModelReply(answer.strip(), incomplete=choices[0].get("finish_reason") in {"length", "content_filter"})
        finally:
            self._chat_lock.release()
