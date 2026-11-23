#!/usr/bin/env python3
"""runs-on 的类别写法：生成、识别、合入前检查（任务 784c14af · CI 统一调度；主人道哥大厅 #49968 / #50045）。

统一调度之后，工作流里的 job 只声明「要哪类机器」，去哪台由调度器写的一张表定。GitHub 只认作业入队那一刻 runs-on 算出来的
标签，所以表存成仓库变量 KROW_CI_TABLE（JSON；只有调度器写），每个 job 的 runs-on 是同一行固定写法，只有类别名和两个回落值不同：

    ${{ github.event.pull_request.head.repo.fork && <fork 回落> || fromJSON(vars.KROW_CI_TABLE || '{}')[format('<类别>@{0}{1}',
    github.event_name, github.event.pull_request.draft && '-draft' || '')] || fromJSON(vars.KROW_CI_TABLE || '{}')['<类别>'] || <没有表时的回落> }}

- fork 来的 PR 一律去 <fork 回落>，不查表：外来代码上不了自建机器。<fork 回落> 写字面量时必须是 GitHub 托管机的标签，否则不算接入。
- 先查「<类别>@<事件>」（草稿 PR 是「<类别>@pull_request-draft」），查不到再查「<类别>」，都没有就用 <没有表时的回落>——
  表不在、表里没有这一类时，行为与接入前逐字相同。
- 回落值两种写法：'ubuntu-latest' 这样的单个标签，或 fromJSON('["self-hosted","krow-release"]') 这样的标签数组。
- 类别名也可以取自矩阵：把 '<类别>' 换成 matrix.<字段>（多系统矩阵用），此时回落值也可以写 matrix.<字段>。

本文件只用标准库，可以逐字放进任何一个仓（放哪儿由那个仓定）。三个用法：

    python3 ci_runs_on.py render light ubuntu-latest            # 打印一行写法
    python3 ci_runs_on.py check [--baseline 文件] [工作流目录或文件 …]   # 合入前检查：有 job 不是类别写法就退 1
    python3 ci_runs_on.py list [工作流目录或文件 …]              # 逐个 job 打印：文件 / job / 判定 / 类别或原因

check 的基线（--baseline）是「还没接入、暂时放行」的 job 清单，一行一个「文件名:job」；只许减不许加——基线里有、
实际已经是类别写法或已经不存在的行会报出来要求删掉（--update-baseline 重写文件）。基线为空且全部通过 = 本仓没有脱管的 job。
"""
from __future__ import annotations

import json
import os
import re
import sys

#: 本文件的版本。各仓的副本与 krowworker 的 scripts/ci/ci_runs_on.py 逐字相同；改了判据或闭集就加一，各仓同批换。
VERSION = "ci-runs-on/2"
#: 类别闭集。加类别要同时改调度器的表（ci_dispatch_table.json）；这里不认识的类别名一律算没接入。
CATEGORIES = ("light", "heavy", "browser", "docker", "vm", "long", "release", "macos", "windows")
TABLE_VAR = "KROW_CI_TABLE"
_LABEL = r"'[A-Za-z0-9][A-Za-z0-9._-]*'"
_ARRAY = r"fromJSON\('\[\"[A-Za-z0-9][A-Za-z0-9._-]*\"(?:, ?\"[A-Za-z0-9][A-Za-z0-9._-]*\")*\]'\)"
_MATRIX = r"matrix\.[A-Za-z_][A-Za-z0-9_]*"
_FALLBACK = rf"(?:{_LABEL}|{_ARRAY}|{_MATRIX})"
_TABLE = r"fromJSON\(vars\.KROW_CI_TABLE \|\| '\{\}'\)"
_DRAFT = r"github\.event\.pull_request\.draft && '-draft' \|\| ''"
CANON_RE = re.compile(
    rf"^\$\{{\{{ github\.event\.pull_request\.head\.repo\.fork && (?P<fork>{_LABEL}|{_MATRIX}) \|\| {_TABLE}\[format\("
    rf"(?:'(?P<cat>[a-z][a-z0-9-]*)@\{{0\}}\{{1\}}', github\.event_name, {_DRAFT}"
    rf"|'\{{2\}}@\{{0\}}\{{1\}}', github\.event_name, {_DRAFT}, (?P<mcat>{_MATRIX}))\)\] \|\| "
    rf"{_TABLE}\[(?:'(?P<cat2>[a-z][a-z0-9-]*)'|(?P<mcat2>{_MATRIX}))\] \|\| (?P<fallback>{_FALLBACK}) \}}\}}$")
