#!/usr/bin/env python3
"""GitHub Actions workflow 卫生闸（W 系列；母仓 ci-workflow-governance 规则与
lint_governance_invariants 的 workflow 登记检查 / krow-bio 的 check_workflow_wiring 在本仓的落法）。

与同源治理包的 G11（required check 名 ↔ job name）互补：G11 管「名字对不对得上」，这里管「workflow 自己写得稳不稳」。
独立成文件、不改 `scripts/lint_governance.py`——那份与 krow-kad 逐字同源，判据不为单仓改。

检查项（FAIL 退非零）::

    W1  每个 job 都有 timeout-minutes（没有上限的 job 卡住 = 占着 runner 等 6 小时被杀，Actions 列表里和「今天有点慢」长得一样）
    W2  最小权限：顶层 permissions: 或每个 job 都写了 permissions:（缺省 GITHUB_TOKEN 是宽权限）
    W3  带 on: pull_request 的 workflow 必须有 concurrency 且 cancel-in-progress: true（同一 PR 再推直接取消旧轮，只减队列不改判据）
    W4  每个 .github/workflows/*.yml 都在 CONTRIBUTING.md 的 CI 表里被反引号点名（不在治理表里 ≡ 没人负责）
    W5  on.workflow_run.workflows 写的必须是某个 workflow 的 name: 逐字原文（写文件名或简称 = 永远不触发且毫无迹象）
    W6  .github/required-checks.txt 里的 job 所在 workflow 的 pull_request 触发不得带 paths: 过滤
        （required check 在被过滤掉的 PR 上永远不出现，分支保护等一个不会来的 check）；
        且每个 required check 名都必须对应某个 on: pull_request 工作流的 job（matrix job 写「<name> (<矩阵值>)」）

存量基线（2026-11-08 Krow-labs 全仓对齐加入）：`scripts/data/workflows_baseline.json` 收编旧 workflow 的 W1/W2/W3/W5/W6
存量条目（改旧 workflow 的 permissions / timeout 可能改变发布链行为，另开 PR 逐个收口）；新增即红、修好一条基线就得收紧
（`--update-baseline`），W4 不许进基线。首次落地 `--init-baseline`。

用法::

    python3 scripts/lint_workflows.py                    # 全部（含基线棘轮）
    python3 scripts/lint_workflows.py --json             # 机读
    python3 scripts/lint_workflows.py --init-baseline    # 首次落地：以当前存量建基线
    python3 scripts/lint_workflows.py --update-baseline  # 收紧基线（只降不升）

病理形态用例：scripts/tests/test_lint_workflows.py。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
REQUIRED_CHECKS = REPO_ROOT / ".github" / "required-checks.txt"
_MENTION = re.compile(r"`(?:\.github/workflows/)?([A-Za-z0-9._-]+\.ya?ml)`")


def _load(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _on(data: dict) -> dict:
    """`on:` 在 yaml 1.1 里会被解析成 True 键；统一成 {trigger: config} 映射。"""
    raw = data.get("on") if "on" in data else data.get(True)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {str(t): None for t in raw}
    if isinstance(raw, str):
        return {raw: None}
    return {}


def _jobs(data: dict) -> dict:
    jobs = data.get("jobs") or {}
    return {str(k): (v or {}) for k, v in jobs.items()} if isinstance(jobs, dict) else {}


def lint(root: Path = REPO_ROOT) -> tuple[list[str], dict[str, str]]:
    fails: list[str] = []
    wf_dir = root / ".github" / "workflows"
    files = sorted(wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []
    if not files:
        return ["W1: .github/workflows 下没有任何 workflow"], {}
    names: dict[str, str] = {}
    parsed: dict[str, dict] = {}
    for wf in files:
        data = _load(wf)
        if data is None:
            fails.append(f"W1: {wf.name} 不是合法的 workflow yaml")
            continue
        parsed[wf.name] = data
        names[wf.name] = str(data.get("name") or wf.stem)

    for fname, data in parsed.items():
        on = _on(data)
        jobs = _jobs(data)
        top_perm = "permissions" in data
        for job_id, job in jobs.items():
            if "timeout-minutes" not in job:
                fails.append(f"W1: {fname} job `{job_id}` 缺 timeout-minutes")
            if not top_perm and "permissions" not in job:
                fails.append(f"W2: {fname} job `{job_id}` 没有 permissions（顶层也没有）——GITHUB_TOKEN 缺省是宽权限")
        if "pull_request" in on:
            conc = data.get("concurrency")
            if not isinstance(conc, dict) or conc.get("cancel-in-progress") is not True:
                fails.append(f"W3: {fname} 带 pull_request 触发但没有 concurrency.cancel-in-progress: true")
        wr = on.get("workflow_run")
        if isinstance(wr, dict):
            for target in wr.get("workflows") or []:
                if str(target) not in names.values():
                    fails.append(f"W5: {fname} 监听的 workflow_run `{target}` 不是任何 workflow 的 name: 逐字原文（永远不会触发）")

    contributing = (root / "CONTRIBUTING.md").read_text(encoding="utf-8") if (root / "CONTRIBUTING.md").is_file() else ""
    registered = set(_MENTION.findall(contributing))
    for fname in parsed:
        if fname not in registered:
            fails.append(f"W4: {fname} 没在 CONTRIBUTING.md 的 CI 表里登记（不在治理表里 ≡ 没人负责）")

    req = root / ".github" / "required-checks.txt"
    if req.is_file():
        wanted = [ln.strip() for ln in req.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        pr_job_names: set[str] = set()
        pr_matrix_jobs: set[str] = set()
        for fname, data in parsed.items():
            on = _on(data)
            if "pull_request" not in on:
                continue
            pr_cfg = on.get("pull_request") or {}
            has_paths = isinstance(pr_cfg, dict) and bool(pr_cfg.get("paths") or pr_cfg.get("paths-ignore"))
            for job_id, job in _jobs(data).items():
                jname = str(job.get("name") or job_id)
                pr_job_names.add(jname)
                if isinstance(job.get("strategy"), dict) and job["strategy"].get("matrix") is not None:
                    pr_matrix_jobs.add(jname)
                if jname in wanted and has_paths:
                    fails.append(f"W6: required check「{jname}」所在 {fname} 的 pull_request 带 paths 过滤——被过滤掉的 PR 会永远等不到这个 check")
        # 2026-11-08 Krow-labs 全仓对齐加入：required check 名必须对应某个 pull_request 工作流的 job（matrix job 写「<name> (<矩阵值>)」）；
        # 否则分支保护等一个永远不出现的 check（与组员仓 lint_governance.py G11 同义，这里保证非组员谱系的仓也有这道闸）。
        for w in wanted:
            m = re.match(r"^(.*) \((.+)\)$", w)
            if w in pr_job_names or (m and m.group(1) in pr_matrix_jobs):
                continue
            fails.append(f"W6: required check「{w}」不等于任何 on: pull_request 工作流里 job 的 name:（分支保护会永远等不到它；matrix job 写「<name> (<矩阵值>)」）")
    return fails, names


BASELINE = REPO_ROOT / "scripts" / "data" / "workflows_baseline.json"
#: W4（登记表）不许进基线：登记一行就能修，没有「存量」可言。其余规则对存量 workflow 允许按条目收编（只降不升）。
RATCHETABLE = ("W1", "W2", "W3", "W5", "W6")


def _load_baseline(path: Path = BASELINE) -> list[str]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(x) for x in (data.get("tolerated") or [])]


def apply_baseline(fails: list[str], tolerated: list[str]) -> list[str]:
    """基线棘轮（母仓「存量未清零首选 baseline 棘轮而非软化」的落法；2026-11-08 Krow-labs 全仓对齐加入）。

    - 基线里有的条目：存量，放过（它们是改 permissions / timeout 会影响发布链行为的旧 workflow，另开 PR 逐个收口）。
    - 基线里没有的：新增即红。
    - 基线里有、现在已经不红的：基线过期也红——必须跑 ``--update-baseline`` 收紧，棘轮只有收紧一个方向。
    """
    tol = set(tolerated)
    out = [f for f in fails if f not in tol]
    stale = sorted(tol - set(fails))
    for s in stale:
        out.append(f"BASELINE: 基线条目已修复但还在 scripts/data/workflows_baseline.json 里：「{s}」—— 跑 python3 scripts/lint_workflows.py --update-baseline 收紧棘轮")
    return out


def write_baseline(fails: list[str], *, init: bool, path: Path = BASELINE) -> int:
    import datetime as _dt
    bad = [f for f in fails if not f.startswith(RATCHETABLE)]
    if bad:
        print("× 这些条目不许进基线（W4 登记一行就能修）：", file=sys.stderr)
        for b in bad:
            print(f"    {b}", file=sys.stderr)
        return 1
    old = _load_baseline(path)
    if not init and path.is_file() and (set(fails) - set(old)):
        print("× --update-baseline 只能收紧：下面这些是基线里没有的新增违规，修掉它们而不是收编", file=sys.stderr)
        for f in sorted(set(fails) - set(old)):
            print(f"    {f}", file=sys.stderr)
        return 1
    if init and path.is_file():
        print("× 基线已存在；收紧用 --update-baseline", file=sys.stderr)
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "note": "W1–W6 存量基线（只降不升）。SSOT: scripts/lint_workflows.py；宪法 §0.2 F。条目逐字等于 lint 输出；修好一条就跑 --update-baseline 删掉它。",
        "updated": _dt.date.today().isoformat(),
        "tolerated": sorted(fails),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
    print(f"✓ 基线写入 {shown}：{len(fails)} 条存量")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--init-baseline", action="store_true", help="首次落地：以当前存量建基线")
    ap.add_argument("--update-baseline", action="store_true", help="收紧基线（只降不升）")
    args = ap.parse_args(argv)
    raw, names = lint()
    if args.init_baseline or args.update_baseline:
        return write_baseline(raw, init=args.init_baseline)
    fails = apply_baseline(raw, _load_baseline())
    if args.json:
        print(json.dumps({"fails": fails, "tolerated": _load_baseline(), "workflows": names}, ensure_ascii=False, indent=2))
    else:
        for f in fails:
            print(f"FAIL {f}")
        tol = len(_load_baseline())
        print(f"workflows: {len(fails)} FAIL · {len(names)} 个 workflow" + (f" · 基线存量 {tol} 条（只降不升）" if tol else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
