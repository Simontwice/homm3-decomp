from __future__ import annotations

import unittest
import json
import tempfile
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from homm3.match.status import MatchRow
from homm3.vc6.tu_state_sweep import (
    _files_digest, _initial_include_insertion, _project_header_pool, affected_by_unit,
    bank_rows, insertion_for, insert_variant, make_variants, _report_scores,
    _normalized_pair, state_reachable, _best_results, _sha256, PLACEMENT_TOP,
)


class TuStateSweepTests(unittest.TestCase):
    def test_candidate_first_pass_includes_compiler_data_claims(self):
        from homm3.vc6 import tu_state_sweep as sweep

        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "data.tsv"
            manifest.write_text(
                "object\tname\tsection_ordinal\tsection_offset\tsize\tstorage\tscope\tprovenance\n"
                "example.c\tsemantic-data\t2\t0x10\t4\tdata\tlocal\tsource-DATA_COMPGEN:test\n")
            expected = sweep.canon.load_compgen_data_claims(manifest, "example")
            with patch.object(sweep.normalize, "DATA_MANIFEST", manifest), \
                 patch.object(sweep, "_claims", return_value=((), frozenset())), \
                 patch.object(sweep.normalize, "data_names_for_unit", return_value={}), \
                 patch.object(sweep.canon, "canonicalize_coff",
                              return_value=SimpleNamespace(data=b"normalized")) as canonicalize:
                self.assertEqual(sweep._first_pass("example", b"raw"), b"normalized")
                canonicalize.assert_called_once_with(
                    b"raw", (), expected, compgen_accounted=frozenset(),
                    unit="example", data_names={})

    def test_candidate_uses_complete_shared_pair_pipeline(self):
        from homm3.vc6 import tu_state_sweep as sweep

        plan = SimpleNamespace(unit="example", target_first=b"retail-first")
        with patch.object(sweep, "_first_pass", return_value=b"candidate-first"), \
             patch.object(sweep.normalize, "_retail_symbol_rvas", return_value={}), \
             patch.object(sweep.normalize, "retail_image_base", return_value=0x400000), \
             patch.object(sweep.normalize, "canonicalize_pair",
                          return_value=(b"paired-base", b"paired-target", {})) as paired:
            self.assertEqual(_normalized_pair(plan, b"raw-candidate"),
                             (b"paired-base", b"paired-target"))
            paired.assert_called_once_with(b"candidate-first", b"retail-first",
                                           "example", {}, image_base=0x400000)

    def test_candidate_report_uses_full_build_relocation_mode(self):
        from homm3.build import configure

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "build/objdiff"
            live.mkdir(parents=True)
            with patch.object(configure, "ROOT", root):
                configure.write_objdiff({}, [{"unit": "example"}])
            live_options = json.loads((live / "objdiff.json").read_text())["options"]
            candidate = root / "candidate"
            candidate.mkdir()
            plan = SimpleNamespace(unit="example", scored=(("example", "body"),))

            def report(command, **kwargs):
                config = json.loads((candidate / "objdiff.json").read_text())
                self.assertEqual(config.get("options"), live_options)
                (candidate / "report.json").write_text(json.dumps({"units": [{
                    "functions": [{"name": "body", "fuzzy_match_percent": 98.0}]
                }]}))
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("homm3.vc6.tu_state_sweep.subprocess.run", side_effect=report):
                self.assertEqual(_report_scores(plan, b"base", b"target", candidate),
                                 {"body": 98.0})

    def test_groups_every_numeric_max_below_hist(self):
        rows = {
            ("a", "low"): MatchRow(80, 90, 100),
            ("a", "already-banked"): MatchRow(80, 100, 100),
            ("a", "equal"): MatchRow(100, 100, 100),
            ("b", "missing"): MatchRow(None, 80, 100),
            ("b", "low"): MatchRow(70, 70, 71),
        }
        self.assertEqual(affected_by_unit(rows), {
            "a": (("a", "low"),),
            "b": (("b", "low"),),
        })

    def test_one_insertion_precedes_earliest_affected_marker(self):
        text = ("#include <x>\n\nint before;\n\n// first evidence\n"
                "VA(0x00400100, 4)\nvoid first() {}\n\n"
                "// second evidence\nVA(0x00400200, 4)\nvoid second() {}\n")
        offset, line = insertion_for(text, (0x200, 0x100))
        self.assertTrue(text[offset:].startswith("\n// first evidence\n"))
        self.assertEqual(line, 4)

    def test_trial_inserts_one_include_block_for_the_whole_tu(self):
        text = ("#include <x>\n#include \"already.h\"\n\nint before;\n\n// first evidence\n"
                "VA(0x00400100, 4)\nvoid first() {}\n\n"
                "// second evidence\nVA(0x00400200, 4)\nvoid second() {}\n")
        offset, line = _initial_include_insertion(text)
        variant = make_variants(
            1, 20260906, "test", tuple(f"new{i}.h" for i in range(12)))[0]
        candidate = insert_variant(text, ((offset, line, 0),), variant)
        self.assertEqual(candidate.count("#line"), 1)
        self.assertEqual(sum(candidate.count(f'#include "new{i}.h"')
                             for i in range(12)),
                         len(variant.body.splitlines()))
        self.assertLess(candidate.index(variant.body), candidate.index("int before"))
        self.assertGreater(candidate.index(variant.body),
                           candidate.index('#include "already.h"'))

    def test_include_sequence_is_deterministic_and_has_five_to_ten_headers(self):
        headers = tuple(f"header{i}.h" for i in range(20))
        left = make_variants(30, 20260906, "unit", headers)
        right = make_variants(30, 20260906, "unit", headers)
        self.assertEqual(left, right)
        self.assertEqual(len(left), 30)
        self.assertTrue(all(5 <= len(item.body.splitlines()) <= 10
                            for item in left))
        self.assertTrue(all(len(set(item.body.splitlines())) ==
                            len(item.body.splitlines()) for item in left))

    def test_trailing_include_comment_does_not_swallow_injected_header(self):
        for ending in (' // reason\n', ' /* reason */\r\n', ''):
            text = '#include "original.h"' + ending
            offset, line = _initial_include_insertion(text)
            variant = make_variants(
                1, 1, "test", tuple(f"new{i}.h" for i in range(10)))[0]
            candidate = insert_variant(text, ((offset, line, 0),), variant)
            self.assertIn("\n" + variant.body, candidate)
            self.assertTrue(candidate.startswith(text))

    def test_input_fingerprint_detects_content_and_membership_changes(self):
        with tempfile.TemporaryDirectory() as raw:
            header = Path(raw) / "header.h"
            flags = Path(raw) / "units.toml"
            header.write_text("int first;\n")
            flags.write_text('/O2')
            original = _files_digest([header, flags])
            self.assertEqual(original, _files_digest([flags, header]))
            header.write_text("int other;\n")
            self.assertNotEqual(original, _files_digest([header, flags]))
            header.write_text("int first;\n")
            flags.write_text('/Od')
            self.assertNotEqual(original, _files_digest([header, flags]))
            self.assertNotEqual(original, _files_digest([header]))

    def test_include_insertion_is_outside_conditionals_comments_and_continuations(self):
        prefixes = (
            '#if 0\n#include "existing.h"\n#endif\n',
            '#if 0\n#if 1\n#include "existing.h"\n#endif\n#else\n#endif\n',
            '/*\n#include "existing.h"\n*/\n',
            '#define UNUSED \\\n  ignored\n',
            '// continued comment \\\n#if 0\n',
            '#if 0\nint hidden;\n#endif\n',
            '#define VA(a,b)\n#if 0\n#include "existing.h"\n#endif\n',
        )
        compiler = shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("C++ preprocessor unavailable")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "existing.h").write_text("")
            for i in range(10):
                (root / f"new{i}.h").write_text(f"int injected{i};\n")
            variant = make_variants(1, 1, "test", tuple(f"new{i}.h" for i in range(10)))[0]
            for prefix in prefixes:
                with self.subTest(prefix=prefix):
                    original = prefix + "int realBody() { return 0; }\n"
                    offset, line = _initial_include_insertion(original)
                    candidate = insert_variant(original, ((offset, line, 0),), variant)
                    result = subprocess.run(
                        [compiler, "-E", "-P", "-x", "c++", "-I", raw, "-"],
                        input=candidate, text=True, capture_output=True, check=True)
                    self.assertEqual(result.stdout.count("int injected"), len(variant.body.splitlines()))
                    self.assertIn("realBody", result.stdout)

    def test_tu_specific_invalid_header_pairings_are_excluded(self):
        self.assertNotIn(
            "kbwin.h", _project_header_pool('#include "diff.h"\n', "diff"))
        self.assertNotIn(
            "autostrptr.h",
            _project_header_pool('#include "spells.h"\n', "spells"))

    def test_editor_header_directories_are_not_in_the_game_pool(self):
        from homm3.vc6 import tu_state_sweep as sweep

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "include/editor").mkdir(parents=True)
            (root / "include/campaign_editor").mkdir()
            (root / "include/game.h").write_text("int game;\n")
            (root / "include/editor/OptionsDlg.h").write_text("afx_msg void f();\n")
            (root / "include/campaign_editor/resource.h").write_text("#define IDC_X 1\n")
            sweep._project_header_closure.cache_clear()
            sweep._project_header_macros.cache_clear()
            try:
                with patch.object(sweep.common, "HOMM3_DIR", root):
                    self.assertEqual(sweep._project_header_pool("int body;\n"), ("game.h",))
            finally:
                sweep._project_header_closure.cache_clear()
                sweep._project_header_macros.cache_clear()

    def test_bank_keeps_cur_and_raises_hist_only_for_new_peak(self):
        hashed = ("u", "hashed")
        no_hash = ("u", "generated")
        rows = {
            hashed: MatchRow(70, 80, 90, 0x100, "abc"),
            no_hash: MatchRow(20, 20, 25, 0x200, None),
        }
        updated, changes = bank_rows(
            rows, {hashed: 85, no_hash: 30}, {hashed: "abc"})
        self.assertEqual(updated[hashed], MatchRow(70, 85, 90, 0x100, "abc"))
        self.assertEqual(updated[no_hash], MatchRow(20, 30, 30, 0x200, None))
        self.assertEqual(len(changes), 2)

    def test_hash_mismatch_refuses_bank(self):
        key = ("u", "fn")
        row = MatchRow(70, 80, 100, 0x100, "old")
        updated, changes = bank_rows({key: row}, {key: 100}, {key: "new"})
        self.assertEqual(updated[key], row)
        self.assertEqual(changes, [])

    def _prediction(self, root, unit, source, functions, scored=True, digest=None):
        directory = root / unit
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "compile-m.json").write_text(json.dumps({
            "unit": unit, "scored": scored,
            "source_sha256": digest or _sha256(source.read_bytes()),
            "functions": {name: {"variants": [{"score": score} for score in scores]}
                          for name, scores in functions.items()}}))

    def test_state_reachable_rows_come_from_scored_current_predictions(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "a.cpp"
            source.write_text("int a;\n")
            stale = root / "b.cpp"
            stale.write_text("int b;\n")
            self._prediction(root, "a", source, {
                "better": [95.0, 100.0],
                "same": [90.0, 90.00001],
                "exact": [100.0, 99.0],
                "unscored": [None],
                "generated": [99.0],
            })
            self._prediction(root, "b", stale, {"better": [100.0]}, digest="old")
            self._prediction(root, "c", source, {"better": [100.0]}, scored=False)
            rows = {
                ("a", "better"): MatchRow(95, 95, 95),
                ("a", "same"): MatchRow(90, 90, 90),
                ("a", "exact"): MatchRow(100, 100, 100),
                ("a", "unscored"): MatchRow(80, 80, 80),
                ("a", "generated"): MatchRow(None, 50, 50),
                ("b", "better"): MatchRow(95, 95, 95),
                ("c", "better"): MatchRow(95, 95, 95),
            }
            sources = {"a": source, "b": stale, "c": source}
            found = state_reachable(rows, root, sources.get)
        self.assertEqual(found, {("a", "better"): 100.0})

    def test_reachable_rows_join_max_below_hist_targets(self):
        rows = {
            ("a", "low"): MatchRow(80, 90, 100),
            ("a", "reach"): MatchRow(95, 95, 95),
            ("b", "reach"): MatchRow(95, 95, 95),
        }
        self.assertEqual(
            affected_by_unit(rows, {("a", "reach"): 100.0, ("b", "reach"): 99.0}),
            {"a": (("a", "low"), ("a", "reach")), "b": (("b", "reach"),)})

    def test_top_placement_precedes_every_include(self):
        text = '#include "first.h"\nint body;\n'
        variant = make_variants(1, 1, "test", tuple(f"new{i}.h" for i in range(10)))[0]
        candidate = insert_variant(text, ((0, 1, 0),), variant)
        self.assertTrue(candidate.startswith(variant.body + "#line 1\n"))
        self.assertTrue(candidate.endswith(text))

    def test_best_result_remembers_its_placement(self):
        includes = SimpleNamespace(unit="u", key="u")
        top = SimpleNamespace(unit="u", key="u@" + PLACEMENT_TOP)
        results = {"u": [{"trial": 1, "scores": {"f": 95.0}}],
                   "u@top": [{"trial": 1, "scores": {"f": 100.0}},
                             {"trial": 2, "scores": {"f": 96.0}}]}
        self.assertEqual(_best_results([includes, top], results),
                         {("u", "f"): (100.0, 1, "u@top")})


if __name__ == "__main__":
    unittest.main()
