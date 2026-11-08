#!/usr/bin/env python3
"""AGENTS.md 的两道 System-1 闸：宪法不许分叉、本仓部分不许无限膨胀。

## 闸一：宪法一致性

宪法要在 `Krow-labs` 各仓**逐字一致**，否则它就不是宪法，是各自演化的建议。
而「复制到各仓」这个动作本身不产生任何持续约束：复制完的第二天，任何一个仓里
改一个字就开始分叉，而且没人会去逐字比对几份两百行的文档。

这正是反模式 A（声明 ≠ 生效）：宪法写进各仓 ≠ 各仓的宪法是同一部。

本脚本只校验**本仓这块有没有被改过**（比对内联的权威摘要）。跨仓一致性目前靠
三仓同批改 `CANONICAL_DIGEST`，无自动检查。

## 闸二：行数预算

§7 写着「上限 150 行」，但在此之前**没有任何东西执行它**——它是一条靠自觉的规则，
而 §7 自己就说了 AGENTS.md「会在无人看管时单调增长：每次事故都想往里加一段，
每段单独看都合理」。靠自觉挡单调增长，是把 System 1 的活派给了 System 2。

**预算只算宪法块以外的行。** 宪法不是本仓的累积物：它逐字一致、被哈希钉住、
在各仓只需被读懂一次。§7 那条上限要防的是**仓内内容的累积**，
把宪法算进去只会逼人去删该留的东西。

## actuation 落点（总则④ 要求）

两道都不是只加眼睛。红了的处置是明确的：宪法红 → **去把各仓改齐，不是改哈希将就**；
行数红 → **把内容挪进 `docs/`，本文件只留一行指针**。CI 拒绝合并就是那只手。

    python3 scripts/check_constitution.py
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

BEGIN = "<!-- krow:constitution:begin -->"
END = "<!-- krow:constitution:end -->"

#: 权威摘要。权威文本在 `Krow-labs/krow-bio: docs/constitution/TURBO.md`。
#: **改宪法时这个常量要跟着改，而且必须与其它仓同一批次改。**
CANONICAL_DIGEST = "ada93a23921620672e2de50ef39888f8f43529fbcce0c0e7be9b8dcc60452c3e"

#: 宪法块以外的行数上限，见 §7。宪法块不计入——理由见模块 docstring「闸二」。
LOCAL_LINE_BUDGET = 150


def main() -> int:
    agents = pathlib.Path(__file__).resolve().parent.parent / "AGENTS.md"
    if not agents.is_file():
        print(f"✗ 找不到 {agents}", file=sys.stderr)
        return 1
    text = agents.read_text(encoding="utf-8")
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < 0 or j < i:
        print(
            "✗ AGENTS.md 里没有宪法块。宪法必须**原样**出现在 AGENTS.md 里，"
            "不能只放一个指向别处的链接——进仓的人读的是 AGENTS.md，指针会被跳过。",
            file=sys.stderr,
        )
        return 1
    block = text[i : j + len(END)]
    got = hashlib.sha256(block.replace("\r\n", "\n").encode()).hexdigest()
    if got != CANONICAL_DIGEST:
        print(
            f"✗ 宪法块与权威文本不一致。\n"
            f"    本仓  {got}\n"
            f"    权威  {CANONICAL_DIGEST}\n\n"
            f"  权威文本：Krow-labs/krow-bio: docs/constitution/TURBO.md\n"
            f"  **不要改上面那个常量去将就本仓的改动。**\n"
            f"  宪法是有意改的 → 同一批次改遍所有仓，PR 描述里列出同批链接；\n"
            f"  宪法是被误改的 → 从权威文本还原。",
            file=sys.stderr,
        )
        return 1

    local = len((text[:i] + text[j + len(END) :]).splitlines())
    if local > LOCAL_LINE_BUDGET:
        print(
            f"✗ 宪法块以外 {local} 行，超出 §7 的 {LOCAL_LINE_BUDGET} 行上限"
            f"（超 {local - LOCAL_LINE_BUDGET} 行）。\n\n"
            f"  §7 说得很清楚：超了**不是「再精简一点」**，是必须把内容挪到 `docs/`"
            f" 下的专题文档，本文件只留一行指针。\n"
            f"  不要调高上面那个常量——上限本身就是这道闸的全部内容，调它等于把闸拆了。",
            file=sys.stderr,
        )
        return 1

    print(f"✓ 宪法块一致（{got[:16]}…）；宪法外 {local}/{LOCAL_LINE_BUDGET} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
