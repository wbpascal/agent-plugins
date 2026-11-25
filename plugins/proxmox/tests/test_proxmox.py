import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import proxmox  # noqa: E402

SECRET = "s3cret-value"


def source(kind="cluster", urls=("https://a:8006",), fps=()):
    return proxmox.Source("prod" if kind == "cluster" else "pdm", kind, list(urls), "ai@pve!analysis", SECRET, list(fps))


def reply(data, status=200, reason="OK"):
    return status, reason, json.dumps({"data": data}).encode()


class FakeHttp:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, target, header, fingerprints):
        self.calls.append((url, target, header))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class GetTest(unittest.TestCase):
    def test_auth_headers_per_kind(self):
        self.assertEqual(proxmox.auth_header(source("pdm")), f"PDMAPIToken=ai@pve!analysis:{SECRET}")
        self.assertEqual(proxmox.auth_header(source()), f"PVEAPIToken=ai@pve!analysis={SECRET}")

    def test_placeholder_secret_is_refused(self):
        src = source()
        src.secret = proxmox.PLACEHOLDER
        with self.assertRaisesRegex(proxmox.Fail, "placeholder"):
            proxmox.get(src, "/version")

    def test_falls_back_to_next_url_on_connection_error(self):
        fake = FakeHttp(OSError("refused"), reply({"version": "9.1"}))
        with mock.patch.object(proxmox, "http_get", fake):
            data = proxmox.get(source(urls=("https://a:8006", "https://b:8006")), "/version")
        self.assertEqual(data, {"version": "9.1"})
        self.assertEqual([c[0] for c in fake.calls], ["https://a:8006", "https://b:8006"])

    def test_http_error_does_not_fall_back(self):
        body = json.dumps({"data": None, "errors": {"vmid": "bad"}}).encode()
        fake = FakeHttp((400, "Bad Request", body))
        with mock.patch.object(proxmox, "http_get", fake), self.assertRaisesRegex(proxmox.Fail, "400.*vmid"):
            proxmox.get(source(urls=("https://a:8006", "https://b:8006")), "/x")
        self.assertEqual(len(fake.calls), 1)

    def test_errors_never_contain_the_secret(self):
        fake = FakeHttp(OSError("refused"), OSError("timeout"))
        with mock.patch.object(proxmox, "http_get", fake), self.assertRaises(proxmox.Fail) as cm:
            proxmox.get(source(urls=("https://a:8006", "https://b:8006")), "/version")
        self.assertIn("no URL answered", str(cm.exception))
        self.assertNotIn(SECRET, str(cm.exception))

    def test_secrets_are_redacted_recursively(self):
        data = [{"id": "r", "token": "t", "nodes": [{"Password": "p", "name": "n"}]}]
        with mock.patch.object(proxmox, "http_get", FakeHttp(reply(data))):
            out = proxmox.get(source(), "/remotes/remote")
        self.assertEqual(out, [{"id": "r", "token": "<redacted>", "nodes": [{"Password": "<redacted>", "name": "n"}]}])

    def test_target_merges_inline_query_and_params(self):
        self.assertEqual(proxmox.target("nodes/n1/journal?since=5", {"lastentries": "10"}),
                         "/api2/json/nodes/n1/journal?since=5&lastentries=10")


class HttpGetTest(unittest.TestCase):
    def test_fingerprint_mismatch_stops_before_the_request(self):
        conn = mock.MagicMock()
        conn.sock.getpeercert.return_value = b"cert"
        with mock.patch.object(proxmox.http.client, "HTTPSConnection", return_value=conn):
            with self.assertRaises(proxmox.CertMismatch):
                proxmox.http_get("https://a:8006", "/api2/json/version", "h", ["00"])
        conn.request.assert_not_called()

    def test_only_get_is_sent(self):
        conn = mock.MagicMock()
        conn.sock.getpeercert.return_value = b"cert"
        conn.getresponse.return_value.status = 200
        fp = hashlib.sha256(b"cert").hexdigest().upper()
        with mock.patch.object(proxmox.http.client, "HTTPSConnection", return_value=conn):
            proxmox.http_get("https://a:8006", "/api2/json/version", "h", [fp])
        self.assertEqual(conn.request.call_args.args[0], "GET")


