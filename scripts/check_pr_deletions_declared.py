#!/usr/bin/env python3
"""PR 里的文件删除必须在 PR 正文里被逐条写出来（PR-only 闸）。

移植自母仓 `aullik5/krow:scripts/lint_pr_deletions_declared.py`（`pr-base-guard.yml::deletions-must-be-declared`，
issue #2824）：`git reset --soft <ref>` 不动工作树、`git add -A` 以工作树为准——落后于 base 的分支会把 base 上
独有的文件整批记成删除，squash merge 忠实执行；被删的用例连同被测代码一起蒸发，没有任何判据会因此变红
（母仓 2026-09-18 实际发生：PR #2822 抹掉 #2816 的 1796 行，CI 一格没红）。

判据为什么是「写下来」而不是「判断该不该删」：删除是不是作者的意图是语义问题，System 1 判不了；硬判就会变成
按目录 / 按年龄猜的启发式。这里只做语法：**被删的每一条路径必须逐字出现在 PR 正文里**。它不判对错，它保证作者看见了。
被拦方的通过动作明确：把清单粘进正文核一遍——本该删的照常合，不该删的当场现形。

用法：
  python3 scripts/check_pr_deletions_declared.py --base origin/main --body-file <PR 正文文件>
  本地：gh pr view <n> --json body -q .body > /tmp/body.md
退出码：0 通过；1 有未声明的删除；2 读不到正文 / git 失败（**拒绝**，不放行——拿不到读数不等于通过）。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=True,
        encoding="utf-8", errors="replace",
    ).stdout


def deleted_paths(base: str, head: str = "HEAD") -> list[str]:
    """三点 diff（merge-base 比对）= GitHub PR diff 的口径；重命名不计（内容仍在仓里）。"""
    out = _git("diff", "--name-status", f"{base}...{head}").strip()
    paths: list[str] = []
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) >= 2 and fields[0].strip() == "D":
            paths.append(fields[1].strip())
    return paths


def behind_count(base: str, head: str = "HEAD") -> int:
    """head 落后 base 的提交数——只做诊断，不做判据（rebase 前的 PR 都落后）。"""
    return int(_git("rev-list", "--count", f"{head}..{base}").strip() or 0)


def undeclared(paths: list[str], body: str) -> list[str]:
    """逐字子串匹配，不做规范化：大小写折叠 / 只比 basename 都会让 a/x.py 被 b/x.py 顶掉。"""
    return [p for p in paths if p not in body]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--body-file", required=True, help="PR 正文文件（CI 从 github.event.pull_request.body 经 env 落盘）")
    args = ap.parse_args(argv)

    body_path = Path(args.body_file)
    if not body_path.exists():
        print(f"[pr-deletions] REFUSE 读不到 PR 正文：{body_path}——判据全靠正文，拿不到就没有读数，不放行也不假装通过。", file=sys.stderr)
        return 2
    body = body_path.read_text(encoding="utf-8", errors="replace")

    try:
        paths = deleted_paths(args.base, args.head)
        behind = behind_count(args.base, args.head)
    except subprocess.CalledProcessError as exc:
        print(f"[pr-deletions] REFUSE git 查询失败：{exc.stderr.strip()}（CI 需 fetch-depth: 0 并 fetch 到 base）", file=sys.stderr)
        return 2

    if not paths:
        print(f"[pr-deletions] OK 本 PR 没有删除文件（落后 base {behind} 个提交）")
        return 0
    missing = undeclared(paths, body)
    if not missing:
        print(f"[pr-deletions] OK {len(paths)} 条删除全部已在 PR 正文里写明")
        return 0

    print(f"[pr-deletions] FAIL {len(missing)}/{len(paths)} 条删除没有在 PR 正文里出现：", file=sys.stderr)
    for p in missing:
        print(f"    {p}", file=sys.stderr)
    if behind:
        print(
            f"\n  [!] 本分支落后 base {behind} 个提交。落后 + 删除正是 issue #2824 那次事故的形状：先 rebase 再看这些删除还在不在。",
            file=sys.stderr,
        )
    print("\n  怎么过：把下面这段粘进 PR 正文，逐条核一遍是不是你要删的（本该删的照常合，不该删的这一步就会现形）。\n", file=sys.stderr)
    print("  ## 本 PR 删除的文件", file=sys.stderr)
    for p in paths:
        print(f"  - `{p}`", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
