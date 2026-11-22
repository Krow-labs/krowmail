# 贡献指南

```
分支（从 main 开）──► 本地自查 `bash scripts/selfcheck.sh` ──► PR 到 main（base 只能是 main；squash；必需检查全绿；非作者评审）──► 合后删分支
```

## 本地自查

一条命令，与 CI required check 同口径：`bash scripts/selfcheck.sh`。它逐条跑的是：

```bash
python3 scripts/check_constitution.py                                               # constitution
python3 -m pytest scripts/tests/test_lint_workflows.py scripts/tests/test_lint_secret_scan.py scripts/tests/test_check_pr_deletions_declared.py scripts/tests/test_lint_governance_g11.py -q && python3 scripts/test_lint_enforce_start.py   # 闸的病理形态用例
python3 scripts/lint_governance.py --strict                                         # G1 / G2 / G10 / G11（组员仓含 G3–G9）
python3 scripts/lint_workflows.py                                                   # W1–W6（存量基线只降不升）
python3 scripts/ci_runs_on.py check                                                 # runs-on 只写类别（CI 统一调度；本仓没有基线）
python3 scripts/lint_enforce_start.py                                               # enforce 起步闸
python3 scripts/lint_secret_scan.py                                                 # 内容级凭证扫描
# 语言门沿用既有 ci.yml（见上表）
```

PR-only 的两道（base 必须 `main` / 删除必须在正文写明）本地这样跑：
`gh pr view <n> --json body -q .body > /tmp/body.md && python3 scripts/check_pr_deletions_declared.py --base origin/main --body-file /tmp/body.md`。

## CI

> 这张表是 workflow 登记表（`scripts/lint_workflows.py` W4：`.github/workflows/` 下每个文件都必须在这里被反引号点名；不在表里 ≡ 没人负责）。

| workflow | 跑什么 | 前提 |
|---|---|---|
| `.github/workflows/ci.yml` | jobs: `test` | 触发 pull_request, push |
| `.github/workflows/governance.yml` | jobs: `constitution` · `governance lint` | 触发 pull_request, push, workflow_dispatch |

机器去向（CI 统一调度）：job 的 `runs-on` 只声明要哪类机器（`light` / `heavy` / `docker` / `vm` / `macos` / `windows` / `release` …），去哪台由调度器写的仓库变量 `KROW_CI_TABLE` 定；表不在或 fork 来的 PR 用那一行末尾的回落标签。新 job 的那一行用 `python3 scripts/ci_runs_on.py render <类别> <回落标签>` 生成。`scripts/ci_runs_on.py` 与 krowworker 仓 scripts/ci/ 下的同名文件逐字相同，不在本仓单独改；本仓的 job 已全部接入，没有基线文件，新 job 不写类别这一步就红。

required check 的清单在 `.github/required-checks.txt`（与 GitHub 分支规则同日同步）；新闸优先接进已是 required 的 job，不新增 check 名。改 workflow 看 `.cursor/rules/governance-change.mdc`。
