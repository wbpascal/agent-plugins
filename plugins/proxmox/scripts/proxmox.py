#!/usr/bin/env python3
"""Read-only client for Proxmox Datacenter Manager and Proxmox VE clusters.

The only reader of the settings file: secrets stay in this process. Sends GET requests only.
"""
import sys

if sys.version_info < (3, 11):
    sys.exit("proxmox.py needs Python 3.11 or later; this is Python %d.%d." % sys.version_info[:2])

import argparse
import dataclasses
import hashlib
import http.client
import json
import os
import ssl
import tomllib
import urllib.parse
from pathlib import Path

DOCS = "https://github.com/wbpascal/agent-plugins/blob/master/plugins/proxmox/README.md#settings"
EXAMPLE = Path(__file__).resolve().parent.parent / "settings.example.toml"
PLACEHOLDER = "PASTE-SECRET-HERE"
REDACT = {"token", "secret", "password", "ticket", "csrfpreventiontoken"}
LIMIT = 50_000
TIMEOUT = 10
PORTS = {"pdm": 8443, "cluster": 8006}


class Fail(Exception):
    """An error to show the user; never carries a secret."""


class CertMismatch(Exception):
    pass


@dataclasses.dataclass
class Source:
    name: str
    kind: str
    urls: list
    token_id: str
    secret: str = dataclasses.field(repr=False)
    fingerprints: list = dataclasses.field(default_factory=list)


def settings_path():
    if p := os.environ.get("AGENT_PROXMOX_SETTINGS"):
        return Path(p)
    if os.name == "nt":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "agent-plugins" / "proxmox.toml"


def norm_fp(fp):
    return fp.replace(":", "").strip().upper()


def colon_fp(hexfp):
    return ":".join(hexfp[i:i + 2] for i in range(0, len(hexfp), 2))


def norm_url(url, kind):
    if "://" not in url:
        url = "https://" + url
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        raise Fail(f"URL {url!r} must be https://host[:port]")
    host = f"[{u.hostname}]" if ":" in u.hostname else u.hostname
    return f"https://{host}:{u.port or PORTS[kind]}"


def make_source(name, kind, table):
    where = "[pdm]" if kind == "pdm" else f"[clusters.{name}]"
    if not isinstance(table, dict):
        raise Fail(f"{where} must be a table. See {DOCS}")
    urls = table.get("urls")
    if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
        raise Fail(f'{where} needs urls = ["https://host:port", ...]')
    for key in ("token_id", "secret"):
        value = table.get(key)
        if not isinstance(value, str) or not value.strip():
            raise Fail(f"{where} needs {key}")
        if not (value.strip().isascii() and value.strip().isprintable()):
            raise Fail(f"{where} {key} contains characters an HTTP header cannot carry, such as a line break")
    fps = table.get("fingerprints", [])
    if not isinstance(fps, list) or not all(isinstance(f, str) for f in fps):
        raise Fail(f"{where} fingerprints must be a list of strings")
    return Source(name, kind, [norm_url(u, kind) for u in urls], table["token_id"].strip(), table["secret"].strip(),
                  [norm_fp(f) for f in fps])


