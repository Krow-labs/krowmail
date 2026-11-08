#!/usr/bin/env python3
"""Secret scan —— git-tracked 文件里不许出现真凭证（内容级闸；路径级由 GitHub push 规则 `krow-byo-push-guard` 拦）。

移植自母仓 `aullik5/krow:scripts/lint_secret_scan.py`（`lint.yml::Secret scan` strict job）。判据逐条沿用，去掉了
母仓为 json 存量设的 baseline 棘轮：本仓从零起步，没有存量可收编——出现即红。

为什么路径级规则不够：推送规则只拦 `.env*` / `*.pem` / `id_rsa*` / `.krow/**` 这些**文件名**；把一把 key 粘进
`.py` / `.md` / `.yaml` 的字面量里，规则一个字都不会说。母仓 2026-09-22 的三把泄漏 key 全部是这条路进去的。

判定（System 1 纯确定性，零 LLM）：
  1. 高精度形状 —— 无条件违规：
     - `sk-` + 32 位 hex（DeepSeek 官方 key 形状）
     - 火山 AccessKey：`AKLT` + 20 位以上 base64
     - GitHub token：`ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_` + 36 位，`github_pat_` + 22 位以上
     - PEM 私钥块头 `-----BEGIN … PRIVATE KEY-----` **且紧跟密钥体**（同行或其后 3 行内有 ≥40 字符的 base64 串）。
       Krow-labs 适配：只有块头、没有密钥体的字面量（格式化常量、检测规则、UI 文案、断言）不是泄漏，不红——
       真私钥粘进文件时密钥体一定紧跟块头，判别力不变。
  2. 候选形状 —— 熵值分级后才违规：`sk-user-`（krow cloud）/ `pk-pilot-`（SDK pilot）+ 长后缀，
     后缀 Shannon 熵 ≥ 3.5 bit/char 且字符类 ≥ 3；含 test / fake / dummy 等词面的一律视为假 key，不红。
  3. 豁免只有一种：同一行写 `secret-scan:allow`（刻意构造的高熵假 key 用；留痕可 review）。

用法：
  python3 scripts/lint_secret_scan.py                 # 扫 git ls-files，违规 exit 1
  python3 scripts/lint_secret_scan.py --scan-dir DIR  # 扫一棵目录树（构建产物出口断言），不走 git

病理形态用例：scripts/tests/test_lint_secret_scan.py。
"""
from __future__ import annotations

import argparse
import hashlib
import math
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 2026-11-08 Krow-labs 全仓对齐：母仓是 Python 单语种，Krow-labs 还有 Rust / Go / Swift / TS / Kotlin / 小程序 /
#: Dockerfile / k8s 清单——凭证粘进这些源码字面量同样一个字都不会被路径级规则拦。后缀表按组织内实际语言扩成超集，
#: 判据一字不改（只是多扫文件，不会少红）。
SCAN_SUFFIXES: tuple[str, ...] = (
    ".py", ".json", ".yaml", ".yml", ".md", ".toml", ".ini", ".cfg", ".env", ".txt", ".sh", ".ps1",
    ".js", ".ts", ".mjs", ".html", ".css", ".mdc", ".env.example",
    ".rs", ".go", ".swift", ".kt", ".kts", ".java", ".tsx", ".jsx", ".cjs", ".mts", ".cts", ".vue",
    ".wxml", ".wxss", ".wxs", ".xml", ".plist", ".gradle", ".properties", ".conf", ".sql", ".graphql",
    ".proto", ".tf", ".bat", ".cmd", ".zsh", ".bash", ".m", ".mlx", ".rb", ".php", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".dart", ".lua", ".r", ".ipynb", ".csv",
)
ALLOW_PRAGMA = "secret-scan:allow"

HIGH_PRECISION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("deepseek-key", re.compile(r"\bsk-[0-9a-f]{32}\b")),
    ("volc-access-key", re.compile(r"\bAKLT[A-Za-z0-9+/=]{20,}\b")),
    ("github-token", re.compile(r"\bgh[opusr]_[A-Za-z0-9]{36}\b")),
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("pem-private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
CANDIDATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sk-user-key", re.compile(r"\bsk-user-[A-Za-z0-9_\-]{24,}\b")),
    ("pk-pilot-key", re.compile(r"\bpk-pilot-[A-Za-z0-9_\-]{16,}\b")),
)
ENTROPY_THRESHOLD = 3.5
CHAR_CLASS_MIN = 3
FAKE_MARKERS: tuple[str, ...] = (
    "test", "fake", "dummy", "smoke", "stub", "example", "invalid", "placeholder", "redacted", "xxxx", "sample", "mock",
)


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    kind: str
    token_digest: str
    token_preview: str


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def char_classes(s: str) -> int:
    return sum((
        any(c.isupper() for c in s),
        any(c.islower() for c in s),
        any(c.isdigit() for c in s),
        any(not c.isalnum() for c in s),
    ))


