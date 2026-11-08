"""G11 的病理形态：required-checks.txt 里的名字必须能在 on: pull_request 的 workflow 里找到对应 job（含 matrix 展开名）。"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("lint_governance", ROOT / "scripts" / "lint_governance.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

WF = """name: ci
on: [pull_request, push]
jobs:
  plain:
    name: plain check
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
  test:
    strategy:
      matrix: {os: [ubuntu-latest, windows-latest], python: ["3.11", "3.13"]}
    runs-on: ${{ matrix.os }}
    steps: [{run: "true"}]
  nightly_only:
    name: nightly
    runs-on: ubuntu-latest
    steps: [{run: "true"}]
"""


def _repo(tmp_path, required: str, workflow: str = WF):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text(workflow, encoding="utf-8")
    (tmp_path / ".github" / "required-checks.txt").write_text(required, encoding="utf-8")
    lg.REPO_ROOT = tmp_path
    rep = lg.Report()
    lg.g11_required_checks(rep)
    return [f for f in rep.fails if f.startswith("G11")] if hasattr(rep, "fails") else [m for m in getattr(rep, "messages", []) if "G11" in m]


def test_plain_and_matrix_names_pass(tmp_path):
    fails = _repo(tmp_path, "plain check\ntest (ubuntu-latest, 3.13)\ntest (windows-latest, 3.11)\n")
    assert fails == [], fails


def test_unknown_name_fails(tmp_path):
    fails = _repo(tmp_path, "plain check\nno-such-job\n")
    assert len(fails) == 1 and "no-such-job" in fails[0]


def test_matrix_form_on_non_matrix_job_fails(tmp_path):
    fails = _repo(tmp_path, "plain check (ubuntu-latest)\n")
    assert len(fails) == 1 and "plain check (ubuntu-latest)" in fails[0]


def test_job_in_non_pr_workflow_fails(tmp_path):
    wf = WF.replace("on: [pull_request, push]", "on: [push]")
    fails = _repo(tmp_path, "plain check\n", workflow=wf)
    assert len(fails) == 1
