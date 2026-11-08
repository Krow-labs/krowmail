"""`scripts/lint_secret_scan.py` 的病理形态用例：坏实现（正则认不出 / 熵阈值失效 / 豁免泛化）过不了。"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_SPEC = importlib.util.spec_from_file_location(
    "lint_secret_scan", pathlib.Path(__file__).resolve().parents[1] / "lint_secret_scan.py"
)
lss = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = lss
_SPEC.loader.exec_module(lss)

# 下面这些是刻意构造的形状样本（不是任何真实凭证），行尾豁免标注只对「本文件被扫描」时生效，
# 对 scan_text 的直接调用无影响——用例里按需把标注放进被扫描的文本。
HEX32 = "0123456789abcdef0123456789abcdef"
GH36 = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
# PEM 块头拆成两段拼出来：各仓自带的旧版秘密扫描（只认块头、不看密钥体）扫到本文件时不会误报。
PEM_BEGIN = "-----BEGIN " + "{} PRIVATE KEY-----"
PEM_END = "-----END " + "{} PRIVATE KEY-----"


def kinds(text: str) -> list[str]:
    return [v.kind for v in lss.scan_text("x.py", text)]


def test_high_precision_shapes_are_unconditional():
    assert kinds(f'KEY = "sk-{HEX32}"') == ["deepseek-key"]  # secret-scan:allow
    assert kinds(f"token = 'ghp_{GH36}'") == ["github-token"]  # secret-scan:allow
    pem_body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" + "Q" * 12
    assert kinds(PEM_BEGIN.format("RSA") + "\n" + pem_body) == ["pem-private-key"]  # 块头 + 密钥体
    assert kinds("AKLT" + "Qm9ndXNCb2d1c0JvZ3VzQm9ndXM=") == ["volc-access-key"]  # secret-scan:allow


def test_candidate_shape_needs_high_entropy_and_mixed_classes():
    # 高熵、四类字符 → 红
    assert kinds("k = 'sk-user-" + "aZ9bY8cX7dW6eV5fU4gT3hS2iR1jQ0kP'") == ["sk-user-key"]  # secret-scan:allow；拆成两段：组员仓 G6 扫 scripts/ 里的 key 形状
    # 低熵词串 / 词面标记 → 不红（给正常开发造假 key 不制造摩擦）
    assert kinds("k = 'sk-user-" + "test_b1_entry_placeholder_key'") == []
    assert kinds("k = 'sk-user-" + "xxxxxxxxxxxxxxxxxxxxxxxxxxxx'") == []


def test_inline_allow_pragma_only_covers_its_own_line():
    text = f'a = "sk-{HEX32}"  # secret-scan:allow\nb = "sk-{HEX32}"'  # secret-scan:allow
    found = lss.scan_text("x.py", text)
    assert [v.line_no for v in found] == [2]


def test_report_never_prints_full_token():
    v = lss.scan_text("x.py", f'"sk-{HEX32}"')[0]  # secret-scan:allow
    assert len(v.token_preview) == 9 and v.token_preview.endswith("…")
    assert HEX32 not in v.token_preview and len(v.token_digest) == 16


def test_scan_dir_tree_covers_non_py_carriers(tmp_path: pathlib.Path):
    (tmp_path / "cfg.yaml").write_text(f"key: sk-{HEX32}\n", encoding="utf-8")  # secret-scan:allow
    (tmp_path / "blob.bin").write_bytes(b"\x00sk-" + HEX32.encode() + b"\x00")
    found = lss.scan_dir_tree(tmp_path)
    assert [v.file for v in found] == ["cfg.yaml"]


# ── 多语种后缀（2026-11-08 Krow-labs 全仓对齐加入）────────────────────────────

def test_multilang_suffixes_are_scanned(tmp_path):
    tok = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # 36 位  # secret-scan:allow
    for name in ("a.rs", "b.go", "c.swift", "d.kt", "e.tsx", "f.wxml", "g.plist", "h.gradle"):
        (tmp_path / name).write_text(f"let k = \"{tok}\"\n", encoding="utf-8")
    found = lss.scan_dir_tree(tmp_path)
    assert {v.file for v in found} == {"a.rs", "b.go", "c.swift", "d.kt", "e.tsx", "f.wxml", "g.plist", "h.gradle"}
    assert all(v.kind == "github-token" for v in found)


def test_pem_header_without_body_is_not_a_leak():
    """格式化常量 / 检测规则 / 断言里只有块头没有密钥体：不是泄漏（Krow-labs 适配）。"""
    src = (
        f'let (b, e) = ("{PEM_BEGIN.format("")}", "{PEM_END.format("")}");\n'.replace("  PRIVATE", " PRIVATE")
        + f'secret_rule("{PEM_BEGIN.format("OPENSSH")}"),\n'
        + f'assert!(s.starts_with("{PEM_BEGIN.format("RSA")}"));\n'
    )
    assert [v.kind for v in lss.scan_text("x.rs", src)] == []


def test_pem_header_with_body_is_a_leak():
    """块头后紧跟 base64 密钥体（同行或 3 行内）→ 红；隔太远不算。"""
    body = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7" + "x" * 20
    hdr, end = PEM_BEGIN.format("").replace("  ", " "), PEM_END.format("").replace("  ", " ")
    same_line = f'key = "{hdr}\\n{body}\\n{end}"\n'
    assert [v.kind for v in lss.scan_text("a.py", same_line)] == ["pem-private-key"]
    next_lines = PEM_BEGIN.format("RSA") + "\n" + body + "\n" + PEM_END.format("RSA") + "\n"
    assert [v.kind for v in lss.scan_text("b.pem.txt", next_lines)] == ["pem-private-key"]
    far = PEM_BEGIN.format("RSA") + "\n\n\n\n" + body + "\n"
    assert [v.kind for v in lss.scan_text("c.txt", far)] == []
