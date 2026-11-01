"""Model handling boundaries; actual ARM64 inference is a separate CI check."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from solrdm_pi import models


def fixture_bytes():
    # This is a container-header fixture, not executable model weights.
    return b"GGUF" + struct.pack("<IQQ", 3, 0, 0) + b"container test bytes"


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.manager = models.ModelManager(self.root / "data", runtime_path=sys.executable)
        self.addCleanup(self.manager.close)
        self.file = self.root / "model.gguf"
        self.body = fixture_bytes()
        self.file.write_bytes(self.body)
        self.sha = hashlib.sha256(self.body).hexdigest()

    def test_attach_hash_persist_and_duplicate(self):
        record = self.manager.attach(str(self.file), "Example", "mathematics", self.sha)
        self.assertEqual(record["sha256"], self.sha)
        self.assertEqual(record["role"], "mathematics")
        self.assertIn("inference not yet tested", record["verification"])
        self.assertEqual(self.manager.attach(str(self.file))["id"], record["id"])
        reloaded = models.ModelManager(self.root / "data")
        self.addCleanup(reloaded.close)
        self.assertEqual(reloaded.list_models()[0]["id"], record["id"])
        self.assertEqual(self.manager.registry_path.stat().st_mode & 0o777, 0o600)

    def test_bad_header_and_hash_are_not_registered(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.manager.attach(str(self.file), sha256="a" * 64)
        self.file.write_bytes(b"<html>model login page</html>")
        with self.assertRaisesRegex(ValueError, "GGUF"):
            self.manager.attach(str(self.file))
        self.assertEqual(self.manager.list_models(), [])

    def test_model_metadata_validation(self):
        for kwargs in ({"name": "bad\nname"}, {"role": "shell"}, {"sha256": "x"}):
            with self.assertRaises(ValueError):
                self.manager.attach(str(self.file), **kwargs)

    def test_upload_order_and_exact_size(self):
        transfer = self.manager.begin_upload("uploaded.gguf", len(self.body), self.sha)
        self.manager.upload_chunk(transfer["id"], 0, self.body[:12])
        with self.assertRaisesRegex(ValueError, "offset"):
            self.manager.upload_chunk(transfer["id"], 0, b"again")
        with self.assertRaisesRegex(ValueError, "before"):
            self.manager.finish_upload(transfer["id"])
        self.manager.upload_chunk(transfer["id"], 12, self.body[12:])
        record = self.manager.finish_upload(transfer["id"])
        self.assertEqual(record["sha256"], self.sha)
        self.assertEqual(self.manager.job(transfer["id"])["state"], "completed")
        self.assertEqual(Path(record["path"]).name, self.sha + ".gguf")

    def test_upload_hash_failure_removes_partial(self):
        transfer = self.manager.begin_upload("uploaded.gguf", len(self.body), "b" * 64)
        self.manager.upload_chunk(transfer["id"], 0, self.body)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.manager.finish_upload(transfer["id"])
        self.assertEqual(self.manager.job(transfer["id"])["state"], "failed")
        self.assertFalse(self.manager._part_path(transfer["id"]).exists())
        self.assertEqual(self.manager.list_models(), [])

    def test_upload_declared_size_is_enforced(self):
        transfer = self.manager.begin_upload("model", 24)
        with self.assertRaisesRegex(ValueError, "larger"):
            self.manager.upload_chunk(transfer["id"], 0, self.body)
        with self.assertRaises(ValueError):
            self.manager.begin_upload("model", models.MAX_MODEL_BYTES + 1)
        with self.assertRaises(ValueError):
            self.manager.begin_upload("model", True)

    def test_cancel_releases_transfer_slot_and_removes_partial(self):
        job = self.manager.begin_upload("model", len(self.body))
        self.manager.upload_chunk(job["id"], 0, self.body[:24])
        self.manager.cancel_transfer(job["id"])
        self.assertFalse(self.manager._part_path(job["id"]).exists())
        self.assertEqual(self.manager.job(job["id"])["state"], "failed")
        with self.assertRaisesRegex(ValueError, "not active"):
            self.manager.upload_chunk(job["id"], 24, self.body[24:])

    def test_download_verifies_sha_and_persists(self):
        job = self.manager._new_job("Cloud model", "language", self.sha, "download")
        response = Response(self.body, headers={"Content-Length": str(len(self.body))})
        connection = Mock()
        with patch.object(models, "_open_public", return_value=(connection, response)):
            self.manager._download(job["id"], "https://example.org/model.gguf")
        self.assertEqual(self.manager.job(job["id"])["state"], "completed")
        self.assertEqual(self.manager.list_models()[0]["sha256"], self.sha)
        connection.close.assert_called_once()

    def test_download_truncated_body_rejected(self):
        job = self.manager._new_job("model", "language", "", "download")
        response = Response(self.body, headers={"Content-Length": str(len(self.body) + 100)})
        with patch.object(models, "_open_public", return_value=(Mock(), response)):
            self.manager._download(job["id"], "https://example.org/model.gguf")
        self.assertEqual(self.manager.job(job["id"])["state"], "failed")
        self.assertEqual(self.manager.list_models(), [])
        self.assertFalse(self.manager._part_path(job["id"]).exists())

    def test_download_rejects_html_and_oversized_headers(self):
        for response in (Response(b"<html>not model weights at all</html>"),
                         Response(self.body, headers={"Content-Length": str(models.MAX_MODEL_BYTES + 1)})):
            job = self.manager._new_job("model", "language", "", "download")
            with patch.object(models, "_open_public", return_value=(Mock(), response)):
                self.manager._download(job["id"], "https://example.org/model.gguf")
            self.assertEqual(self.manager.job(job["id"])["state"], "failed")
        self.assertEqual(self.manager.list_models(), [])

    def test_catalog_pins_weights_and_hashes(self):
        for entry in models.CATALOG:
            self.assertRegex(entry["url"], r"/resolve/[a-f0-9]{40}/")
            self.assertRegex(entry["sha256"], r"^[a-f0-9]{64}$")
            self.assertEqual(entry["license"], "Apache-2.0")
        with patch.object(self.manager, "import_url", return_value={"id": "transfer"}) as download:
            self.manager.import_catalog(models.CATALOG[0]["id"])
        download.assert_called_once_with(models.CATALOG[0]["url"], models.CATALOG[0]["name"],
                                         models.CATALOG[0]["sha256"], models.CATALOG[0]["role"])

    def test_runtime_missing_gives_actionable_error(self):
        self.manager.runtime_path = None
        record = self.manager.attach(str(self.file))
        with self.assertRaisesRegex(ValueError, "not installed"):
            self.manager.start(record["id"])
        self.assertFalse(self.manager.status()["ready"])

    def test_runtime_readiness_and_command_is_not_shell(self):
        record = self.manager.attach(str(self.file))
        self.manager._active = record["id"]
        self.manager._state = "loading"
        process = Mock()
        process.poll.return_value = None
        with patch.object(models.subprocess, "Popen", return_value=process) as popen:
            with patch.object(self.manager, "_runtime_json", side_effect=[
                {"status": "ok"}, {"data": [{"id": "model"}]},
                HTTPError("http://127.0.0.1/v1/models", 401, "Unauthorized", {}, None),
            ]) as runtime:
                self.manager._launch(record, self.manager._generation)
        self.assertTrue(self.manager.status()["ready"])
        command = popen.call_args.args[0]
        self.assertIn("127.0.0.1", command)
        self.assertIn(str(self.file), command)
        self.assertIn("--api-key-file", command)
        self.assertNotIn("--api-key", command)
        self.assertNotIn(self.manager._api_key, command)
        key_path = Path(command[command.index("--api-key-file") + 1])
        self.assertEqual(key_path.read_text().strip(), self.manager._api_key)
        self.assertEqual(key_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(runtime.call_args_list[1].args[0], "/v1/models")
        self.assertNotEqual(runtime.call_args_list[2].kwargs["api_key"], self.manager._api_key)
        self.assertFalse(popen.call_args.kwargs.get("shell", False))
        self.manager.stop()
        process.terminate.assert_called_once()
        self.assertFalse(self.manager.status()["ready"])
        self.assertFalse(key_path.exists())

    def test_another_unauthenticated_server_cannot_satisfy_readiness(self):
        record = self.manager.attach(str(self.file))
        self.manager._state = "loading"
        process = Mock()
        process.poll.side_effect = [None, 1, 1]
        with patch.object(models.subprocess, "Popen", return_value=process):
            with patch.object(self.manager, "_runtime_json", side_effect=[
                {"status": "ok"}, {"data": [{"id": "old-server"}]},
                {"data": [{"id": "old-server"}]},
            ]):
                with patch.object(models.time, "sleep"):
                    self.manager._launch(record, self.manager._generation)
        self.assertFalse(self.manager.status()["ready"])
        self.assertEqual(self.manager.status()["state"], "error")
        self.assertEqual(list(self.manager.data_dir.glob("runtime-key-*.txt")), [])

    def test_runtime_opener_disables_redirects_and_proxies(self):
        opener = Mock()
        opener.open.return_value = Response(b'{"status":"ok"}')
        self.manager._api_key = "private-test-token"
        with patch.object(models, "build_opener", return_value=opener) as build:
            self.assertEqual(self.manager._runtime_json("/health"), {"status": "ok"})
        self.assertEqual(build.call_args.args[0].proxies, {})
        redirect_handler = build.call_args.args[1]
        self.assertIsInstance(redirect_handler, models.HTTPRedirectHandler)
        self.assertIsNone(redirect_handler.redirect_request(None, None, 302, "Found", {}, "https://remote.example"))
        self.assertEqual(opener.open.call_args.args[0].get_header("Authorization"), "Bearer private-test-token")

    def test_mutated_model_cannot_start(self):
        record = self.manager.attach(str(self.file))
        self.file.write_bytes(self.body + b"changed")
        self.manager._state = "loading"
        with patch.object(models.subprocess, "Popen") as popen:
            self.manager._launch(record, self.manager._generation)
        popen.assert_not_called()
        self.assertEqual(self.manager.status()["state"], "error")
        self.assertIn("SHA-256", self.manager.status()["error"])

    def test_runtime_failure_does_not_claim_ready(self):
        record = self.manager.attach(str(self.file))
        self.manager._state = "loading"
        process = Mock()
        process.poll.return_value = 1
        with patch.object(models.subprocess, "Popen", return_value=process):
            self.manager._launch(record, self.manager._generation)
        self.assertFalse(self.manager.status()["ready"])
        self.assertIn("could not load", self.manager.status()["error"])

    def test_chat_requires_real_ready_state_and_extracts_answer(self):
        messages = [{"role": "user", "content": "What is 2 + 2?"}]
        with self.assertRaisesRegex(ValueError, "Load a model"):
            self.manager.chat(messages)
        self.manager._state = "ready"
        with patch.object(self.manager, "_runtime_json", return_value={"choices": [{"message": {"content": "4"}}]}) as call:
            self.assertEqual(self.manager.chat(messages), "4")
        self.assertEqual(call.call_args.args[0], "/v1/chat/completions")
        self.assertFalse(call.call_args.args[1]["stream"])

    def test_chat_rejects_multimodal_and_empty_runtime_answers(self):
        with self.assertRaisesRegex(ValueError, "text"):
            self.manager.chat([{"role": "user", "content": [{"type": "image"}]}])
        self.manager._state = "ready"
        with patch.object(self.manager, "_runtime_json", return_value={"choices": [{"message": {"content": ""}}]}):
            with self.assertRaisesRegex(ValueError, "empty"):
                self.manager.chat([{"role": "user", "content": "Hello"}])

    def test_chat_handles_malformed_message_objects(self):
        self.manager._state = "ready"
        for message in (None, [], "wrong"):
            with patch.object(self.manager, "_runtime_json", return_value={"choices": [{"message": message}]}):
                with self.assertRaisesRegex(ValueError, "invalid answer"):
                    self.manager.chat([{"role": "user", "content": "Hello"}])

    def test_chat_preserves_incomplete_finish_reasons(self):
        self.manager._state = "ready"
        for reason, incomplete in (("length", True), ("content_filter", True), ("stop", False), (None, False)):
            response = {"choices": [{"message": {"content": "Partial or complete text"}, "finish_reason": reason}]}
            with patch.object(self.manager, "_runtime_json", return_value=response):
                answer = self.manager.chat([{"role": "user", "content": "Hello"}])
            self.assertIsInstance(answer, str)
            self.assertEqual(answer, "Partial or complete text")
            self.assertEqual(answer.incomplete, incomplete)

    def test_chat_sends_strict_response_schema_when_requested(self):
        self.manager._state = "ready"
        schema = {"type": "object", "properties": {"answer": {"type": "string"}},
                  "required": ["answer"], "additionalProperties": False}
        response = {"choices": [{"message": {"content": '{"answer":"hello"}'}, "finish_reason": "stop"}]}
        with patch.object(self.manager, "_runtime_json", return_value=response) as runtime:
            answer = self.manager.chat([{"role": "user", "content": "Hello"}], response_schema=schema)
        self.assertEqual(answer, '{"answer":"hello"}')
        self.assertEqual(runtime.call_args.args[1]["response_format"], {
            "type": "json_schema", "json_schema": {"name": "solrdm_action", "strict": True, "schema": schema}})
        with patch.object(self.manager, "_runtime_json", return_value=response) as runtime:
            self.manager.chat([{"role": "user", "content": "Hello"}])
        self.assertNotIn("response_format", runtime.call_args.args[1])

    def test_chat_rejects_invalid_or_oversized_response_schema(self):
        for schema in ([], {"description": "x" * 20001}, {"bad": object()}, {"bad": float("nan")}):
            with patch.object(self.manager, "_runtime_json") as runtime:
                with self.assertRaisesRegex(ValueError, "schema"):
                    self.manager.chat([{"role": "user", "content": "Hello"}], response_schema=schema)
            runtime.assert_not_called()


class DownloadNetworkTests(unittest.TestCase):
    def test_urls_reject_credentials_schemes_and_nonstandard_ports(self):
        for url in ("http://example.com/x", "file:///etc/passwd", "https://user:pass@example.com/a",
                    "https://example.com:444/a", "https://example.com/#secret", "https://example.com:bad/a"):
            with self.assertRaises(ValueError):
                models._public_url(url)

    def test_dns_rejects_private_loopback_and_mixed_answers(self):
        for addresses in (["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"], ["::1"],
                          ["93.184.216.34", "192.168.1.1"]):
            dns = [(2, 1, 6, "", (address, 443)) for address in addresses]
            with patch.object(models.socket, "getaddrinfo", return_value=dns):
                with self.assertRaisesRegex(ValueError, "public"):
                    models._public_url("https://example.org/model.gguf")

    def test_public_addresses_are_returned_for_pinned_connect(self):
        with patch.object(models.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 443))]):
            parsed, addresses = models._public_url("https://example.org/model.gguf")
        self.assertEqual(parsed.hostname, "example.org")
        self.assertEqual(addresses, ["93.184.216.34"])

    def test_redirect_to_private_address_is_revalidated(self):
        connection = Mock()
        connection.getresponse.return_value = Response(status=302, headers={"Location": "https://127.0.0.1/private"})
        public = [(2, 1, 6, "", ("93.184.216.34", 443))]
        private = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch.object(models.socket, "getaddrinfo", side_effect=[public, private]):
            with patch.object(models, "_PublicHTTPSConnection", return_value=connection):
                with self.assertRaisesRegex(ValueError, "public"):
                    models._open_public("https://example.org/model.gguf")
        connection.close.assert_called()


if __name__ == "__main__":
    unittest.main()
