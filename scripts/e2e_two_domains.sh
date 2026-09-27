#!/bin/bash
# Two local domains: MCP send, inbox, then a tampered body must be rejected.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export DOCKER_BUILDKIT=0
export TMPDIR="${TMPDIR:-/data/docker-tmp}"
mkdir -p "$TMPDIR"
docker info --format '{{.DockerRootDir}}' | grep -q '^/data/' || {
  echo "docker data-root is not under /data" >&2
  exit 1
}
docker compose -f deploy/compose.yaml up -d --build alpha beta
cleanup() { docker compose -f deploy/compose.yaml down >/dev/null 2>&1 || true; }
trap cleanup EXIT
for _ in $(seq 1 90); do
  if curl -sf http://127.0.0.1:19081/healthz >/dev/null && curl -sf http://127.0.0.1:19082/healthz >/dev/null; then
    break
  fi
  sleep 2
done
curl -sf http://127.0.0.1:19081/healthz >/dev/null
python3 - <<'PY'
import json, subprocess, urllib.parse, urllib.request

call = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "send_message",
        "arguments": {
            "from": "ann@alpha.test",
            "to": "bob@beta.test",
            "body": "hello from mcp",
        },
    },
}
payload = "\n".join([
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
    json.dumps(call),
    "",
])
proc = subprocess.run(
    ["docker", "compose", "-f", "deploy/compose.yaml", "--profile", "tools", "run", "--rm", "-T", "mcp"],
    input=payload,
    text=True,
    capture_output=True,
    check=True,
)
sent = None
for line in proc.stdout.splitlines():
    if '"id":2' in line or '"id": 2' in line:
        sent = json.loads(line)
if sent is None:
    raise SystemExit(f"mcp produced no result\n{proc.stdout}\n{proc.stderr}")
if sent.get("result", {}).get("isError"):
    raise SystemExit(sent)
body = json.loads(sent["result"]["content"][0]["text"])
wire = body["debug_wire"]
query = urllib.parse.urlencode({"mailbox": "bob@beta.test"})
with urllib.request.urlopen(f"http://127.0.0.1:19082/krowmail/v1/inbox?{query}") as resp:
    inbox = json.load(resp)
if not inbox or inbox[0]["body"] != "hello from mcp" or inbox[0]["wake"] is not True:
    raise SystemExit(f"inbox mismatch {inbox}")
tampered = wire["body"].replace("hello from mcp", "hello from mpc").encode()
req = urllib.request.Request(
    "http://127.0.0.1:19082/krowmail/v1/inbound",
    data=tampered,
    method="POST",
    headers={
        "content-type": "application/json",
        "content-digest": wire["content_digest"],
        "signature-input": wire["signature_input"],
        "signature": wire["signature"],
    },
)
try:
    urllib.request.urlopen(req)
    raise SystemExit("tampered body was accepted")
except urllib.error.HTTPError as err:
    if err.code != 401:
        raise SystemExit(f"expected 401, got {err.code} {err.read()!r}")
print("mcp send, inbox, and tamper rejection ok")
PY
echo "TWO DOMAINS: PASS"
