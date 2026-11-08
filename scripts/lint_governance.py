#!/usr/bin/env python3
"""治理 lint（krow 一方组员仓统一治理包 · 与 krow-electrical / krow-building 同源，参数全在 docs/governance/kit.yaml）。

为什么要 lint 元规则：AGENTS.md 立的原则是「没有可执行检查的规则不写进来」——这条对它自己也生效。
本脚本是那些规则的物理闸：零依赖（标准库 + PyYAML），不 import 组员插件（CI 里没有 krow_worker_common 也能跑），
与 kas ``scripts/lint_klik_teammate.py``（K1–K9）互补：K 系列管 klik 工具面，这里管仓库纪律与退役边界。

本仓相对两行业仓的两处扩展（向后兼容，kit 不写就是原行为）：
  - G1 行数预算**不计 TURBO 宪法块**（``<!-- krow:constitution:begin/end -->``，由 ``scripts/check_constitution.py`` 钉哈希）；
  - ``kit.core`` 可以是多包内核：``core.packages: [{dir, pyproject, module, dist, version_attr_file?}]``（uv workspace 形）。

检查项（G 系列；FAIL 退非零，WARN 只打印）::

    G1  AGENTS.md 在、行数在预算内（软 WARN / 硬 FAIL；宪法块不计）、灵魂关键词在场（防 squash 静默回退）
    G2  .cursor/rules/*.mdc frontmatter 完整；globs 指向真实文件；每份 .mdc 在 AGENTS.md 登记
    G3  插件工具面（静态解析 _spec(...)）：≤ warn 把 WARN、> fail 把 FAIL；每把带 output_schema；首句 ≤ 120 字
    G4  cli_leaves.yaml：family 对、每片叶子的 tool 是自有工具、example 以 `krow <族> <叶>` 开头
    G5  零 LLM / 零网络 / 零硬编码地址 / 不碰退役模块：插件源码（tests 除外）不得含 kit.banned_in_plugin 与 legacy.import_tokens；
        不得出现 http(s):// 字面量
    G6  extended.md ≤ 预算字符；skills/*/SKILL.md 的 frontmatter name 与目录名一致
    G7  tests/conftest.py 隔离 KROW_WORKSPACE（K8 的本地镜像）
    G8  版本仪式：插件 pyproject version == assets/__act__.yaml version（一份版本号）；core 若声明 version_attr 则与 core pyproject 一致
    G9  退役边界显式：kit.legacy.modules 每一项都在 docs/governance/decisions.md 里被点名（不许静默半边墙）
    G10 反引号点名的 scripts/ / .github/ / docs/governance/ 路径必须真实存在（AGENTS.md / CONTRIBUTING.md / constitution.md）
    G11 .github/required-checks.txt 每个名字都等于某个 on: pull_request 工作流里某个 job 的 name:（与 krow-client / 母仓同款：
        改名 / 合并 / 删除 required job 的 PR 在这里红，而不是合入后让 main / release 分支等一个永远不出现的 check）

用法::

    python scripts/lint_governance.py            # 全部
    python scripts/lint_governance.py --strict   # WARN 也退非零（本地自查）
    python scripts/lint_governance.py --json     # 机读
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
KIT = REPO_ROOT / "docs" / "governance" / "kit.yaml"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
RULES_DIR = REPO_ROOT / ".cursor" / "rules"
DECISIONS = REPO_ROOT / "docs" / "governance" / "decisions.md"

K2_ONE_LINER_CHARS = 120
_URL = re.compile(r"https?://")
_PATH_REF = re.compile(r"`((?:scripts|\.github|docs/governance)/[A-Za-z0-9_./\-]+)`")
_CONSTITUTION = re.compile(r"<!-- krow:constitution:begin -->.*?<!-- krow:constitution:end -->", flags=re.S)


def _without_constitution(text: str) -> str:
    """宪法块逐字一致、被哈希钉住，不是本仓的累积物：行数预算只算它以外的部分（与 check_constitution.py 同口径）。"""
    return _CONSTITUTION.sub("", text)


def core_packages(kit: dict) -> list[dict]:
    """内核包清单：``core.packages``（多包）或由单包形 ``core.{package_dir, pyproject, module, dist, version_attr_file}`` 折成一项。"""
    core = kit.get("core") or {}
    pkgs = core.get("packages")
    if isinstance(pkgs, list) and pkgs:
        return [dict(p) for p in pkgs if isinstance(p, dict)]
    if not core:
        return []
    return [{"dir": core.get("package_dir"), "pyproject": core.get("pyproject") or "pyproject.toml", "module": core.get("module"),
             "dist": core.get("dist"), "version_attr_file": core.get("version_attr_file")}]


class Report:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"{code}: {msg}")

    def warn(self, code: str, msg: str) -> None:
        self.warns.append(f"{code}: {msg}")


def load_kit() -> dict:
    if not KIT.is_file():
        raise SystemExit(f"缺 {KIT.relative_to(REPO_ROOT)}：治理包的参数文件（见 docs/governance/constitution.md）")
    data = yaml.safe_load(KIT.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise SystemExit("kit.yaml 顶层须为映射")
    return data


# ── G1 / G2 / G10：元规则文件 ────────────────────────────────────────────────

def g1_agents(kit: dict, rep: Report) -> None:
    if not AGENTS_MD.is_file():
        rep.fail("G1", "缺 AGENTS.md")
        return
    text = AGENTS_MD.read_text(encoding="utf-8")
    local = _without_constitution(text)
    lines = local.count("\n") + 1
    limits = (kit.get("limits") or {}).get("agents_md_lines") or {}
    soft, hard = int(limits.get("soft", 120)), int(limits.get("hard", 160))
    note = "（宪法块不计）" if local != text else ""
    if lines > hard:
        rep.fail("G1", f"AGENTS.md {lines} 行{note} > 硬上限 {hard}（规则下沉 .mdc / docs/governance，不要膨胀入口）")
    elif lines > soft:
        rep.warn("G1", f"AGENTS.md {lines} 行{note} > 软上限 {soft}")
    for kw in kit.get("invariants") or []:
        if str(kw) not in text:
            rep.fail("G1", f"AGENTS.md 缺灵魂关键词「{kw}」（squash / 重写时被静默删掉了？）")


def g2_mdc(kit: dict, rep: Report) -> None:
    agents = AGENTS_MD.read_text(encoding="utf-8") if AGENTS_MD.is_file() else ""
    for mdc in sorted(RULES_DIR.glob("*.mdc")) if RULES_DIR.is_dir() else []:
        text = mdc.read_text(encoding="utf-8")
        m = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.S)
        if not m:
            rep.fail("G2", f"{mdc.name} 缺 frontmatter")
            continue
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            rep.fail("G2", f"{mdc.name} frontmatter 不是合法 yaml：{e}")
            continue
        if not str(fm.get("description") or "").strip():
            rep.fail("G2", f"{mdc.name} 缺 description")
        if not fm.get("alwaysApply") and not fm.get("globs"):
            rep.fail("G2", f"{mdc.name} 既非 alwaysApply 也没有 globs——永远不会生效")
        globs = fm.get("globs") or ""
        patterns = [str(g).strip() for g in globs] if isinstance(globs, list) else [g.strip() for g in str(globs).split(",")]
        for pattern in [g for g in patterns if g]:
            if not glob.glob(str(REPO_ROOT / pattern), recursive=True):
                rep.fail("G2", f"{mdc.name} 的 glob「{pattern}」匹配不到任何文件（路径改了规则没跟上）")
        if f"`.cursor/rules/{mdc.name}`" not in agents and mdc.name not in agents:
            rep.fail("G2", f"{mdc.name} 没在 AGENTS.md 登记（规则不登记 = 没人知道它存在）")


def g10_promises(rep: Report) -> None:
    for doc in (AGENTS_MD, REPO_ROOT / "CONTRIBUTING.md", REPO_ROOT / "docs" / "governance" / "constitution.md"):
        if not doc.is_file():
            continue
        for ref in sorted(set(_PATH_REF.findall(doc.read_text(encoding="utf-8")))):
            if not (REPO_ROOT / ref).exists():
                rep.fail("G10", f"{doc.name} 点名了不存在的路径 `{ref}`")


# ── G3 / G4 / G5 / G6 / G7：组员插件 ─────────────────────────────────────────

def _plugin_paths(kit: dict) -> tuple[Path, Path]:
    tm = kit.get("teammate") or {}
    plugin_dir = REPO_ROOT / str(tm.get("plugin_dir") or "")
    package = plugin_dir / str(tm.get("package") or "")
    return plugin_dir, package


def _parse_specs(init_py: Path) -> list[dict]:
    """静态读 ``_spec("name", "description", ..., output_schema=...)`` 调用；不 import 插件。"""
    specs: list[dict] = []
    if not init_py.is_file():
        return specs
    tree = ast.parse(init_py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_spec"):
            continue
        name = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else ""
        desc = ""
        if len(node.args) > 1:
            d = node.args[1]
            if isinstance(d, ast.Constant) and isinstance(d.value, str):
                desc = d.value
            elif isinstance(d, ast.JoinedStr):
                desc = "".join(v.value for v in d.values if isinstance(v, ast.Constant))
        kws = {k.arg for k in node.keywords}
        specs.append({"name": str(name), "description": desc, "has_output_schema": "output_schema" in kws})
    return specs


def g3_tool_face(kit: dict, rep: Report) -> list[str]:
    plugin_dir, package = _plugin_paths(kit)
    specs = _parse_specs(package / "__init__.py")
    limits = (kit.get("limits") or {}).get("tools") or {}
    warn_n, fail_n = int(limits.get("warn", 8)), int(limits.get("fail", 12))
    if not specs:
        rep.fail("G3", f"{package.relative_to(REPO_ROOT) if package.exists() else package}/__init__.py 里没解析到 _spec(...) 工具面")
        return []
    if len(specs) > fail_n:
        rep.fail("G3", f"工具 {len(specs)} 把 > 硬顶 {fail_n}")
    elif len(specs) > warn_n:
        rep.warn("G3", f"工具 {len(specs)} 把 > {warn_n}（动词化、回声退成技能页）")
    family = str((kit.get("teammate") or {}).get("family") or "")
    for s in specs:
        if not s["has_output_schema"]:
            rep.fail("G3", f"{s['name']} 缺 output_schema")
        first = re.split(r"[。.!?！？\n]", s["description"].strip(), maxsplit=1)[0]
        if len(first) > K2_ONE_LINER_CHARS:
            rep.fail("G3", f"{s['name']} 描述首句 {len(first)} 字 > {K2_ONE_LINER_CHARS}")
        if family and not s["name"].startswith(family + "."):
            rep.fail("G3", f"{s['name']} 不在自有前缀 {family}. 下")
    return [s["name"] for s in specs]


def g4_leaves(kit: dict, rep: Report, tools: list[str]) -> None:
    _plugin_dir, package = _plugin_paths(kit)
    lf = package / "cli_leaves.yaml"
    family = str((kit.get("teammate") or {}).get("family") or "")
    if not lf.is_file():
        rep.fail("G4", f"缺 {lf.relative_to(REPO_ROOT)}（klik 组员没有叶子文件就不算 klik 组员）")
        return
    doc = yaml.safe_load(lf.read_text(encoding="utf-8")) or {}
    if doc.get("family") != family:
        rep.fail("G4", f"cli_leaves.yaml family={doc.get('family')!r} ≠ kit.teammate.family={family!r}")
    leaves = doc.get("leaves") or {}
    for leaf, body in leaves.items():
        tool = str((body or {}).get("tool") or "")
        if tools and tool not in tools:
            rep.fail("G4", f"叶子 {leaf} 指向的工具 {tool} 不在自有工具面里")
        ex = str((body or {}).get("example") or "")
        if not (ex == f"krow {family} {leaf}" or ex.startswith(f"krow {family} {leaf} ")):
            rep.fail("G4", f"叶子 {leaf} 的 example 须以 `krow {family} {leaf}` 开头：{ex!r}")
    if tools and set(tools) - {str((b or {}).get("tool")) for b in leaves.values()}:
        rep.warn("G4", f"有工具没有叶子：{sorted(set(tools) - {str((b or {}).get('tool')) for b in leaves.values()})}")


def g5_zero_llm(kit: dict, rep: Report) -> None:
    plugin_dir, package = _plugin_paths(kit)
    banned = [str(t) for t in (kit.get("banned_in_plugin") or [])]
    banned += [str(t) for t in ((kit.get("legacy") or {}).get("import_tokens") or [])]
    for py in sorted(package.rglob("*.py")) if package.is_dir() else []:
        if "tests" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                rep.fail("G5", f"{py.relative_to(REPO_ROOT)} 含禁用记号「{token}」（工具内零 LLM / 零网络 / 不碰退役模块）")
        if _URL.search(text):
            rep.fail("G5", f"{py.relative_to(REPO_ROOT)} 出现 http(s):// 字面量（服务地址走席位策略 / 配置，不写进组员包）")
    for other in sorted(package.rglob("*")) if package.is_dir() else []:
        is_doc = other.is_file() and other.suffix in {".md", ".yaml", ".yml"} and "tests" not in other.parts
        if is_doc and _URL.search(other.read_text(encoding="utf-8", errors="ignore")):
            rep.warn("G5", f"{other.relative_to(REPO_ROOT)} 含 http(s):// 字面量——确认不是服务地址")


def g6_assets(kit: dict, rep: Report) -> None:
    _plugin_dir, package = _plugin_paths(kit)
    budget = int((kit.get("limits") or {}).get("extended_chars", 6000))
    ext = package / "assets" / "extended.md"
    if not ext.is_file():
        rep.fail("G6", "缺 assets/extended.md")
    else:
        n = len(ext.read_text(encoding="utf-8"))
        if n > budget:
            rep.fail("G6", f"extended.md {n} 字符 > 预算 {budget}（一页手册 + 技能页）")
    pages = sorted(package.glob("skills/*/SKILL.md")) if package.is_dir() else []
    if not pages:
        rep.fail("G6", "没有 skills/*/SKILL.md（能力是可读物：范式 / 尺子 / 账本格式进技能页）")
    for p in pages:
        head = p.read_text(encoding="utf-8").splitlines()[:3]
        if len(head) < 2 or head[0] != "---" or head[1] != f"name: {p.parent.name}":
            rep.fail("G6", f"{p.relative_to(REPO_ROOT)} frontmatter 须以 `---\\nname: {p.parent.name}` 开头")


def g7_conftest(kit: dict, rep: Report) -> None:
    plugin_dir, _package = _plugin_paths(kit)
    conftest = plugin_dir / "tests" / "conftest.py"
    if not conftest.is_file() or "KROW_WORKSPACE" not in conftest.read_text(encoding="utf-8"):
        rep.fail("G7", f"{plugin_dir.relative_to(REPO_ROOT) if plugin_dir.exists() else plugin_dir}/tests/conftest.py 没隔离 KROW_WORKSPACE（会把技能页 / 账本写进真实盘）")


# ── G8 / G9：版本仪式与退役边界 ───────────────────────────────────────────────

def _pyproject_version(path: Path) -> str:
    if not path.is_file():
        return ""
    m = re.search(r'^version\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1) if m else ""


def g8_versions(kit: dict, rep: Report) -> None:
    plugin_dir, package = _plugin_paths(kit)
    pv = _pyproject_version(plugin_dir / "pyproject.toml")
    act = package / "assets" / "__act__.yaml"
    av = ""
    if act.is_file():
        av = str((yaml.safe_load(act.read_text(encoding="utf-8")) or {}).get("version") or "")
    if not pv:
        rep.fail("G8", "插件 pyproject.toml 缺 version")
    elif pv != av:
        rep.fail("G8", f"版本号分叉：插件 pyproject {pv!r} ≠ __act__.yaml {av!r}（一份版本号，改一处就要改另一处）")
    for core in core_packages(kit):
        pyproject = str(core.get("pyproject") or "pyproject.toml")
        cv = _pyproject_version(REPO_ROOT / pyproject)
        if not cv:
            rep.fail("G8", f"内核 {pyproject} 缺 version")
        attr_file = str(core.get("version_attr_file") or "")
        if attr_file:
            m = re.search(r'^__version__\s*=\s*"([^"]+)"', (REPO_ROOT / attr_file).read_text(encoding="utf-8"), flags=re.M) if (REPO_ROOT / attr_file).is_file() else None
            if not m or m.group(1) != cv:
                rep.fail("G8", f"内核版本分叉：{pyproject} {cv!r} ≠ {attr_file} __version__ {m.group(1) if m else None!r}")


def g9_legacy_declared(kit: dict, rep: Report) -> None:
    legacy = (kit.get("legacy") or {}).get("modules") or []
    if not legacy:
        return
    if not DECISIONS.is_file():
        rep.fail("G9", "有退役模块但缺 docs/governance/decisions.md")
        return
    text = DECISIONS.read_text(encoding="utf-8")
    for mod in legacy:
        if not (REPO_ROOT / str(mod)).exists():
            rep.warn("G9", f"kit.legacy.modules 里的 {mod} 已不存在——从 kit 里删掉它")
            continue
        if str(mod) not in text:
            rep.fail("G9", f"退役模块 {mod} 没在 decisions.md 里被点名（退役必须显式，不许静默半边墙）")
    if not re.search(r"^## D-\d{3}", text, flags=re.M):
        rep.fail("G9", "decisions.md 没有 `## D-NNN` 形式的决定条目")


# ── G11：required checks ↔ workflow job 名 ──────────────────────────────────

def g11_required_checks(rep: Report) -> None:
    req = REPO_ROOT / ".github" / "required-checks.txt"
    if not req.is_file():
        rep.fail("G11", "缺 .github/required-checks.txt（分支保护 required checks 的仓内镜像）")
        return
    names = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not names:
        rep.fail("G11", ".github/required-checks.txt 一个 check 都没列")
        return
    job_names: set[str] = set()
    matrix_jobs: set[str] = set()
    for wf in sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml")):
        try:
            data = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            rep.fail("G11", f"{wf.name} 不是合法 yaml：{e}")
            continue
        on = data.get("on") if "on" in data else data.get(True)  # yaml 1.1 把裸 on 解析成 True
        triggers = on if isinstance(on, (list, dict)) else [on]
        if "pull_request" not in (triggers if isinstance(triggers, list) else list(triggers.keys())):
            continue
        for job_id, job in (data.get("jobs") or {}).items():
            base = str((job or {}).get("name") or job_id)
            job_names.add(base)
            if isinstance((job or {}).get("strategy"), dict) and (job or {}).get("strategy", {}).get("matrix") is not None:
                matrix_jobs.add(base)  # matrix job 的 check 名是「<name> (<矩阵值, …>)」
    for n in names:
        m = re.match(r"^(.*) \((.+)\)$", n)
        if n in job_names or (m and m.group(1) in matrix_jobs):
            continue
        rep.fail("G11", f"required check「{n}」不等于任何 on: pull_request 工作流里 job 的 name:（matrix job 写成「<name> (<矩阵值>)」）（分支保护会永远等不到它）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--strict", action="store_true", help="WARN 也退非零")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    kit = load_kit()
    rep = Report()
    g1_agents(kit, rep)
    g2_mdc(kit, rep)
    # 2026-11-08 Krow-labs 全仓对齐：G3–G8 的主体是 klik 组员插件（kit.teammate）。非组员仓（Rust 服务 / TS 前端 / Go /
    # Swift / 纯规则仓）kit 不写 teammate 段，这六条没有被检对象，跳过而不是报「找不到插件」——向后兼容：写了 teammate
    # 的组员仓行为与 krow-kad 同源版本完全一致。
    if kit.get("teammate"):
        tools = g3_tool_face(kit, rep)
        g4_leaves(kit, rep, tools)
        g5_zero_llm(kit, rep)
        g6_assets(kit, rep)
        g7_conftest(kit, rep)
        g8_versions(kit, rep)
    else:
        tools = []
    g9_legacy_declared(kit, rep)
    g10_promises(rep)
    g11_required_checks(rep)
    if args.json:
        print(json.dumps({"fails": rep.fails, "warns": rep.warns, "tools": tools}, ensure_ascii=False, indent=2))
    else:
        for w in rep.warns:
            print(f"WARN {w}")
        for f in rep.fails:
            print(f"FAIL {f}")
        print(f"governance: {len(rep.fails)} FAIL / {len(rep.warns)} WARN · 工具 {len(tools)} 把")
    if rep.fails or (args.strict and rep.warns):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
