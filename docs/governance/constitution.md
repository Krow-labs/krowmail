# 本仓宪法（Krow-labs 便携治理包 `krow-labs-governance-core/1`）

> 权威源不在本仓：TURBO 宪法在 `Krow-labs/krow-bio:docs/constitution/TURBO.md`（本仓 `AGENTS.md` 宪法块逐字收录，`scripts/check_constitution.py` 钉哈希）；
> 研发纪律与元规则基准是 `aullik5/krow@30b5504f`（`AGENTS.md` §零–§十二、`.cursor/rules/*.mdc`、`lint.yml`、`pr-base-guard.yml`）。
> 上游路径写成 `<仓>:<路径>`，G10 只核本仓路径。本文只写上位规则落到本仓怎么执行，以及对应的物理闸。

| 上位规则 | 本仓执行 | 物理闸 |
|---|---|---|
| 准确性 > 完整性 > 速度 > 成本；错就 fail-loud | 新闸 enforce 起步，软化必带 `enforce-by` ≤30 天 | `scripts/lint_enforce_start.py` |
| 声明 ≠ 生效（反模式 A） | 规则必须有闸；required check 名逐字等于 job 名 | `scripts/lint_governance.py` G11、`scripts/lint_workflows.py` W6 |
| 半边墙（反模式 B） | 每道闸带病理用例，CI 第一步先跑 | `scripts/tests/`、`scripts/test_lint_enforce_start.py` |
| 凭据不进仓 | 内容级扫描 + 路径级推送规则 | `scripts/lint_secret_scan.py` |
| 删除要留痕 | PR 删除的文件逐条写进正文 | `scripts/check_pr_deletions_declared.py`（PR-only） |
| base 必须默认分支、不叠 PR | PR-only 守门 | `.github/workflows/` governance job |
| 元规则不膨胀、不分叉 | 宪法块钉哈希；宪法外 ≤150 行；`.mdc` 必登记 | `scripts/check_constitution.py`、G1 / G2 |
| workflow 卫生 | timeout / permissions / concurrency / 登记表 | `scripts/lint_workflows.py` W1–W6 |

本地一条命令：`bash scripts/selfcheck.sh`。决定记录：`docs/governance/decisions.md`。
