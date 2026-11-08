"""`scripts/lint_workflows.py` 的病理形态用例：每条 W 规则各一条「该红」+ 整体一条「该绿」。"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import textwrap

_SPEC = importlib.util.spec_from_file_location(
    "lint_workflows", pathlib.Path(__file__).resolve().parents[1] / "lint_workflows.py"
)
lw = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = lw
_SPEC.loader.exec_module(lw)

GOOD = textwrap.dedent(
    """
    name: good
    on:
      pull_request:
      push: { branches: [main] }
    concurrency:
      group: "g-${{ github.ref }}"
      cancel-in-progress: true
    permissions: { contents: read }
    jobs:
      a:
        name: check a
        runs-on: ubuntu-latest
        timeout-minutes: 5
        steps: [{ run: "true" }]
    """
)


def _repo(tmp_path: pathlib.Path, workflows: dict[str, str], contributing: str = "", required: str = "") -> pathlib.Path:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    for name, text in workflows.items():
        (wf / name).write_text(text, encoding="utf-8")
    (tmp_path / "CONTRIBUTING.md").write_text(contributing or " ".join(f"`{n}`" for n in workflows), encoding="utf-8")
    if required:
        (tmp_path / ".github" / "required-checks.txt").write_text(required, encoding="utf-8")
    return tmp_path


def codes(fails: list[str]) -> set[str]:
    return {f.split(":", 1)[0] for f in fails}


def test_healthy_workflow_passes(tmp_path: pathlib.Path):
    fails, names = lw.lint(_repo(tmp_path, {"good.yml": GOOD}))
    assert fails == [] and names == {"good.yml": "good"}


def test_w1_missing_timeout(tmp_path: pathlib.Path):
    fails, _ = lw.lint(_repo(tmp_path, {"g.yml": GOOD.replace("    timeout-minutes: 5\n", "")}))
    assert codes(fails) == {"W1"}


def test_w2_missing_permissions_everywhere(tmp_path: pathlib.Path):
    fails, _ = lw.lint(_repo(tmp_path, {"g.yml": GOOD.replace("permissions: { contents: read }\n", "")}))
    assert codes(fails) == {"W2"}


def test_w2_job_level_permissions_are_enough(tmp_path: pathlib.Path):
    text = GOOD.replace("permissions: { contents: read }\n", "").replace("    timeout-minutes: 5\n", "    timeout-minutes: 5\n    permissions: { contents: read }\n")
    fails, _ = lw.lint(_repo(tmp_path, {"g.yml": text}))
    assert fails == []


def test_w3_pr_workflow_without_cancel_in_progress(tmp_path: pathlib.Path):
    fails, _ = lw.lint(_repo(tmp_path, {"g.yml": GOOD.replace("cancel-in-progress: true", "cancel-in-progress: false")}))
    assert codes(fails) == {"W3"}


def test_w4_unregistered_workflow(tmp_path: pathlib.Path):
    fails, _ = lw.lint(_repo(tmp_path, {"good.yml": GOOD}, contributing="没有点名任何 workflow"))
    assert codes(fails) == {"W4"}


def test_w5_workflow_run_must_match_name_verbatim(tmp_path: pathlib.Path):
    listener = textwrap.dedent(
        """
        name: rerun
        on:
          workflow_run:
            workflows: ["good.yml"]
            types: [completed]
        permissions: { contents: read }
        jobs:
          r: { runs-on: ubuntu-latest, timeout-minutes: 5, steps: [{ run: "true" }] }
        """
    )
    fails, _ = lw.lint(_repo(tmp_path, {"good.yml": GOOD, "rerun.yml": listener}))
    assert codes(fails) == {"W5"}
    fails, _ = lw.lint(_repo(tmp_path, {"good.yml": GOOD, "rerun.yml": listener.replace('"good.yml"', '"good"')}))
    assert fails == []


def test_w6_required_check_behind_paths_filter(tmp_path: pathlib.Path):
    filtered = GOOD.replace("  pull_request:\n", "  pull_request:\n    paths: ['src/**']\n")
    fails, _ = lw.lint(_repo(tmp_path, {"good.yml": filtered}, required="check a\n"))
    assert codes(fails) == {"W6"}


# ── 基线棘轮（2026-11-08 Krow-labs 全仓对齐加入）──────────────────────────────

def test_baseline_tolerates_listed_and_fails_new():
    raw = ["W1: a.yml job `x` 缺 timeout-minutes", "W2: a.yml job `x` 没有 permissions（顶层也没有）——GITHUB_TOKEN 缺省是宽权限"]
    assert lw.apply_baseline(raw, raw) == []
    out = lw.apply_baseline(raw + ["W1: b.yml job `y` 缺 timeout-minutes"], raw)
    assert out == ["W1: b.yml job `y` 缺 timeout-minutes"]


def test_baseline_stale_entry_fails_until_tightened():
    out = lw.apply_baseline([], ["W1: a.yml job `x` 缺 timeout-minutes"])
    assert len(out) == 1 and out[0].startswith("BASELINE:") and "--update-baseline" in out[0]


def test_baseline_refuses_w4(tmp_path: pathlib.Path):
    rc = lw.write_baseline(["W4: a.yml 没在 CONTRIBUTING.md 的 CI 表里登记（不在治理表里 ≡ 没人负责）"], init=True, path=tmp_path / "b.json")
    assert rc == 1 and not (tmp_path / "b.json").exists()


def test_baseline_update_only_tightens(tmp_path: pathlib.Path):
    b = tmp_path / "b.json"
    assert lw.write_baseline(["W1: a.yml job `x` 缺 timeout-minutes"], init=True, path=b) == 0
    # 新增违规不许被 --update-baseline 收编
    assert lw.write_baseline(["W1: a.yml job `x` 缺 timeout-minutes", "W1: a.yml job `z` 缺 timeout-minutes"], init=False, path=b) == 1
    # 修好了可以收紧
    assert lw.write_baseline([], init=False, path=b) == 0
    assert lw._load_baseline(b) == []


def test_w6_required_name_must_match_a_pr_job(tmp_path):
    """required-checks.txt 里的名字对不上任何 pull_request job → W6 红；matrix 形式「name (值)」放行。"""
    wf = GOOD + (
        "  test:\n"
        "    strategy: { matrix: { os: [ubuntu-latest] } }\n"
        "    runs-on: ubuntu-latest\n"
        "    timeout-minutes: 5\n"
        '    steps: [{ run: "true" }]\n'
    )
    root = _repo(tmp_path, {"ci.yml": wf}, contributing="| `ci.yml` | x |\n", required="check a\ntest (ubuntu-latest)\nghost\n")
    fails, _ = lw.lint(root)
    w6 = [f for f in fails if f.startswith("W6")]
    assert len(w6) == 1 and "ghost" in w6[0], fails
