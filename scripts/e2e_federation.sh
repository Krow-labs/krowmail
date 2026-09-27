#!/usr/bin/env bash
# 本地跨域验收。只打 127.0.0.1，不访问线上。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/data/krowmail/target}"
export TMPDIR="${TMPDIR:-/data/docker-tmp}"
mkdir -p "$TMPDIR"
WORK="$(mktemp -d "$TMPDIR/krowmail-fed-XXXX")"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

cd "$ROOT"
cargo build -p krowmail-server --quiet
BIN="$CARGO_TARGET_DIR/debug/krowmail-server"

python3 - "$WORK" <<'PY' &
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

work = sys.argv[1]
records = {}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        prefix = "/v1/domains/"
        if not self.path.startswith(prefix):
            self.send_response(404)
            self.end_headers()
            return
        domain = self.path[len(prefix):].split("?")[0]
        card = records.get(domain)
        if card is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(card).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/domains":
            self.send_response(404)
            self.end_headers()
            return
        n = int(self.headers.get("content-length", "0"))
        card = json.loads(self.rfile.read(n))
        records[card["domain"]] = card
        body = b'{"ok":true}'
        self.send_response(201)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("127.0.0.1", 19190), Handler).serve_forever()
PY
PIDS+=($!)

start_server() {
  local name="$1" domain="$2" segments="$3" port="$4" peers="$5"
  KROWMAIL_DOMAIN="$domain" \
  KROWMAIL_SEGMENT_COUNT="$segments" \
  KROWMAIL_DB="$WORK/$name.sqlite" \
  KROWMAIL_PUBLIC_ENDPOINT="http://127.0.0.1:$port" \
  KROWMAIL_ROOT="http://127.0.0.1:19190" \
  KROWMAIL_PEERS="$peers" \
  KROWMAIL_DEBUG_WIRE=1 \
  KROWMAIL_LISTEN="127.0.0.1:$port" \
    "$BIN" >"$WORK/$name.log" 2>&1 &
  PIDS+=($!)
}

start_server krow krow.cn 3 19101 "stranger.test=http://127.0.0.1:19103"
start_server lab lab.test 1 19102 ""
start_server stranger stranger.test 1 19103 ""

python3 - <<'PY'
import json, time, urllib.error, urllib.parse, urllib.request

def wait(url):
    for _ in range(50):
        try:
            with urllib.request.urlopen(url, timeout=1) as res:
                if res.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise SystemExit(f"not ready {url}")

def call(method, url, payload=None, headers=None, data=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data if data is not None else body, method=method)
    if payload is not None:
        req.add_header("content-type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            raw = res.read()
            return res.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read()
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw.decode()
        return err.code, parsed

for port in (19190, 19101, 19102, 19103):
    wait(f"http://127.0.0.1:{port}/healthz")

def card(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/.well-known/krowmail") as res:
        return json.load(res)

def register(domain, port, segments):
    found = card(port)
    status, _ = call("POST", "http://127.0.0.1:19190/v1/domains", {
        "domain": domain,
        "endpoint": f"http://127.0.0.1:{port}",
        "public_key": found["public_key"],
        "key_id": found["key_id"],
        "segment_count": segments,
    })
    if status != 201:
        raise SystemExit(f"register {domain} {status}")

register("krow.cn", 19101, 3)
register("lab.test", 19102, 1)

def send(port, sender, recipient, body, reply=None):
    payload = {"from": sender, "to": recipient, "body": body, "subject": "e2e"}
    if reply:
        payload["in_reply_to"] = reply
    status, out = call("POST", f"http://127.0.0.1:{port}/krowmail/v1/send", payload)
    if status != 200:
        raise SystemExit(f"send {sender} -> {recipient} failed {status} {out}")
    return out

def inbox(port, mailbox):
    query = urllib.parse.urlencode({"mailbox": mailbox})
    status, rows = call("GET", f"http://127.0.0.1:{port}/krowmail/v1/inbox?{query}")
    if status != 200:
        raise SystemExit(f"inbox {mailbox} {status} {rows}")
    return rows

friendly = send(19102, "agent@lab.test", "大风#PST#道哥@krow.cn", "hello-friendly")
rows = inbox(19101, "大风#PST#道哥@krow.cn")
hit = next(row for row in rows if row["body"] == "hello-friendly")
assert hit["wake"] is True and hit["quarantine"] is False, hit

numeric = send(19102, "agent@lab.test", "100440#100054#100095@krow.cn", "hello-numeric")
nrows = inbox(19101, "100440#100054#100095@krow.cn")
nhit = next(row for row in nrows if row["body"] == "hello-numeric")
assert nhit["wake"] is True and nhit["quarantine"] is False, nhit

reply = send(19101, "大风#PST#道哥@krow.cn", "agent@lab.test", "hello-reply", friendly["id"])
lrows = inbox(19102, "agent@lab.test")
rhit = next(row for row in lrows if row["body"] == "hello-reply")
assert rhit["wake"] is True and rhit["from"] == "大风#PST#道哥@krow.cn", rhit

wire = friendly["debug_wire"]
tampered = wire["body"].replace("hello-friendly", "hello-friendlx").encode()
status, _ = call(
    "POST",
    "http://127.0.0.1:19101/krowmail/v1/inbound",
    headers={
        "content-type": "application/json",
        "content-digest": wire["content_digest"],
        "signature-input": wire["signature_input"],
        "signature": wire["signature"],
    },
    data=tampered,
)
if status != 401:
    raise SystemExit(f"tamper expected 401, got {status}")

send(19103, "spy@stranger.test", "大风#PST#道哥@krow.cn", "hello-stranger")
srows = inbox(19101, "大风#PST#道哥@krow.cn")
shit = next(row for row in srows if row["body"] == "hello-stranger")
assert shit["quarantine"] is True and shit["wake"] is False, shit
print("FEDERATION: PASS")
PY