HOSTED_RE = re.compile(r"^(ubuntu|windows|macos)-[A-Za-z0-9.-]+$")


def fallback_text(value: str | list[str] | tuple[str, ...]) -> str:
    """回落值 → 表达式里的写法。字符串以 matrix. 开头的原样用（矩阵字段）。"""
    if isinstance(value, str):
        return value if value.startswith("matrix.") else f"'{value}'"
    return "fromJSON('[" + ",".join(f'"{x}"' for x in value) + "]')"


def render(category: str, fallback: str | list[str] | tuple[str, ...], fork: str | None = None) -> str:
    """生成一行类别写法。category 是类别名或 matrix.<字段>；fork 缺省 = fallback（fallback 是数组时必须显式给 fork）。"""
    if fork is None:
        if not isinstance(fallback, str):
            raise ValueError("回落值是自建机器的标签数组时，必须另给 fork 来的 PR 用的托管机标签")
        fork = fallback
    table = f"fromJSON(vars.{TABLE_VAR} || '{{}}')"
    draft = "github.event.pull_request.draft && '-draft' || ''"
    if category.startswith("matrix."):
        key1, key2 = f"format('{{2}}@{{0}}{{1}}', github.event_name, {draft}, {category})", category
    else:
        key1, key2 = f"format('{category}@{{0}}{{1}}', github.event_name, {draft})", f"'{category}'"
    return (f"${{{{ github.event.pull_request.head.repo.fork && {fallback_text(fork)} || {table}[{key1}] || "
            f"{table}[{key2}] || {fallback_text(fallback)} }}}}")


def classify(raw: object) -> dict:
    """一个 job 的 runs-on 原文 → {"managed": bool, "category": …, "kind": …, "why": …}。

    kind：managed（类别写法）/ hosted（写死托管机标签）/ selfhosted（写死自建机标签）/ var（读别的仓库变量）/ expr（别的表达式）/ empty。
    """
    if isinstance(raw, (list, tuple)):
        labels = [str(x) for x in raw]
        if len(labels) == 1 and HOSTED_RE.match(labels[0]):
            return {"managed": False, "kind": "hosted", "category": None, "why": f"写死托管机标签 {labels[0]}"}
        return {"managed": False, "kind": "selfhosted", "category": None, "why": f"写死机器标签 {','.join(labels)}"}
    text = str(raw or "").strip()
    if not text:
        return {"managed": False, "kind": "empty", "category": None, "why": "没有 runs-on"}
    m = CANON_RE.match(text)
    if m:
        cat, cat2, mcat, mcat2 = m.group("cat"), m.group("cat2"), m.group("mcat"), m.group("mcat2")
        fork = m.group("fork")
        if fork.startswith("'") and not HOSTED_RE.match(fork[1:-1]):
            return {"managed": False, "kind": "expr", "category": None, "why": f"fork 来的 PR 的回落必须是 GitHub 托管机标签，写的是 {fork}"}
        if mcat or mcat2:
            if mcat and mcat == mcat2:
                return {"managed": True, "kind": "managed", "category": mcat, "why": ""}
            return {"managed": False, "kind": "expr", "category": None, "why": "两处类别不是同一个矩阵字段"}
        if cat != cat2:
            return {"managed": False, "kind": "expr", "category": None, "why": f"两处类别名不一致（{cat} / {cat2}）"}
        if cat not in CATEGORIES:
            return {"managed": False, "kind": "expr", "category": None, "why": f"类别 {cat} 不在闭集 {list(CATEGORIES)} 里"}
        return {"managed": True, "kind": "managed", "category": cat, "why": ""}
    if "${{" not in text:
        if HOSTED_RE.match(text):
            return {"managed": False, "kind": "hosted", "category": None, "why": f"写死托管机标签 {text}"}
        return {"managed": False, "kind": "selfhosted", "category": None, "why": f"写死机器标签 {text}"}
    if TABLE_VAR in text:
        return {"managed": False, "kind": "expr", "category": None, "why": "用了调度表但不是固定写法（差一个字符也不算）"}
    if re.search(r"\bvars\.", text):
        return {"managed": False, "kind": "var", "category": None, "why": "去向读的是别的仓库变量"}
    return {"managed": False, "kind": "expr", "category": None, "why": "去向是别的表达式"}


