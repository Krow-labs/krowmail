#!/usr/bin/env python3
"""`lint_enforce_start.py` 自测 —— 每条规则都要证明「拦得住」和「放得过」两面。

闸门最危险的失效方式是恒绿：正则写歪了，什么都认不出来，于是永远通过。
所以每条规则至少一条「该红」的用例；只测「该绿」的等于没测。

    python3 scripts/test_lint_enforce_start.py
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
import tempfile
import textwrap
import unittest

_SPEC = importlib.util.spec_from_file_location(
    "lint_enforce_start", pathlib.Path(__file__).with_name("lint_enforce_start.py")
)
les = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = les
_SPEC.loader.exec_module(les)

TODAY = dt.date(2026, 9, 26)
CFG = {
    "flags": [
        {
            "globs": ["src/*.rs"],
            "pattern": r"env_bool\(\s*\"(?P<name>[A-Z][A-Z0-9_]+)\"\s*,\s*(?P<default>true|false)\s*\)",
        },
        {
            "globs": ["app/*.py"],
            "pattern": r"environ\.get\(\s*\"(?P<name>[A-Z][A-Z0-9_]+)\"\s*,\s*\"(?P<default>[^\"]*)\"\s*\)\s*(?:==|in\b)",
        },
    ],
    "configmap_drift": {"files": ["cm.yaml"], "exempt": {}},
}


class _Repo:
    def __init__(self, files: dict[str, str]):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        for rel, body in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(body), encoding="utf-8")

    def run(self, cfg=CFG, baseline=None):
        rep = les.run(self.root, cfg, TODAY)
        les.check_ratchet(rep, baseline or {})
        return rep

    def close(self):
        self._tmp.cleanup()


def _errs(rep) -> str:
    return "\n".join(rep.errors)


class WarningOnlySteps(unittest.TestCase):
    WF = """\
        jobs:
          lint:
            runs-on: ubuntu-latest
            steps:
              - name: soft
                continue-on-error: true
                run: cargo clippy
              # enforce-by: 2026-10-10
              - name: dated
                run: |
                  cargo fmt --check || true
              - name: swallowed
                run: |
                  ruff check . || true
        """

    def test_unmarked_soft_steps_are_counted_and_marked_ones_are_not(self):
        r = _Repo({".github/workflows/ci.yml": self.WF})
        rep = r.run()
        self.assertEqual(len(rep.unmarked_steps), 2, rep.unmarked_steps)
        self.assertIn("未标期限的 warning-only 步骤 2 > 基线 0", _errs(rep))
        r.close()

    def test_baseline_holds_existing_count_and_shrink_demands_tightening(self):
        r = _Repo({".github/workflows/ci.yml": self.WF})
        self.assertNotIn("warning-only", _errs(r.run(baseline={"warning_only_unmarked": 2})))
        self.assertIn("--update-baseline", _errs(r.run(baseline={"warning_only_unmarked": 3})))
        r.close()


class EnforceByDates(unittest.TestCase):
    def test_expired_and_far_future_are_red_done_and_near_are_green(self):
        r = _Repo(
            {
                "a.rs": "// enforce-by: 2026-09-01\n",
                "b.rs": "// enforce-by: 2027-01-01\n",
                "c.rs": "// enforce-by: 2026-09-01 enforce-by-done: 2026-09-20\n",
                "d.rs": "// enforce-by: 2026-10-20\n",
            }
        )
        errs = _errs(r.run())
        self.assertIn("a.rs:1: enforce-by 2026-09-01 已过期", errs)
        self.assertIn("b.rs:1: enforce-by 2027-01-01 距今", errs)
        self.assertNotIn("c.rs", errs)
        self.assertNotIn("d.rs", errs)
        r.close()


class DefaultOffFlags(unittest.TestCase):
    SRC = """\
        fn from_env() {
            let a = env_bool("KW_FF_OLD", false);
            // retire-when: 消融实验出结论
            let b = env_bool("KW_FF_MARKED", false);
            let c = env_bool("KW_FF_NEIGHBOUR", false);
            let d = env_bool("KW_FF_ON", true);
        }
        """

    def test_new_default_off_flag_is_red_unless_marked_right_above(self):
        r = _Repo({"src/config.rs": self.SRC})
        errs = _errs(r.run(baseline={"default_off_flags": ["KW_FF_OLD"]}))
        self.assertIn("KW_FF_NEIGHBOUR", errs, "紧贴上一行的标记不许顺带罩住相邻开关")
        self.assertNotIn("KW_FF_MARKED", errs)
        self.assertNotIn("KW_FF_ON", errs)
        r.close()

    def test_stale_baseline_entry_is_red(self):
        r = _Repo({"src/config.rs": self.SRC})
        errs = _errs(r.run(baseline={"default_off_flags": ["KW_FF_OLD", "KW_FF_NEIGHBOUR", "KW_FF_GONE"]}))
        self.assertIn("KW_FF_GONE", errs)
        self.assertIn("--update-baseline", errs)
        r.close()

    def test_python_default_off_flag_is_recognised(self):
        r = _Repo({"app/x.py": 'import os\nX = os.environ.get("KWB_SPARSE", "") in ("1", "true")\n'})
        self.assertIn("KWB_SPARSE", r.run().default_off)
        r.close()

    def test_exclude_globs_drop_test_fixtures(self):
        body = 'import os\nX = os.environ.get("KWB_SPARSE", "") in ("1", "true")\n'
        r = _Repo({"app/x.py": body, "app/tests/test_x.py": body.replace("KWB_SPARSE", "KWB_FIXTURE")})
        cfg = {"flags": [dict(CFG["flags"][1], exclude_globs=["*/tests/*"])]}
        off = r.run(cfg=cfg).default_off
        self.assertIn("KWB_SPARSE", off)
        self.assertNotIn("KWB_FIXTURE", off, "exclude_globs 命中的路径不该计入")
        r.close()


class ConfigmapDrift(unittest.TestCase):
    def test_configmap_value_differing_from_code_default_is_red(self):
        r = _Repo(
            {
                "src/config.rs": 'env_bool("KW_FF_A", false); env_bool("KW_FF_B", true);\n',
                "cm.yaml": 'data:\n  KW_FF_A: "true"\n  KW_FF_B: "true"\n',
            }
        )
        errs = _errs(r.run(baseline={"default_off_flags": ["KW_FF_A"]}))
        self.assertIn('KW_FF_A=true 与代码默认值 false 漂移', errs)
        self.assertNotIn("KW_FF_B=", errs)
        r.close()

    def test_deployment_env_value_differing_from_code_default_is_red(self):
        r = _Repo({
            "src/config.rs": 'fn f() { env_bool("KF_GC_DELETE", false); env_bool("KF_OK", true); }\n',
            "cm.yaml": """\
                env:
                  - name: KF_GC_DELETE
                    value: 'true'
                  - name: KF_OK
                    value: "true"
                """,
        })
        errs = _errs(r.run(baseline={"default_off_flags": ["KF_GC_DELETE"]}))
        self.assertIn("cm.yaml:3: KF_GC_DELETE=true", errs, "Deployment env 写法也要认出漂移")
        self.assertNotIn("KF_OK", errs)
        r.close()

    def test_exempt_key_passes_and_cross_file_conflict_is_red(self):
        r = _Repo(
            {
                "src/a.rs": 'env_bool("KW_FF_A", false);\n',
                "src/b.rs": 'env_bool("KW_FF_A", true);\n',
                "cm.yaml": 'data:\n  KW_FF_A: "true"\n',
            }
        )
        cfg = dict(CFG, configmap_drift={"files": ["cm.yaml"], "exempt": {"KW_FF_A": "理由"}})
        errs = _errs(r.run(cfg=cfg, baseline={"default_off_flags": ["KW_FF_A"]}))
        self.assertIn("同一开关在不同代码处默认值不一致", errs)
        self.assertNotIn("漂移", errs)
        r.close()


class BaselineOnlyShrinks(unittest.TestCase):
    def test_update_refuses_to_bake_in_a_new_default_off_flag(self):
        r = _Repo({"src/config.rs": 'env_bool("KW_FF_NEW", false);\n'})
        rep = les.run(r.root, CFG, TODAY)
        saved = les.BASELINE_PATH
        les.BASELINE_PATH = r.root / "baseline.json"
        try:
            self.assertEqual(les.write_baseline(rep, {"default_off_flags": []}, init=False), 1)
            self.assertFalse(les.BASELINE_PATH.exists())
        finally:
            les.BASELINE_PATH = saved
        r.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)