def _suffix_after_prefix(token: str) -> str:
    for prefix in ("sk-user-", "pk-pilot-"):
        if token.startswith(prefix):
            return token[len(prefix):]
    return token


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


PEM_BODY = re.compile(r"[A-Za-z0-9+/=]{40,}")
PEM_BODY_LOOKAHEAD = 3


def _pem_has_body(lines: list[str], idx: int, m: re.Match[str]) -> bool:
    """块头之后（同行剩余部分或其后 PEM_BODY_LOOKAHEAD 行内）出现 base64 密钥体才算私钥块。"""
    tail = lines[idx][m.end():]
    if PEM_BODY.search(tail):
        return True
    return any(PEM_BODY.search(ln) for ln in lines[idx + 1 : idx + 1 + PEM_BODY_LOOKAHEAD])


def scan_text(rel_path: str, text: str) -> list[Violation]:
    out: list[Violation] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        line_no = idx + 1
        if ALLOW_PRAGMA in line:
            continue
        for kind, pat in HIGH_PRECISION_PATTERNS:
            for m in pat.finditer(line):
                if kind == "pem-private-key" and not _pem_has_body(lines, idx, m):
                    continue
                tok = m.group(0)
                out.append(Violation(rel_path, line_no, kind, _digest(tok), tok[:8] + "…"))
        for kind, pat in CANDIDATE_PATTERNS:
            for m in pat.finditer(line):
                tok = m.group(0)
                suffix = _suffix_after_prefix(tok)
                if any(mark in suffix.lower() for mark in FAKE_MARKERS):
                    continue
                if shannon_entropy(suffix) >= ENTROPY_THRESHOLD and char_classes(suffix) >= CHAR_CLASS_MIN:
                    out.append(Violation(rel_path, line_no, kind, _digest(tok), tok[:8] + "…"))
    return out


def _scannable(rel: str) -> bool:
    return rel.endswith(SCAN_SUFFIXES) or Path(rel).name in {".env", ".envrc", "Dockerfile"}


def scan_files(root: Path, rel_files: list[str]) -> list[Violation]:
    out: list[Violation] = []
    for rel in rel_files:
        if not _scannable(rel):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        out.extend(scan_text(rel.replace("\\", "/"), text))
    return out


def scan_dir_tree(scan_root: Path) -> list[Violation]:
    rel_files = [p.relative_to(scan_root).as_posix() for p in scan_root.rglob("*") if p.is_file()]
    return scan_files(scan_root, rel_files)


def git_tracked_files(root: Path) -> list[str]:
    res = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        print(f"[secret-scan] FATAL git ls-files: {res.stderr}", file=sys.stderr)
        sys.exit(2)
    return res.stdout.splitlines()


def _report(violations: list[Violation], where: str) -> None:
    print(f"[secret-scan] FAIL {where} 疑似携带真凭证：", file=sys.stderr)
    for v in violations:
        print(f"  {v.file}:{v.line_no} [{v.kind}] token={v.token_preview} digest={v.token_digest}", file=sys.stderr)
    print(
        "\n  怎么过：① 真凭证 → 立即从文件移除并在供应商侧作废轮换；凭据只走 CI secrets（`gh secret set`）/ 用户级 gitignored 文件，\n"
        f"  不经信件、不进代码；② 刻意构造的高熵假 key（测试 / 文档）→ 同一行加 `{ALLOW_PRAGMA}`；低熵占位符（含 test / fake / xxxx）本就不会触发，优先用它们。",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--scan-dir", type=Path, action="append", default=None, metavar="DIR",
                    help="扫一棵目录树（构建产物出口断言），不走 git；可重复")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.scan_dir:
        found: list[Violation] = []
        for d in args.scan_dir:
            if not d.is_dir():
                print(f"[secret-scan] FATAL --scan-dir 不存在：{d}", file=sys.stderr)
                return 2
            found.extend(scan_dir_tree(d))
        if found:
            _report(found, "目录树")
            return 1
        if not args.quiet:
            print(f"[secret-scan] OK 目录树干净：{', '.join(str(d) for d in args.scan_dir)}")
        return 0

    files = git_tracked_files(REPO_ROOT)
    found = scan_files(REPO_ROOT, files)
    if found:
        _report(found, "git-tracked 文件")
        return 1
    if not args.quiet:
        print(f"[secret-scan] OK {len(files)} 个 tracked 文件，无凭证形状")
    return 0


if __name__ == "__main__":
    sys.exit(main())
