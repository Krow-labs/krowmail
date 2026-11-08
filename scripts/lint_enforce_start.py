#!/usr/bin/env python3
"""enforce 起步闸 —— 反 warning-only 腐败（Krow-labs 各仓同一份文件，权威副本在 krow-bio）。

## 为什么需要这道闸

「先 warning / 先默认关，观察一阵再翻」听上去稳妥，实际是一条单行道：观察期没有
截止日期，就等于永久 warning。母仓 `aullik5/krow` 为此付过学费（"warning-only 起步"
已废止，见宪法 §0.2 F）。本仓的实测形态是：几十个灰度开关早已在现网全量，代码
默认值却还停在 false —— ConfigMap 丢一行，已全量的能力就静默退回旧行为，而且
没有任何东西会变红。

## 四条规则（配置在 `scripts/data/enforce_start.json`；`globs` / `exclude_globs` 用 fnmatch，`*` 跨目录）

1. **warning-only CI 步骤必须带期限**：workflow 里 `continue-on-error: true`、或检查
   命令后缀 `|| true` 的步骤，同一步骤块内（含紧邻的上方注释）必须写
   `enforce-by: YYYY-MM-DD` / `retire-when: <条件>` / `not-a-gate: <理由>` 之一。
   存量未标注的按计数棘轮（只降不升）。
2. **enforce-by 不许过期、不许画远期大饼**：已过期 → 红；距今超过 30 天 → 红。
   已兑现的写 `enforce-by-done: <日期>`（同一行），本闸跳过。续期 = 改日期的 diff，
   review 里看得见 —— 这是故意的。
3. **默认关的开关按名单棘轮**：配置里的正则认出「代码默认值 = 关」的开关。新出现的
   默认关开关若不在基线里、匹配行及紧贴其上的连续注释块里也没有上面三种标记之一
   → 红（只认紧贴的注释：一条标记不许顺带罩住相邻的开关）。开关翻成默认开、或删掉之后，基线里的旧名字也 → 红（跑 `--update-baseline`
   收紧）：棘轮只有收紧这一个方向。
4. **部署配置与代码默认值不许漂移**（仅配置了 `configmap_drift` 的仓）：ConfigMap 的
   `KEY: "true"|"false"`、Deployment env 的 `- name: KEY` / `value: "true"` 与代码默认值
   不一致 → 红；同一开关在两处代码里默认值不同
   → 红。从零起步，没有基线；确有理由的写进 `exempt`（键 → 理由），review 可见。

## 被拦了怎么过（权责对等：被拦的一方做什么能通过）

- 规则 1/3：要么直接 enforce 起步（去掉 `continue-on-error` / 默认值改成目标行为），
  要么在同一处注释写 `enforce-by:`（≤30 天）/ `retire-when:` / `not-a-gate:`。
- 规则 2：到期了就兑现（转 enforce，写 `enforce-by-done:`），或改 `retire-when:` 退役。
- 规则 3 的旧名字 / 规则 1 的计数变少：`python3 scripts/lint_enforce_start.py --update-baseline`。
- 规则 4：把代码默认值改成现网值（已全量的能力），或把 ConfigMap 改回代码值。

## 用法

    python3 scripts/lint_enforce_start.py                    # 校验（CI 硬闸）
    python3 scripts/lint_enforce_start.py --list             # 附默认关开关清单
    python3 scripts/lint_enforce_start.py --update-baseline  # 收紧基线（只降不升）
    python3 scripts/lint_enforce_start.py --init-baseline    # 首次落地：以当前存量建基线
    python3 scripts/lint_enforce_start.py --cross-repo       # 仅 krow-bio：比对各仓副本（需 gh）
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import fnmatch
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "scripts" / "data" / "enforce_start.json"
BASELINE_PATH = ROOT / "scripts" / "data" / "enforce_start_baseline.json"

#: 参与 `--cross-repo` 的仓（krow-bio 是权威副本，不在列）。
PEERS = ("krowworker", "krow-agent-service", "krowfiles")

MARKER = re.compile(r"enforce-by:|retire-when:|not-a-gate:")
ENFORCE_BY = re.compile(r"enforce-by:\s*(\d{4}-\d{2}-\d{2})")
MAX_ENFORCE_WINDOW_DAYS = 30
#: 本闸与其自测：自测里故意写着过期 / 远期的 enforce-by 用例。
SELF = {"scripts/lint_enforce_start.py", "scripts/test_lint_enforce_start.py"}
OFF = {"false", "0", "", "off", "no", "none"}
ON = {"true", "1", "on", "yes"}
SWALLOW = re.compile(r"(lint|check|test|clippy|fmt|audit|ruff|mypy)[^\n]*\|\|\s*true\b")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unmarked_steps: list[str] = field(default_factory=list)
    default_off: dict[str, str] = field(default_factory=dict)  # name -> 首个出处
    marked_off: set[str] = field(default_factory=set)
    code_defaults: dict[str, dict[str, str]] = field(default_factory=dict)  # name -> {出处: 值}


def _norm(v: str | None) -> str | None:
    s = (v or "").strip().strip("\"'").lower()
    if s in OFF:
        return "false"
    if s in ON:
        return "true"
    return None


def _tracked(root: pathlib.Path) -> list[pathlib.Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
        ).stdout.decode("utf-8", "replace")
        return [root / p for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        return ""


def _rel(root: pathlib.Path, p: pathlib.Path) -> str:
    return p.relative_to(root).as_posix()


# ── 规则 1：warning-only CI 步骤 ──────────────────────────────────────────


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block(lines: list[str], i: int) -> tuple[int, int]:
    """第 i 行所在的步骤 / job 块 [start, end)，start 向上吞掉紧邻的注释行。

    命中行在 `run: |` 这类块标量里时继续上溯到步骤本身，否则步骤头上的期限
    注释会被判成「不在块内」。
    """
    ind = _indent(lines[i])
    start = i
    while True:
        j = start - 1
        while j >= 0 and not (lines[j].strip() and _indent(lines[j]) < ind):
            j -= 1
        if j < 0:
            start = 0
            break
        start = j
        if re.search(r":\s*[|>][-+]?\s*$", lines[j].split("#", 1)[0]):
            ind = _indent(lines[j])
            continue
        break
    head = _indent(lines[start])
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    end = i + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() and _indent(ln) <= head:
            break
        end += 1
    return start, end


def check_workflows(root: pathlib.Path, cfg: dict, rep: Report) -> None:
    wf_dir = root / cfg.get("workflows_dir", ".github/workflows")
    for wf in sorted(wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []:
        lines = _read(wf).split("\n")
        seen: set[int] = set()
        for i, ln in enumerate(lines):
            code = ln.split("#", 1)[0]
            hit = re.match(r"\s*continue-on-error:\s*true\b", code) or SWALLOW.search(code)
            if not hit:
                continue
            s, e = _block(lines, i)
            if s in seen:
                continue
            seen.add(s)
            if not any(MARKER.search(x) for x in lines[s:e]):
                rep.unmarked_steps.append(f"{_rel(root, wf)}:{i + 1}")


# ── 规则 2：enforce-by 期限 ────────────────────────────────────────────────


def check_enforce_by(root: pathlib.Path, cfg: dict, rep: Report, today: _dt.date) -> None:
    exts = tuple(cfg.get("marker_exts", [".rs", ".py", ".yml", ".yaml", ".sh", ".toml", ".md"]))
    skip = set(cfg.get("marker_skip", []))
    for p in _tracked(root):
        rel = _rel(root, p)
        if not rel.endswith(exts) or rel in skip or rel in SELF:
            continue
        for n, ln in enumerate(_read(p).split("\n"), 1):
            if "enforce-by-done" in ln:
                continue
            for m in ENFORCE_BY.finditer(ln):
                try:
                    due = _dt.date.fromisoformat(m.group(1))
                except ValueError:
                    rep.errors.append(f"{rel}:{n}: enforce-by 日期不合法：{m.group(1)}")
                    continue
                if due < today:
                    rep.errors.append(
                        f"{rel}:{n}: enforce-by {due} 已过期 —— 兑现（转 enforce 并写 "
                        f"enforce-by-done:）或改 retire-when: 退役，禁止静默续期"
                    )
                elif (due - today).days > MAX_ENFORCE_WINDOW_DAYS:
                    rep.errors.append(
                        f"{rel}:{n}: enforce-by {due} 距今 {(due - today).days} 天，超过 "
                        f"{MAX_ENFORCE_WINDOW_DAYS} 天窗口 —— 远期承诺等于没有承诺"
                    )


# ── 规则 3/4：开关默认值 ──────────────────────────────────────────────────


COMMENT_LEAD = ("//", "#", "--", "*", "/*")


def _marked(lines: list[str], first: int, last: int) -> bool:
    """匹配所占的行 [first, last]（0 基）或紧贴其上的连续注释块里有期限标记。"""
    if any(MARKER.search(x) for x in lines[first : last + 1]):
        return True
    j = first - 1
    while j >= 0 and lines[j].lstrip().startswith(COMMENT_LEAD):
        if MARKER.search(lines[j]):
            return True
        j -= 1
    return False


def scan_flags(root: pathlib.Path, cfg: dict, rep: Report) -> None:
    files = _tracked(root)
    for spec in cfg.get("flags", []):
        rx = re.compile(spec["pattern"], re.S)
        name_rx = re.compile(spec.get("name_filter", r".*"))
        missing = spec.get("default_if_missing")
        excluded = spec.get("exclude_globs", [])
        for p in files:
            rel = _rel(root, p)
            if not any(fnmatch.fnmatch(rel, g) for g in spec["globs"]):
                continue
            if any(fnmatch.fnmatch(rel, g) for g in excluded):
                continue
            text = _read(p)
            lines = text.split("\n")
            for m in rx.finditer(text):
                name = m.group("name")
                if not name_rx.fullmatch(name):
                    continue
                raw = m.groupdict().get("default")
                val = _norm(raw if raw is not None else missing)
                if val is None:
                    continue
                line_no = text.count("\n", 0, m.start()) + 1
                last_no = text.count("\n", 0, m.end()) + 1
                where = f"{rel}:{line_no}"
                rep.code_defaults.setdefault(name, {})[where] = val
                if val != "false":
                    continue
                rep.default_off.setdefault(name, where)
                if _marked(lines, line_no - 1, last_no - 1):
                    rep.marked_off.add(name)


CM_ROW = re.compile(r"""^\s+(?P<key>[A-Z][A-Z0-9_]+):\s*["'](?P<val>[^"']*)["']""")
ENV_NAME = re.compile(r"^\s*-\s*name:\s*[\"']?(?P<key>[A-Z][A-Z0-9_]+)[\"']?\s*$")
ENV_VALUE = re.compile(r"""^\s*value:\s*["']?(?P<val>[^"'\s]*)["']?\s*$""")


def _deployed_values(text: str):
    """部署文件里的 (行号, 键, 值)：ConfigMap 的 ``KEY: "v"``，与 Deployment env 的
    ``- name: KEY`` + 下一行 ``value: v`` 两种写法都认。"""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = CM_ROW.match(ln)
        if m:
            yield i + 1, m.group("key"), m.group("val")
            continue
        m = ENV_NAME.match(ln)
        if m and i + 1 < len(lines):
            v = ENV_VALUE.match(lines[i + 1])
            if v:
                yield i + 2, m.group("key"), v.group("val")


def check_drift(root: pathlib.Path, cfg: dict, rep: Report) -> None:
    for name, where in sorted(rep.code_defaults.items()):
        if len(set(where.values())) > 1:
            detail = "、".join(f"{w}={v}" for w, v in sorted(where.items()))
            rep.errors.append(f"{name}: 同一开关在不同代码处默认值不一致（{detail}）")
    drift = cfg.get("configmap_drift")
    if not drift:
        return
    exempt = drift.get("exempt", {})
    for f in drift.get("files", []):
        for n, key, val in _deployed_values(_read(root / f)):
            if key not in rep.code_defaults:
                continue
            want = _norm(val)
            code = set(rep.code_defaults[key].values())
            if want is None or len(code) != 1 or want in code or key in exempt:
                continue
            (have,) = code
            rep.errors.append(
                f"{f}:{n}: {key}={want} 与代码默认值 {have} 漂移 —— 已全量的能力把代码默认值"
                f"改成现网值；ConfigMap 丢行不许静默退回旧行为"
            )


# ── 基线 ───────────────────────────────────────────────────────────────────


def _load_json(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _baseline_view(rep: Report) -> tuple[int, set[str]]:
    unmarked_off = set(rep.default_off) - rep.marked_off
    return len(rep.unmarked_steps), unmarked_off


def check_ratchet(rep: Report, base: dict) -> None:
    steps, off = _baseline_view(rep)
    b_steps = int(base.get("warning_only_unmarked", 0))
    b_off = set(base.get("default_off_flags", []))
    if steps > b_steps:
        rep.errors.append(
            f"未标期限的 warning-only 步骤 {steps} > 基线 {b_steps}：\n    "
            + "\n    ".join(rep.unmarked_steps)
            + "\n  新步骤直接 enforce，或在步骤块内写 enforce-by:/retire-when:/not-a-gate:"
        )
    elif steps < b_steps:
        rep.errors.append(
            f"未标期限的 warning-only 步骤降到 {steps}（基线 {b_steps}）—— 跑 --update-baseline 收紧棘轮"
        )
    new = sorted(off - b_off)
    if new:
        rep.errors.append(
            "新增默认关的开关（不在基线、附近也没有 enforce-by:/retire-when:/not-a-gate:）：\n    "
            + "\n    ".join(f"{n}  ({rep.default_off[n]})" for n in new)
            + "\n  enforce 起步 = 默认值写成目标行为；确需软起步就在定义处上方写期限标记"
        )
    stale = sorted(b_off - off)
    if stale:
        rep.errors.append(
            "基线里这些开关已不再是未标注的默认关（翻开 / 删除 / 补了标记）："
            + "、".join(stale)
            + " —— 跑 --update-baseline 收紧棘轮"
        )


def write_baseline(rep: Report, base: dict, *, init: bool) -> int:
    steps, off = _baseline_view(rep)
    if not init:
        b_steps = int(base.get("warning_only_unmarked", 0))
        grow = sorted(off - set(base.get("default_off_flags", [])))
        if steps > b_steps or grow:
            print(
                "× 基线只降不升：不能把新增的 warning-only 步骤或默认关开关写进基线"
                + (f"（{'、'.join(grow)}）" if grow else "")
                + "。去 enforce 起步，或补期限标记。",
                file=sys.stderr,
            )
            return 1
    elif BASELINE_PATH.is_file():
        print("× 基线已存在；收紧用 --update-baseline", file=sys.stderr)
        return 1
    data = {
        "note": base.get(
            "note",
            "enforce 起步闸存量基线（只降不升）。SSOT: scripts/lint_enforce_start.py；"
            "宪法 §0.2 F。",
        ),
        "updated": _dt.date.today().isoformat(),
        "warning_only_unmarked": steps,
        "default_off_flags": sorted(off),
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"√ 基线已写入：warning-only 未标注 {steps} 条，默认关开关 {len(off)} 个")
    return 0


def cross_repo() -> int:
    mine = hashlib.sha256(pathlib.Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    bad = 0
    for repo in PEERS:
        try:
            raw = subprocess.run(
                ["gh", "api", f"repos/Krow-labs/{repo}/contents/scripts/lint_enforce_start.py"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=True,
            ).stdout
            body = base64.b64decode(json.loads(raw)["content"]).replace(b"\r\n", b"\n")
        except Exception as e:  # noqa: BLE001
            print(f"? {repo}: 取不到副本（{type(e).__name__}），本次不判", file=sys.stderr)
            continue
        if hashlib.sha256(body).hexdigest() == mine:
            print(f"√ {repo}: 副本一致")
        else:
            print(f"× {repo}: 副本已分叉 —— 以 krow-bio 为准同步", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


def run(root: pathlib.Path, cfg: dict, today: _dt.date) -> Report:
    rep = Report()
    check_workflows(root, cfg, rep)
    check_enforce_by(root, cfg, rep, today)
    scan_flags(root, cfg, rep)
    check_drift(root, cfg, rep)
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--init-baseline", action="store_true")
    ap.add_argument("--cross-repo", action="store_true")
    a = ap.parse_args()
    if a.cross_repo:
        return cross_repo()
    if not CONFIG_PATH.is_file():
        print(f"× 缺配置 {CONFIG_PATH.relative_to(ROOT)}", file=sys.stderr)
        return 1
    cfg = _load_json(CONFIG_PATH)
    base = _load_json(BASELINE_PATH)
    rep = run(ROOT, cfg, _dt.date.today())
    if a.update_baseline or a.init_baseline:
        if rep.errors:
            print("× 先修掉下列硬错误再动基线：\n  " + "\n  ".join(rep.errors), file=sys.stderr)
            return 1
        return write_baseline(rep, base, init=a.init_baseline)
    check_ratchet(rep, base)
    if a.list:
        for n in sorted(rep.default_off):
            tag = "已标注" if n in rep.marked_off else "存量"
            print(f"  [{tag}] {n}  ({rep.default_off[n]})")
    if rep.errors:
        print("× enforce 起步闸：\n  " + "\n  ".join(rep.errors), file=sys.stderr)
        return 1
    steps, off = _baseline_view(rep)
    print(
        f"√ enforce 起步闸通过：warning-only 未标注 {steps} 条（基线），"
        f"默认关开关 {len(rep.default_off)} 个（存量 {len(off)} / 已标期限 {len(rep.marked_off)}），"
        f"开关默认值 {len(rep.code_defaults)} 个无漂移"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
