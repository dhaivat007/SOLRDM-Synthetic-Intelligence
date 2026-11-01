"""HTTP contracts run without sockets; a real loopback smoke runs when permitted."""
from http.client import HTTPConnection, HTTPMessage
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from solrdm_pi.server import Application, LocalServer, MAX_BODY, Settings, make_handler


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Application(self.directory.name)
        self.addCleanup(self.app.close)

    def request(self, method="GET", path="/api/status", body=None, headers=None, raw=None):
        if raw is None:
            raw = json.dumps(body).encode() if body is not None else b""
        values = {"Host": "127.0.0.1:8787", "X-SOLRDM-Token": self.app.token,
                  "Content-Length": str(len(raw)), "Content-Type": "application/json"}
        values.update(headers or {})
        handler = make_handler(self.app).__new__(make_handler(self.app))
        handler.command = method
        handler.path = path
        handler.requestline = f"{method} {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.headers = HTTPMessage()
        for key, value in values.items():
            if value is not None:
                handler.headers[key] = value
        handler.server = SimpleNamespace(server_port=8787)
        handler.rfile, handler.wfile = io.BytesIO(raw), io.BytesIO()
        handler.request()
        head, payload = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
        status = int(head.split(b" ", 2)[1])
        try:
            parsed = json.loads(payload)
        except (ValueError, UnicodeError):
            parsed = payload.decode()
        return status, parsed, head.decode()

    def test_api_requires_session_and_same_origin_and_expected_host(self):
        cases = ({"X-SOLRDM-Token": None}, {"X-SOLRDM-Token": "wrong"},
            {"Origin": "https://evil.example"}, {"Host": "evil.example:8787"}, {"Host": "127.0.0.1:9999"})
        for headers in cases:
            with self.subTest(headers=headers):
                status, _, _ = self.request(headers=headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.request(headers={"Origin": "http://localhost:8787"})[0], 200)

    def test_non_ascii_token_is_rejected_cleanly(self):
        status, _, _ = self.request(headers={"X-SOLRDM-Token": "é-invalid"})
        self.assertEqual(status, 403)

    def test_settings_never_return_api_key_and_preserve_blank_password(self):
        secret = "test-secret-not-real"
        status, value, _ = self.request("POST", "/api/settings", {"provider_key": secret, "provider_model": "test-model"})
        self.assertEqual(status, 200)
        self.assertTrue(value["provider_key_set"])
        self.assertNotIn(secret, json.dumps(value))
        self.assertNotIn("provider_key", value)
        for path in ("/api/settings", "/api/status", "/api/diagnostics"):
            self.assertNotIn(secret, json.dumps(self.request(path=path)[1]))
        self.request("POST", "/api/settings", {"provider_key": ""})
        self.assertEqual(self.app.settings.get(private=True)["provider_key"], secret)
        self.assertEqual(self.app.settings.path.stat().st_mode & 0o777, 0o600)
        self.request("POST", "/api/settings", {"clear_provider_key": True})
        self.assertFalse(self.app.settings.get()["provider_key_set"])

    def test_settings_validates_types_and_persists(self):
        before = self.app.settings.get()
        for changes in ({"provider_vision": "true"}, {"preferred_backend": "shell"}, {"provider_url": "http://remote.example/v1"}, {"provider_key": "bad\nkey"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.request("POST", "/api/settings", changes)[0], 400)
                self.assertEqual(self.app.settings.get(), before)
        self.request("POST", "/api/settings", {"provider_model": "test", "provider_vision": True})
        restored = Settings(self.directory.name)
        self.assertTrue(restored.get()["provider_vision"])
        self.assertEqual(restored.get()["provider_model"], "test")

    def test_health_is_public_but_does_not_claim_model_connection(self):
        status, data, _ = self.request(path="/health", headers={"X-SOLRDM-Token": None})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        status, data, _ = self.request()
        self.assertEqual(status, 200)
        self.assertFalse(data["models"]["ready"])
        self.assertFalse(data["provider"]["verified"])
        self.assertFalse(data["engine"]["full_integration"])

    def test_body_size_transfer_encoding_invalid_json_and_top_level_types(self):
        for headers, raw, expected in (({"Content-Length": str(MAX_BODY + 1)}, b"", 413),
                ({"Content-Length": "-1"}, b"", 413), ({"Content-Length": "abc"}, b"", 413),
                ({"Transfer-Encoding": "chunked"}, b"", 400), ({}, b"not-json", 400),
                ({}, b"[]", 400), ({}, b'{"value":NaN}', 400), ({"Content-Length": "20"}, b"{}", 400)):
            with self.subTest(headers=headers, raw=raw):
                self.assertEqual(self.request("POST", "/api/settings", headers=headers, raw=raw)[0], expected)

    def test_deep_json_and_malformed_url_fail_cleanly(self):
        raw = b"[" * 1200 + b"0" + b"]" * 1200
        self.assertEqual(self.request("POST", "/api/chat", raw=raw)[0], 400)
        self.assertEqual(self.request(path="//[malformed")[0], 400)

    def test_offline_tool_endpoint_works_without_model(self):
        status, value, _ = self.request("POST", "/api/tools", {"name": "calculate", "args": {"expression": "2+2"}})
        self.assertEqual(status, 200)
        self.assertEqual(value["receipt"]["data"]["result"], 4)
        self.assertEqual(value["receipt"]["status"], "completed")
        self.assertEqual(self.request("POST", "/api/tools", {"name": "shell", "args": {}})[0], 400)

    def test_chat_without_model_is_actionable_failure(self):
        status, value, _ = self.request("POST", "/api/chat", {"text": "hello"})
        self.assertEqual(status, 400)
        self.assertIn("Load", value["error"])
        self.assertNotIn("text", value)

    def test_memory_round_trip_and_explicit_boolean_review(self):
        status, value, _ = self.request("POST", "/api/memory", {"text": "A user observation", "source": "lab notes"})
        self.assertEqual(status, 200)
        self.assertEqual(value["status"], "unreviewed")
        self.assertEqual(value["origin"], "user")
        record_id = value["id"]
        self.assertEqual(self.request("POST", "/api/memory/review", {"id": record_id, "approved": "false"})[0], 400)
        self.assertEqual(self.request("POST", "/api/memory/review", {"id": record_id, "approved": True})[1]["status"], "approved")
        self.assertEqual(self.request(path="/api/memory")[1]["items"][0]["source"], "lab notes")

    def test_assets_have_token_and_security_headers_and_no_arbitrary_file_access(self):
        root = Path(self.directory.name) / "assets"
        (root / "web").mkdir(parents=True)
        (root / "web/index.html").write_text('<meta name="token" content="__SOLRDM_TOKEN__">')
        with patch("solrdm_pi.server.ROOT", root):
            status, text, headers = self.request(path="/")
            self.assertEqual(status, 200)
            self.assertIn(self.app.token, text)
            self.assertIn("Content-Security-Policy:", headers)
            self.assertIn("X-Frame-Options: DENY", headers)
            self.assertIn("Cache-Control: no-store", headers)
            for path in ("/../../settings.json", "/settings.json", "/api/no-such-route"):
                self.assertEqual(self.request(path=path)[0], 404)


class RealHTTPTests(unittest.TestCase):
    def test_loopback_server_health_auth_and_calculator(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory)
            try:
                try:
                    server = LocalServer(("127.0.0.1", 0), make_handler(app))
                except PermissionError:
                    self.skipTest("Execution sandbox denies loopback sockets; CI runs this smoke test.")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    client = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
                    client.request("GET", "/health")
                    response = client.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertTrue(json.loads(response.read())["ok"])
                    client.request("GET", "/api/status")
                    response = client.getresponse()
                    self.assertEqual(response.status, 403)
                    response.read()
                    client.request("POST", "/api/tools", json.dumps({"name": "calculate", "args": {"expression": "6*7"}}),
                        {"X-SOLRDM-Token": app.token, "Content-Type": "application/json"})
                    response = client.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["receipt"]["data"]["result"], 42)
                    client.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=5)
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
