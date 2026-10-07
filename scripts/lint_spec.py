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
    "shorthand-two",
    "shorthand-own-domain",
    "shorthand-other-domain",
    "shorthand-three-is-full",
    "decide-policy-allowlist",
    "decide-allowlist-listed",
}

# 信封可选卡片的上限：schema 与 krowmail-core 常量同值（core 侧由 tests/vectors.rs 对读）。
ENVELOPE_LIMITS = {"participants": 6, "mentions": 10}
# 0.3.0 协议位闭集：schema 与 krowmail-core::envelope 同值。
ENVELOPE_KINDS = ["ack", "close", "request", "decision"]
ENVELOPE_OUTCOMES = ["done", "declined", "needs_info", "expired", "withdrawn"]


def fail(msg: str) -> None:
    print(f"SPEC LINT: FAIL {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    envelope = json.loads((SPEC / "envelope.schema.json").read_text())
    if envelope.get("required") != ["id", "from", "to", "body", "created_at"]:
        fail("envelope required fields drifted")
    if envelope.get("additionalProperties") is not False:
        fail("envelope must stay closed (additionalProperties: false)")
    props = envelope["properties"]
    participant = envelope.get("$defs", {}).get("participant", {})
    if participant.get("additionalProperties") is not False or participant.get("required") != ["address"]:
        fail("envelope $defs.participant must be closed and require address")
    for key, cap in ENVELOPE_LIMITS.items():
        if props.get(key, {}).get("maxItems") != cap:
            fail(f"envelope.{key}.maxItems should be {cap}")
        if props[key].get("items") != {"$ref": "#/$defs/participant"}:
            fail(f"envelope.{key} items must be the participant card")
    if props.get("cc", {}).get("type") != "boolean":
        fail("envelope.cc should be boolean")
    # 0.3.0 协议位：闭集与 core 常量同值（core 侧由 tests/vectors.rs 对读）。
    if props.get("kind", {}).get("enum") != ENVELOPE_KINDS:
        fail(f"envelope.kind enum should be {ENVELOPE_KINDS}")
    if props.get("outcome", {}).get("enum") != ENVELOPE_OUTCOMES:
        fail(f"envelope.outcome enum should be {ENVELOPE_OUTCOMES}")
    for key in ("due_at", "decision_for"):
        if props.get(key, {}).get("type") != "string":
            fail(f"envelope.{key} should be string")
    if "kind" in envelope.get("required", []):
        fail("envelope.kind must stay optional（老对端按普通信处理）")
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
