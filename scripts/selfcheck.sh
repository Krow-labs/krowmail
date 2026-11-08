#!/usr/bin/env bash
# 本地自查 = CI required check 同口径一次跑完（「验证是一步」）。Krow-labs 便携治理包 krow-labs-governance-core/1。
#   bash scripts/selfcheck.sh
# PR-only 的两道（base 必须 main / 删除必须声明）需要 PR 正文：
#   gh pr view <n> --json body -q .body > /tmp/body.md && python3 scripts/check_pr_deletions_declared.py --base origin/main --body-file /tmp/body.md
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
if [ -x .venv/bin/python ]; then PY=".venv/bin/python"; fi
FAILS=0
step() {  # step <名字> <命令...>
  local name="$1"; shift
  printf '\n### %s\n' "$name"
  if "$@"; then printf '    → OK\n'; else printf '    → FAIL (%s)\n' "$name"; FAILS=$((FAILS+1)); fi
}
echo "repo: $(pwd) · python: $($PY --version 2>&1) · base: origin/main=$(git rev-parse --short origin/main 2>/dev/null || echo '?')"
"$PY" -c "import yaml, pytest" 2>/dev/null || echo "提示：治理脚本要 pyyaml + pytest（$PY -m pip install pyyaml pytest）"

step "constitution" "$PY" scripts/check_constitution.py
step "治理脚本自测" "$PY" -m pytest scripts/tests/test_lint_workflows.py scripts/tests/test_lint_secret_scan.py scripts/tests/test_check_pr_deletions_declared.py scripts/tests/test_lint_governance_g11.py -q -p no:cacheprovider
step "enforce 起步闸自测" "$PY" scripts/test_lint_enforce_start.py
step "G 系列（--strict：WARN 也红）" "$PY" scripts/lint_governance.py --strict
step "W1–W6 workflow 卫生" "$PY" scripts/lint_workflows.py
step "enforce 起步闸" "$PY" scripts/lint_enforce_start.py
step "secret scan" "$PY" scripts/lint_secret_scan.py


echo
if [ "$FAILS" -gt 0 ]; then echo "selfcheck: $FAILS 项 FAIL"; exit 1; else echo "selfcheck: 全绿（与 CI required check「governance lint」同口径）"; exit 0; fi
