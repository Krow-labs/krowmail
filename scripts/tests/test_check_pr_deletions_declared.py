"""`scripts/check_pr_deletions_declared.py` 的病理形态用例：在临时 git 仓里造「落后 + 删除」，证明闸拦得住、放得过、拿不到正文就拒绝。"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_pr_deletions_declared", pathlib.Path(__file__).resolve().parents[1] / "check_pr_deletions_declared.py"
)
cpd = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = cpd
_SPEC.loader.exec_module(cpd)


def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "keep.py").write_text("1\n", encoding="utf-8")
    (r / "gone.py").write_text("2\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "checkout", "-q", "-b", "feature")
    (r / "gone.py").unlink()
    (r / "renamed_from.py").write_text("3\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "delete gone.py")
    _git(r, "mv", "renamed_from.py", "renamed_to.py")
    _git(r, "commit", "-q", "-m", "rename")
    # base 往前走一步 → 分支落后 1
    _git(r, "checkout", "-q", "main")
    (r / "later.py").write_text("4\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "later")
    _git(r, "checkout", "-q", "feature")
    monkeypatch.setattr(cpd, "REPO_ROOT", r)
    return r


def test_deleted_paths_is_three_dot_and_ignores_renames(repo: pathlib.Path):
    assert cpd.deleted_paths("main") == ["gone.py"]
    assert cpd.behind_count("main") == 1


def test_fails_when_deletion_not_in_body(repo: pathlib.Path, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]):
    body = tmp_path / "body.md"
    body.write_text("只删了 keep.py 以外的东西\n", encoding="utf-8")
    assert cpd.main(["--base", "main", "--body-file", str(body)]) == 1
    err = capsys.readouterr().err
    assert "gone.py" in err and "落后 base 1" in err


def test_passes_when_every_deletion_is_verbatim_in_body(repo: pathlib.Path, tmp_path: pathlib.Path):
    body = tmp_path / "body.md"
    body.write_text("## 本 PR 删除的文件\n- `gone.py`\n", encoding="utf-8")
    assert cpd.main(["--base", "main", "--body-file", str(body)]) == 0


def test_case_folding_is_not_a_match(repo: pathlib.Path, tmp_path: pathlib.Path):
    # 逐字匹配、不折叠大小写：正文只写了 `Gone.py` 时必须红（母仓同口径）。
    body = tmp_path / "body.md"
    body.write_text("删了 Gone.py\n", encoding="utf-8")
    assert cpd.main(["--base", "main", "--body-file", str(body)]) == 1


def test_missing_body_is_refusal_not_pass(repo: pathlib.Path, tmp_path: pathlib.Path):
    assert cpd.main(["--base", "main", "--body-file", str(tmp_path / "nope.md")]) == 2