class RenderTest(unittest.TestCase):
    def test_long_output_is_truncated_with_a_hint(self):
        text = proxmox.render(["x" * 100] * 1000)
        self.assertLess(len(text), proxmox.LIMIT + 300)
        self.assertIn("truncated", text)

    def test_task_log_lines_are_joined(self):
        self.assertEqual(proxmox.render([{"n": 1, "t": "a"}, {"n": 2, "t": "b"}]), "a\nb")


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "proxmox.toml"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, text):
        self.path.write_text(text)
        os.chmod(self.path, 0o600)

    def test_missing_file_names_path_and_docs(self):
        with self.assertRaises(proxmox.Fail) as cm:
            proxmox.load(self.path)
        self.assertIn(str(self.path), str(cm.exception))
        self.assertIn(proxmox.DOCS, str(cm.exception))

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_file_readable_by_others_is_refused(self):
        self.write('[clusters.a]\nurls = ["h"]\ntoken_id = "t"\nsecret = "s"\n')
        os.chmod(self.path, 0o644)
        with self.assertRaisesRegex(proxmox.Fail, "chmod 600"):
            proxmox.load(self.path)

    def test_loads_pdm_and_clusters_with_default_ports(self):
        self.write('[pdm]\nurls = ["pdm.local"]\ntoken_id = "t"\nsecret = "s"\n'
                   '[clusters.fra]\nurls = ["https://n1", "n2:9000"]\ntoken_id = "t"\nsecret = "s"\n'
                   'fingerprints = ["ab:cd"]\n')
        sources = proxmox.load(self.path)
        self.assertEqual(sources["pdm"].urls, ["https://pdm.local:8443"])
        self.assertEqual(sources["fra"].urls, ["https://n1:8006", "https://n2:9000"])
        self.assertEqual(sources["fra"].fingerprints, ["ABCD"])

    def test_cluster_named_pdm_is_refused(self):
        self.write('[clusters.pdm]\nurls = ["h"]\ntoken_id = "t"\nsecret = "s"\n')
        with self.assertRaisesRegex(proxmox.Fail, "cannot be named"):
            proxmox.load(self.path)

    def test_secret_with_line_break_is_refused_without_echoing_it(self):
        self.write(f'[clusters.a]\nurls = ["h"]\ntoken_id = "t"\nsecret = "{SECRET}\\nrest"\n')
        with self.assertRaises(proxmox.Fail) as cm:
            proxmox.load(self.path)
        self.assertIn("line break", str(cm.exception))
        self.assertNotIn(SECRET, str(cm.exception))


class DiscoverTest(unittest.TestCase):
    def test_pdm_remotes_become_cluster_tables(self):
        remotes = [{"id": "fra", "type": "pve", "nodes": ["hostname=10.0.0.1,fingerprint=AA:BB", "10.0.0.2:8006"]},
                   {"id": "old", "type": "pve", "nodes": ["n3"]},
                   {"id": "bk", "type": "pbs", "nodes": ["b1"]}]
        sources = {"pdm": source("pdm"), "old": source()}
        out = io.StringIO()
        with mock.patch.object(proxmox, "http_get", FakeHttp(reply(remotes))), contextlib.redirect_stdout(out):
            proxmox.cmd_discover(sources, [])
        text = out.getvalue()
        self.assertIn('[clusters.fra]\nurls = ["https://10.0.0.1:8006", "https://10.0.0.2:8006"]\n'
                      'fingerprints = ["AA:BB"]\ntoken_id = "ai@pve!analysis"', text)
        self.assertIn("[clusters.old]\nurls = [\"https://n3:8006\"]\n# keep token_id", text)
        self.assertNotIn("bk", text)
        self.assertNotIn(SECRET, text)


if __name__ == "__main__":
    unittest.main()
