#!/usr/bin/env python3
"""Lint krowmail spec artifacts. Prints SPEC LINT: PASS or exits 1."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "spec"

REQUIRED_IDS = {
    "chinese-three",
    "mixed-numeric",
    "fullwidth-mailto",
    "legacy-uuid",
    "legacy-uuid-padded",
    "wrong-domain",
    "legacy-not-uuid",
    "pure-digits",
    "zero-width",
    "bidi",
    "space",
    "slash",
    "reserved-admin",
    "name-pst-ok",
    "name-chinese-ok",
    "display-at",
    "display-fullwidth-hash",
    "display-ok",
    "decide-allow-external",
    "decide-flag-off",
    "decide-policy-own",
    "decide-policy-contacts",
    "decide-contacts-known",
    "decide-blocked",
    "decide-rate-daily",
    "decide-rate-hourly",
    "decide-rate-team",
    "decide-same-owner",
    "decide-flat-off",
    "uri-encoded",
}


def fail(msg: str) -> None:
    print(f"SPEC LINT: FAIL {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    envelope = json.loads((SPEC / "envelope.schema.json").read_text())
    if envelope.get("required") != ["id", "from", "to", "body", "created_at"]:
        fail("envelope required fields drifted")
    mcp = json.loads((SPEC / "mcp-tools.json").read_text())
    names = [tool["name"] for tool in mcp["tools"]]
    if names != ["send_message", "inbox", "read_message"]:
        fail(f"mcp tools {names}")
    for label in ("s2s.openapi.yaml", "root.openapi.yaml"):
        text = (SPEC / label).read_text()
        if "openapi:" not in text or "\npaths:" not in text:
            fail(f"{label} missing openapi or paths")
    if "/krowmail/v1/inbound:" not in (SPEC / "s2s.openapi.yaml").read_text():
        fail("s2s missing inbound")
    root = (SPEC / "root.openapi.yaml").read_text()
    for needle in ("/v1/domains/{domain}:", "/v1/domains:", "/v1/reports:"):
        if needle not in root:
            fail(f"root missing {needle}")
    vectors = json.loads((SPEC / "test-vectors" / "address.json").read_text())
    ids = {case["id"] for case in vectors["cases"]}
    missing = REQUIRED_IDS - ids
    if missing:
        fail(f"vectors missing {sorted(missing)}")
    if not (SPEC / "address.md").read_text().strip():
        fail("address.md empty")
    print("SPEC LINT: PASS")


if __name__ == "__main__":
    main()