def load(path=None):
    path = path or settings_path()
    if not path.is_file():
        raise Fail(f"No settings file at {path}.\n"
                   f"Run `proxmox.py init` to create it from the example, then fill it in: {DOCS}")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise Fail(f"{path} is readable by other users. Run: chmod 600 {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise Fail(f"{path} is not valid TOML: {e}") from None
    sources = {}
    if "pdm" in data:
        sources["pdm"] = make_source("pdm", "pdm", data["pdm"])
    for name, table in data.get("clusters", {}).items():
        if name == "pdm":
            raise Fail("A cluster cannot be named 'pdm'.")
        sources[name] = make_source(name, "cluster", table)
    if not sources:
        raise Fail(f"{path} has neither [pdm] nor a [clusters.<name>] table. See {DOCS}")
    return sources


def auth_header(src):
    if src.secret == PLACEHOLDER:
        raise Fail(f"The secret of {src.name} is still the placeholder. Paste it into the settings file. See {DOCS}")
    if src.kind == "pdm":
        return f"PDMAPIToken={src.token_id}:{src.secret}"
    return f"PVEAPIToken={src.token_id}={src.secret}"


def http_get(url, target, header, fingerprints):
    """GET one URL. With fingerprints, the certificate is pinned before the token is sent."""
    u = urllib.parse.urlsplit(url)
    ctx = ssl.create_default_context()
    if fingerprints:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(u.hostname, u.port, timeout=TIMEOUT, context=ctx)
    try:
        conn.connect()
        if fingerprints:
            fp = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest().upper()
            if fp not in fingerprints:
                raise CertMismatch(f"certificate {colon_fp(fp)} is not in fingerprints")
        try:
            conn.request("GET", target, headers={"Authorization": header, "Accept": "application/json"})
        except (ValueError, UnicodeError):
            raise Fail("The token_id or secret contains characters an HTTP header cannot carry.") from None
        resp = conn.getresponse()
        return resp.status, resp.reason, resp.read()
    finally:
        conn.close()


def redact(value):
    if isinstance(value, dict):
        return {k: "<redacted>" if k.lower() in REDACT else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def target(path, params):
    path, _, query = path.strip().partition("?")
    path = "/" + path.strip("/")
    pairs = urllib.parse.parse_qsl(query) + list(params.items())
    return "/api2/json" + urllib.parse.quote(path) + ("?" + urllib.parse.urlencode(pairs) if pairs else "")


def error_detail(body):
    try:
        errors = json.loads(body).get("errors")
    except (ValueError, AttributeError):
        return ""
    return f": {json.dumps(redact(errors))[:500]}" if errors else ""


def get(src, path, params=None):
    """Return the `data` of a GET, trying each URL until one answers."""
    header, tgt, failures = auth_header(src), target(path, params or {}), []
    for url in src.urls:
        try:
            status, reason, body = http_get(url, tgt, header, src.fingerprints)
        except ssl.SSLCertVerificationError as e:
            failures.append(f"  {url}: {e.verify_message}; if the certificate is self-signed or its CA is not "
                            "trusted here, add its SHA-256 fingerprint to fingerprints")
            continue
        except (OSError, http.client.HTTPException, CertMismatch) as e:
            failures.append(f"  {url}: {e}")
            continue
        if status != 200:
            raise Fail(f"{src.name} {path}: HTTP {status} {reason}{error_detail(body)}")
        try:
            return redact(json.loads(body).get("data"))
        except (ValueError, AttributeError):
            raise Fail(f"{src.name} {path}: response is not a JSON object") from None
    raise Fail(f"{src.name}: no URL answered\n" + "\n".join(failures))


def render(data):
    if isinstance(data, list) and data and all(isinstance(x, str) for x in data):
        text = "\n".join(data)
    elif isinstance(data, list) and data and all(isinstance(x, dict) and set(x) == {"n", "t"} for x in data):
        text = "\n".join(x["t"] for x in data)
    else:
        text = json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True)
    if len(text) > LIMIT:
        text = (text[:LIMIT] + f"\n[truncated: showed {LIMIT} of {len(text)} characters. Narrow the query with a "
                "more specific path or parameters such as lastentries=, limit=, since=, typefilter=, type=.]")
    return text


def cmd_sources(sources):
    for s in sources.values():
        print(f"{s.name}\t{s.kind}\t{' '.join(s.urls)}")
    if "pdm" not in sources:
        return 0
    try:
        remotes = get(sources["pdm"], "/remotes/remote")
    except Fail as e:
        print(f"Could not list PDM remotes: {e}")
        return 1
    ids = {r["id"] for r in remotes if r.get("type") == "pve"}
    clusters = {s.name for s in sources.values() if s.kind == "cluster"}
    for rid in sorted(ids - clusters):
        print(f"{rid}\tremote\tin PDM only; no cluster entry, so no logs, HA or backup jobs")
    for name in sorted(clusters - ids):
        print(f"{name}\tcluster\tnot a PDM remote")
    return 0


def cmd_check(sources):
    failed = 0
    for s in sources.values():
        for url in s.urls:
            try:
                v = get(dataclasses.replace(s, urls=[url]), "/version")
                print(f"{s.name}\t{url}\tok, version {(v or {}).get('version', '?')}")
            except Fail as e:
                failed = 1
                print(f"{s.name}\t{url}\tFAILED {' '.join(str(e).split())}")
    return failed


def property_string(value):
    if isinstance(value, dict):
        return value
    out = {}
    for part in value.split(","):
        key, sep, val = part.partition("=")
        out.update({key: val} if sep else {"hostname": key})
    return out


def toml_block(name, urls, fps, existing):
    lines = [f"[clusters.{name}]", "urls = [" + ", ".join(json.dumps(u) for u in urls) + "]"]
    if fps:
        lines.append("fingerprints = [" + ", ".join(json.dumps(f) for f in fps) + "]")
    if existing:
        lines.append("# keep token_id and secret from your current entry")
    else:
        lines += ['token_id = "ai@pve!analysis"', f'secret = "{PLACEHOLDER}"']
    return "\n".join(lines)


def node_fingerprint(src, node):
    try:
        certs = get(src, f"/nodes/{node}/certificates/info")
    except Fail:
        return None
    by_file = {c.get("filename"): c.get("fingerprint") for c in certs or []}
    return by_file.get("pveproxy-ssl.pem") or by_file.get("pve-ssl.pem")


def cmd_discover(sources, names):
    blocks = []
    if "pdm" in sources and not names:
        for r in get(sources["pdm"], "/remotes/remote"):
            if r.get("type") != "pve":
                continue
            nodes = [property_string(n) for n in r.get("nodes", [])]
            urls = [norm_url(n["hostname"], "cluster") for n in nodes if n.get("hostname")]
            fps = [n["fingerprint"] for n in nodes if n.get("fingerprint")]
            blocks.append(toml_block(r["id"], urls, fps, r["id"] in sources))
    else:
        for name in names or [s.name for s in sources.values() if s.kind == "cluster"]:
            src = sources.get(name)
            if not src or src.kind != "cluster":
                raise Fail(f"No cluster named {name!r} in the settings.")
            port = urllib.parse.urlsplit(src.urls[0]).port
            nodes = [n for n in get(src, "/cluster/status") or [] if n.get("type") == "node"]
            urls = [norm_url(f"https://{h}:{port}" if ":" not in h else f"https://[{h}]:{port}", "cluster")
                    for h in (n.get("ip") or n["name"] for n in nodes)]
            fps = [fp for n in nodes if (fp := node_fingerprint(src, n["name"]))]
            blocks.append(toml_block(name, urls, fps, True))
    if not blocks:
        raise Fail("Nothing to discover: PDM lists no Proxmox VE remotes and the settings name no cluster.")
    print("# Check that these addresses are reachable from here, then merge them into the settings file.\n")
    print("\n\n".join(blocks))
    return 0


def cmd_init():
    path = settings_path()
    if path.exists():
        raise Fail(f"{path} already exists; edit it instead.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(EXAMPLE.read_text(encoding="utf-8"))
    print(f"Created {path}.\nOpen it in an editor, fill in URLs and token IDs, paste the secrets, "
          f"then run `proxmox.py check`. Details: {DOCS}")
    return 0


def parse_params(items):
    params = {}
    for p in items:
        key, sep, val = p.partition("=")
        if not sep:
            raise Fail(f"Parameter {p!r} must be key=value")
        params[key] = val
    return params


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="proxmox.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sources", help="list configured sources, and PDM remotes without a cluster entry")
    g = sub.add_parser("get", help="GET an API path from a source")
    g.add_argument("source", help="'pdm' or a cluster name")
    g.add_argument("path", help="API path below /api2/json, e.g. /cluster/status")
    g.add_argument("params", nargs="*", metavar="key=value", help="query parameters")
    sub.add_parser("check", help="test every URL of every source")
    d = sub.add_parser("discover", help="print settings entries for clusters, without secrets")
    d.add_argument("clusters", nargs="*", help="read these clusters' own node lists instead of PDM's")
    sub.add_parser("init", help="create the settings file from the example")
    sub.add_parser("path", help="print the settings file path")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "path":
            print(settings_path())
            return 0
        if args.cmd == "init":
            return cmd_init()
        sources = load()
        if args.cmd == "sources":
            return cmd_sources(sources)
        if args.cmd == "check":
            return cmd_check(sources)
        if args.cmd == "discover":
            return cmd_discover(sources, args.clusters)
        if args.source not in sources:
            raise Fail(f"No source {args.source!r}. Known: {', '.join(sources)}")
        print(render(get(sources[args.source], args.path, parse_params(args.params))))
        return 0
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