# ---------------- 从工作流文本里取每个 job 的 runs-on（不依赖 PyYAML） ----------------
def _strip_comment(value: str) -> str:
    """去掉行尾注释。表达式和引号里的 # 不算注释。"""
    out, quote, depth, i = [], "", 0, 0
    while i < len(value):
        ch = value[i]
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif value.startswith("${{", i):
            depth += 1
        elif value.startswith("}}", i) and depth:
            depth -= 1
        elif ch == "#" and not depth and (i == 0 or value[i - 1] in " \t"):
            break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner.replace('\\"', '"')
    return value


def _flow_list(value: str) -> list[str]:
    return [_unquote(x) for x in value.strip()[1:-1].split(",") if x.strip()]


class WorkflowError(ValueError):
    """工作流结构无法安全枚举。"""


def jobs_of(text: str) -> list[dict]:
    """工作流文本 → [{"job", "line", "runs_on"（字符串 / 列表 / None）, "uses"（调用可复用工作流时的目标）}]。

    只认块状写法（认不出的 job 结构报错）：顶层 jobs: 下面第一层缩进是 job 名，job 下面第一层缩进里的 runs-on / uses。
    runs-on 的值可以是单行标量、单行 [a, b]、下面几行的「- a」列表、或者 > / | 开头的折行标量。
    """
    lines = text.splitlines()
    roots = [i for i, ln in enumerate(lines) if re.match(r"""^(?:jobs|'jobs'|"jobs")\s*:""", ln)]
    if len(roots) != 1 or not re.fullmatch(r"jobs:\s*(#.*)?", lines[roots[0]]):
        raise WorkflowError("需要唯一的、可识别的顶层 jobs: 块")
    start = roots[0]
    out: list[dict] = []
    job_indent = key_indent = None
    cur: dict | None = None
    i = start + 1
    while i < len(lines):
        ln = lines[i]
        body = ln.strip()
        if not body or body.startswith("#"):
            i += 1
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        if indent == 0:
            break
        if job_indent is None:
            job_indent = indent
        if indent == job_indent:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(#.*)?$", body)
            if not m:
                raise WorkflowError(f"第 {i + 1} 行不是可识别的块状 job")
            cur = {"job": m.group(1), "line": i + 1, "runs_on": None, "uses": None}
            out.append(cur)
            key_indent = None
            i += 1
            continue
        if cur is None or indent < job_indent:
            raise WorkflowError(f"第 {i + 1} 行 job 缩进异常")
        if key_indent is None:
            key_indent = indent
        if indent == key_indent:
            m = re.match(r"^(runs-on|uses):(.*)$", body)
            if m:
                key, value = m.group(1), _strip_comment(m.group(2).strip())
                if key == "uses":
                    cur["uses"] = _unquote(value)
                elif value.startswith("[") and value.endswith("]"):
                    cur["runs_on"] = _flow_list(value)
                elif value in ("", ">", ">-", ">+", "|", "|-", "|+"):
                    # 往下收更深缩进的行：「- a」是列表，否则是折行标量
                    items, j = [], i + 1
                    while j < len(lines):
                        nxt = lines[j]
                        nb = nxt.strip()
                        if nb and not nb.startswith("#") and len(nxt) - len(nxt.lstrip(" ")) <= key_indent:
                            break
                        if nb and not nb.startswith("#"):
                            items.append(nb)
                        j += 1
                    if value == "" and items and all(x.startswith("- ") or x == "-" for x in items):
                        cur["runs_on"] = [_unquote(_strip_comment(x[1:].strip())) for x in items]
                    else:
                        cur["runs_on"] = " ".join(items)
                    i = j
                    continue
                else:
                    cur["runs_on"] = _unquote(value)
        i += 1
    if not out:
        raise WorkflowError("jobs: 块没有可识别的 job")
    return out


def workflow_files(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths or [".github/workflows"]:
        if os.path.isdir(p):
            out += sorted(os.path.join(p, f) for f in os.listdir(p) if f.endswith((".yml", ".yaml")))
        elif os.path.exists(p):
            out.append(p)
    return out


def scan(paths: list[str]) -> list[dict]:
    """逐文件逐 job 判定。调用可复用工作流的 job（uses:）没有 runs-on，不计入——被调用的那个文件里的 job 各自被查。"""
    rows = []
    for path in workflow_files(paths):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            jobs = jobs_of(text)
        except WorkflowError as exc:
            raise WorkflowError(f"{path}: {exc}") from exc
        for j in jobs:
            if j["uses"] and j["runs_on"] is None:
                continue
            rows.append({"file": os.path.basename(path), "job": j["job"], "line": j["line"], "raw": j["runs_on"], **classify(j["runs_on"])})
    return rows


def load_baseline(path: str | None) -> list[str]:
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]


def check(rows: list[dict], baseline: list[str]) -> tuple[list[str], list[str]]:
    """→ (不通过的原因, 基线里该删的行)。基线只许减：新增的脱管 job 不通过；基线里已经接入 / 已经不存在的行要删。"""
    allowed = set(baseline)
    bad = [f"{r['file']}:{r['job']}（第 {r['line']} 行）：{r['why']}" for r in rows if not r["managed"] and f"{r['file']}:{r['job']}" not in allowed]
    unmanaged = {f"{r['file']}:{r['job']}" for r in rows if not r["managed"]}
    stale = sorted(allowed - unmanaged)
    return bad, stale


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, args = argv[0], argv[1:]
    if cmd == "render":
        if len(args) < 2:
            print("用法：render <类别> <回落标签|JSON 数组> [fork 回落标签]", file=sys.stderr)
            return 2
        fb: str | list[str] = json.loads(args[1]) if args[1].startswith("[") else args[1]
        print(render(args[0], fb, args[2] if len(args) > 2 else None))
        return 0
    if cmd not in ("check", "list"):
        print(f"不认识的子命令 {cmd!r}（render / check / list）", file=sys.stderr)
        return 2
    baseline_path, update, paths = None, False, []
    it = iter(args)
    for a in it:
        if a == "--baseline":
            baseline_path = next(it, None)
        elif a == "--update-baseline":
            update = True
        else:
            paths.append(a)
    try:
        rows = scan(paths)
    except WorkflowError as exc:
        print(f"[{VERSION}] ::error::{exc}", file=sys.stderr)
        return 1
    if cmd == "list":
        for r in rows:
            print(f"{r['file']}\t{r['job']}\t{'managed' if r['managed'] else r['kind']}\t{r['category'] or r['why']}")
        return 0
    baseline = load_baseline(baseline_path)
    bad, stale = check(rows, baseline)
    managed = sum(1 for r in rows if r["managed"])
    if update and baseline_path:
        # 只删已经接入 / 已不存在的行；注释行与剩下各行的次序原样留着
        unmanaged = {f"{r['file']}:{r['job']}" for r in rows if not r["managed"]}
        head = "# 还没接入统一调度、暂时放行的 job（文件名:job）。只许减不许加。\n"
        old = open(baseline_path, encoding="utf-8").read().splitlines() if os.path.exists(baseline_path) else []
        kept = [ln for ln in old if ln.lstrip().startswith("#") or ln.strip() in unmanaged]
        with open(baseline_path, "w", encoding="utf-8") as f:
            f.write(("" if any(ln.lstrip().startswith("#") for ln in kept) else head) + "".join(ln + "\n" for ln in kept))
        stale = []
    for line in bad:
        print(f"::error::runs-on 不是类别写法：{line}")
    for line in stale:
        print(f"::error::基线里的 {line} 已经接入或已不存在，从基线里删掉（--update-baseline）")
    print(f"[{VERSION}] job {len(rows)} 个：类别写法 {managed} 个，基线放行 {len(rows) - managed - len(bad)} 个，不通过 {len(bad)} 个"
          + (f"，基线待删 {len(stale)} 行" if stale else ""))
    return 1 if bad or stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
