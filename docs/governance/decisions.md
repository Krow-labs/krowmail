# 决定记录（ADR）

一条决定一节，编号 `D-NNN` 只增不改；推翻用新条目引用旧条目。退役 / 边界模块必须在这里被点名（`scripts/lint_governance.py` G9）。

## D-001 · 2026-11-08 · 治理对齐 krow 母仓 `aullik5/krow@30b5504f`（Krow-labs 全仓对齐，任务 8393887e）

- **基准**：母仓默认分支 `main` 提交 `30b5504f027617f9da661918d7614ae4540ac7c1`（2026-11-08，#3621 合入后）的实际执行链——`AGENTS.md` §零–§十二 + `.cursor/rules/*.mdc`（`lint_mdc.py` 守）+ `lint.yml`（governance-invariants / secret-scan / test-naming / 棘轮家族）+ `pr-base-guard.yml`（base 必须 main + 删除必须声明）+ `main` 分支保护（4 项 required + 1 评审 + 会话解决 + 最新化）。只取「通用且本仓适用」的项，不照搬 ACT / klik / SDK 专属闸；Turbo 已退役，不新增 Turbo 专属测试。
- **本 PR 落地**：① 宪法块逐字 + `scripts/check_constitution.py`；② `scripts/lint_governance.py`（G1 行数 + 灵魂关键词 / G2 `.mdc` frontmatter 与登记 / G10 点名路径存在 / G11 required check ↔ job 名；非组员仓跳过 G3–G8）；③ 语言门沿用既有 CI（不改业务 workflow）；④ `scripts/lint_workflows.py` W1–W6（存量 3 条进 `scripts/data/workflows_baseline.json` 棘轮，只降不升，W4 不许进基线）；⑤ `scripts/lint_enforce_start.py`（krow-bio 权威副本原样，`scripts/data/enforce_start.json` 配置）；⑥ `scripts/lint_secret_scan.py`（母仓判据 + 多语种后缀）；⑦ `scripts/check_pr_deletions_declared.py` + PR base 必须 `main`（PR-only）；⑧ 病理用例 `scripts/tests/`，CI 第一步先跑；⑨ `.cursor/rules/governance-change.mdc`；⑩ `.github/required-checks.txt` 仓内镜像；⑪ `CONTRIBUTING.md` CI 登记表；⑫ `.gitattributes`（LF）；⑬ `scripts/selfcheck.sh`。
- **接线**：新建 `.github/workflows/governance.yml`（job `constitution` + `governance lint`），合入后把两者加入默认分支 required checks。
- **不动的**：业务代码与既有 workflow 的语义（不改它们的 permissions / 触发 / 发布链）；宪法块；既有同源脚本。
- **母仓有、本仓判定不适用**：`lint_version_authority.py`（无用户授权版本门的发布形态）/ `tests/MAP.md` 测试命名 lint（规模不足）/ `agent_session_init.py` worktree 协议（工作台纪律在平台侧）/ `lint_merged_branch_cleanup.py`（合并即删分支由仓库设置承担）/ ACT · klik · SDK 打包 · nightly 预算等母仓业务专属闸。
- AGENTS.md：新建
- **形态覆盖**：既有 `ci.yml` job `test`（`scripts/lint_spec.py` + `cargo test` + `clippy -D warnings`）近 3 次 `main` 运行全绿，作为本仓语言门一并设为 required；不另写 ci.yml
