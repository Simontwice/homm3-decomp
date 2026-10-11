import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from homm3.cleanliness import board


class ContainerHelperMetrics(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "src").mkdir()
        (self.root / "include").mkdir()
        self.baseline = self.root / "baseline.tsv"
        for name, value in (("REPO", self.root), ("BASELINE", self.baseline)):
            replacement = patch.object(board, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def write_source(self, text):
        (self.root / "src/sample.cpp").write_text(text)

    def gate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return board.check_and_roll(write=True, dc_origins=[])

    def test_embedded_controls(self):
        self.assertEqual(board.selftest(), [])

    def test_counts_code_and_reports_each_site(self):
        self.write_source('''
// std::_MIN(a, b); values.insert(values.end(), value);
const char* description = "std::_Sort insert(end(), value)";
void append() {
    values.insert(
        values.end(), std::_cpp_min(a, b));
    values.insert(where, values.begin(), values.end());
    values.insert(values.end(), first, last);
}
''')
        (self.root / "include/helpers.h").write_text(
            "inline int helper() { return std :: _MAX(a, b); }\n")
        rows, offenders = board.count(per_file=True, dc_origins=[])
        counts = dict(rows)
        self.assertEqual(counts["end-position inserts"], 2)
        self.assertEqual(counts["std internal references"], 2)
        self.assertEqual(sum(label == "end-position inserts"
                             for label, _ in offenders), 2)
        self.assertIn(("end-position inserts", "src/sample.cpp:5: insert("),
                      offenders)

    def test_new_metrics_ratchet_and_reject_regrowth(self):
        self.write_source(
            "values.insert(values.end(), std::_cpp_min(a, b));\n")
        self.assertEqual(self.gate(), [])
        initial = board.load_baseline()
        self.assertEqual(initial["end-position inserts"], 1)
        self.assertEqual(initial["std internal references"], 1)
        self.write_source("values.push_back(min(a, b));\n")
        self.assertEqual(self.gate(), [])
        lowered = self.baseline.read_text()
        self.write_source(
            "values.insert(values.end(), std::_cpp_min(a, b));\n")
        violations = self.gate()
        self.assertTrue(any("end-position inserts rose 0 -> 1" in line
                            for line in violations))
        self.assertTrue(any("std internal references rose 0 -> 1" in line
                            for line in violations))
        self.assertEqual(self.baseline.read_text(), lowered)


class SanctionedFeatureSwitch(unittest.TestCase):
    """HOMM3_RMG_HOTFIX is a reviewed whole-build feature flag, not a per-TU
    view: its conditionals are reported on their own unratcheted row."""

    FLAG = "HOMM3" + "_RMG_HOTFIX"
    SCAFFOLD = "HOMM3" + "_SAMPLE_DECLS"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "src").mkdir()
        (self.root / "include").mkdir()
        self.baseline = self.root / "baseline.tsv"
        for name, value in (("REPO", self.root), ("BASELINE", self.baseline)):
            replacement = patch.object(board, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)

    def write(self, text):
        (self.root / "src/rmg.cpp").write_text(text)

    def gate(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return board.check_and_roll(write=True, dc_origins=[])

    def test_conditionals_are_reported_not_scaffolds(self):
        self.write(f"#if defined({self.FLAG})\nint a;\n#endif\n"
                   f"#ifndef {self.FLAG}\nint b;\n#endif\n")
        counts = dict(board.count(dc_origins=[]))
        self.assertEqual(counts["per-TU preprocessor scaffolds"], 0)
        self.assertEqual(counts["sanctioned feature switches"], 2)

    def test_growth_is_not_a_ratchet_violation(self):
        self.write(f"#if defined({self.FLAG})\nint a;\n#endif\n")
        self.assertEqual(self.gate(), [])
        self.write(f"#if defined({self.FLAG})\nint a;\n#endif\n" * 3)
        self.assertEqual(self.gate(), [])
        self.assertEqual(board.load_baseline()["sanctioned feature switches"], 3)
        self.assertEqual(board.load_baseline()["per-TU preprocessor scaffolds"], 0)

    def test_source_definition_and_other_names_still_ratchet(self):
        self.write("int a;\n")
        self.assertEqual(self.gate(), [])
        self.write(f"#define {self.FLAG}\n"
                   f"#if defined({self.FLAG}) || defined({self.SCAFFOLD})\n#endif\n")
        violations = self.gate()
        self.assertTrue(any("per-TU preprocessor scaffolds rose 0 -> 2" in line
                            for line in violations), violations)
        self.assertNotIn("sanctioned feature switches",
                         " ".join(line for line in violations if "rose" in line))

    def test_feature_only_local_class_is_reported_not_a_view(self):
        self.write(f"#if defined({self.FLAG})\nstruct TFailure {{}};\n#endif\n"
                   f"#if defined({self.FLAG})\nint a;\n#else\nstruct TView {{}};\n#endif\n")
        rows, offenders = board.count(per_file=True, dc_origins=[])
        counts = dict(rows)
        self.assertEqual(counts[".cpp-local views"], 1)
        self.assertEqual(counts["sanctioned feature local classes"], 1)
        self.assertIn((".cpp-local views", "src/rmg.cpp:7: struct TView {};"), offenders)


PROJECT = """
[inputs.retail]
path = "build/orig/HEROES3.EXE"

[inputs.h3maped]
image = true
path = "build/orig/h3maped.exe"
sources = "editor"

[inputs.h3ccmped]
image = true
path = "build/orig/h3ccmped.exe"
sources = "campaign_editor"
"""


class ImageBoards(unittest.TestCase):
    """Each image answers to the board for its own trees: the game for every
    file outside the editors' trees, an editor for its src/ and include/
    subdirectories, each against its own floors."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "config").mkdir()
        (self.root / "config/project.toml").write_text(PROJECT)
        self.baseline = self.root / "config/baseline.tsv"
        for name, value in (("REPO", self.root), ("BASELINE", self.baseline)):
            replacement = patch.object(board, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.write("include/hero.h", "enum eHero { KNIGHT };\n")
        self.write("src/hero.cpp", "int h = static_cast<eHero>(t);\n")
        self.write("src/editor/MapDoc.cpp", "int x = (int)y;\n")
        self.write("include/editor/MapDoc.h",
                   "struct TMapDoc { bool owns; };\nint e = static_cast<eHero>(t);\n")
        self.write("src/campaign_editor/CampaignDoc.cpp", "int a = (int)b; int c = (int)d;\n")

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def counts(self, image):
        return dict(board.count(dc_origins=[], image=image))

    def gate(self, image):
        with contextlib.redirect_stdout(io.StringIO()):
            return board.check_and_roll(write=True, dc_origins=[], image=image)

    def test_each_board_counts_only_its_own_trees(self):
        game = self.counts("game")
        self.assertEqual(game["C-style casts"], 0)
        self.assertEqual(game["casts to enum types"], 1)
        editor = self.counts("h3maped")
        self.assertEqual(editor["C-style casts"], 1)
        # The game's enum registry is visible to the editor's own sources.
        self.assertEqual(editor["casts to enum types"], 1)
        self.assertEqual(self.counts("h3ccmped")["C-style casts"], 2)

    def test_offenders_name_only_the_images_own_files(self):
        _rows, offenders = board.count(per_file=True, dc_origins=[], image="h3maped")
        files = {where.split(":", 1)[0] for _label, where in offenders}
        self.assertEqual(files, {"src/editor/MapDoc.cpp", "include/editor/MapDoc.h"})

    def test_each_image_keeps_its_own_floors(self):
        self.assertEqual(board.baseline_path("game"), self.baseline)
        self.assertEqual(board.baseline_path("h3maped"),
                         self.root / "config/baseline.h3maped.tsv")
        for image in ("game", "h3maped", "h3ccmped"):
            self.assertEqual(self.gate(image), [])
        self.assertEqual(board.load_baseline("game")["C-style casts"], 0)
        self.assertEqual(board.load_baseline("h3maped")["C-style casts"], 1)
        self.assertEqual(board.load_baseline("h3ccmped")["C-style casts"], 2)

    def test_an_editor_header_volatile_fails_only_the_editors_board(self):
        for image in ("game", "h3maped"):
            self.assertEqual(self.gate(image), [])
        self.write("include/editor/MapDoc.h",
                   "struct TMapDoc { volatile bool owns; };\n")
        floors = board.baseline_path("h3maped").read_text()
        violations = self.gate("h3maped")
        self.assertTrue(any(line.startswith("h3maped cleanliness ratchet violated: "
                                            "volatile qualifiers rose 0 -> 1")
                            for line in violations), violations)
        self.assertIn("  include/editor/MapDoc.h:1: volatile bool owns; };", violations)
        self.assertEqual(board.baseline_path("h3maped").read_text(), floors)
        self.assertEqual(self.gate("game"), [])

    def test_selection_follows_the_image_environment(self):
        import os
        from homm3.core import images
        with patch.dict(os.environ, {images.IMAGE_ENV: "h3ccmped"}):
            self.assertEqual(board.baseline_path(), self.root / "config/baseline.h3ccmped.tsv")
            self.assertEqual(dict(board.count(dc_origins=[]))["C-style casts"], 2)


class VolatileAllowlist(unittest.TestCase):
    """volatile stays banned; a reviewed row admits one retail-proven site."""

    HEADER = "# reviewed\nimage\tfile\tdeclaration\tevidence\n"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "config/cleanliness").mkdir(parents=True)
        (self.root / "config/project.toml").write_text(PROJECT)
        self.baseline = self.root / "config/cleanliness/baseline.tsv"
        for name, value in (("REPO", self.root), ("BASELINE", self.baseline)):
            replacement = patch.object(board, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.header = self.root / "include/editor/MapDoc.h"
        self.header.parent.mkdir(parents=True)
        self.header.write_text("class TMapDoc {\n    volatile bool _m_bOwns;  // thread\n"
                               "    volatile int _m_other;\n};\n")
        for image in ("game", "h3maped"):
            board.save_baseline([(label, 0) for label, *_ in board.METRICS], image)

    def allow(self, *rows):
        (self.root / board.VOLATILE_ALLOWLIST).write_text(
            self.HEADER + "".join("\t".join(row) + "\n" for row in rows))

    def gate(self, image="h3maped"):
        with contextlib.redirect_stdout(io.StringIO()):
            return board.check_and_roll(write=False, dc_origins=[], image=image)

    def test_without_a_row_every_volatile_fails(self):
        violations = self.gate()
        self.assertTrue(any("volatile qualifiers rose 0 -> 2" in line for line in violations))

    def test_a_row_admits_exactly_its_declaration(self):
        self.allow(("h3maped", "include/editor/MapDoc.h", "volatile bool _m_bOwns;",
                    "autosave thread writes it; retail keeps the store order"))
        counts = dict(board.count(dc_origins=[], image="h3maped"))
        self.assertEqual(counts["volatile qualifiers"], 1)
        self.assertEqual(counts[board.ADMITTED_VOLATILE], 1)
        violations = self.gate()
        self.assertTrue(any("volatile qualifiers rose 0 -> 1" in line for line in violations))
        self.assertIn("  include/editor/MapDoc.h:3: volatile int _m_other;", violations)
        self.assertNotIn(board.ADMITTED_VOLATILE, board.RATCHET)

    def test_admitted_sites_pass_and_are_reported(self):
        self.allow(("h3maped", "include/editor/MapDoc.h", "volatile bool _m_bOwns;", "thread"),
                   ("h3maped", "include/editor/MapDoc.h", "volatile  int _m_other;", "modal loop"))
        self.assertEqual(self.gate(), [])
        self.assertEqual(dict(board.count(dc_origins=[], image="h3maped"))[
            board.ADMITTED_VOLATILE], 2)

    def test_a_row_belongs_to_one_image(self):
        self.allow(("h3ccmped", "include/editor/MapDoc.h", "volatile bool _m_bOwns;", "thread"))
        self.assertTrue(any("rose 0 -> 2" in line for line in self.gate()))
        self.assertEqual(self.gate("game"), [])

    def test_an_unused_row_fails(self):
        self.allow(("h3maped", "include/editor/MapDoc.h", "volatile bool _m_bOwns;", "thread"),
                   ("h3maped", "include/editor/MapDoc.h", "volatile int _m_other;", "loop"),
                   ("h3maped", "include/editor/MapDoc.h", "volatile long _m_gone;", "old"))
        violations = self.gate()
        self.assertEqual(len(violations), 1)
        self.assertIn("`volatile long _m_gone;` admits no h3maped volatile site", violations[0])

    def test_a_row_without_evidence_admits_nothing(self):
        self.allow(("h3maped", "include/editor/MapDoc.h", "volatile bool _m_bOwns;", " "),
                   ("h3maped", "include/editor/MapDoc.h", "volatile int _m_other;"))
        violations = self.gate()
        self.assertTrue(any("rose 0 -> 2" in line for line in violations))
        self.assertEqual(sum("needs image, file, declaration and evidence" in line
                             for line in violations), 2)

    def test_the_repair_text_names_the_admission_path(self):
        fix = board._FIX["volatile qualifiers"]
        for required in ("banned as a codegen lever", "volatile_allowlist.tsv",
                         "compiling both", "a score gain is not evidence"):
            self.assertIn(required, fix)


if __name__ == "__main__":
    unittest.main()


class EditorRttiLocalClasses(unittest.TestCase):
    def test_anonymous_scope_names_its_source_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            table = root / "config/retail/h3maped/vtables.tsv"
            table.parent.mkdir(parents=True)
            table.write_text(
                "rva\tslots\tclass\n"
                "0x13a598\t7\tTTerrainPlacementMapAdapter@?%C:\\Dev\\Heroes 3 Exp 2\\Editor\\"
                "MapSpecsGeneralPage.cpp2959323531\n"
                "0x131400\t2\t_TSkillControls@TPrimarySkillBonusesDlg@?%C:\\Dev\\Heroes 3 Exp 2\\Editor\\"
                "BlackBoxPropsContentsPage.cpp544924908\n"
                "0x13b000\t4\tTSplashWnd@?%C:\\Dev\\Heroes 3 Exp 2\\Editor\\Map Editor.cpp1\n"
                "0x13c000\t3\tTMapView\n")
            with patch.object(board, "REPO", root):
                origins = board._image_rtti_private_origins("h3maped")
        self.assertEqual(origins, {
            "TTerrainPlacementMapAdapter": {"mapspecsgeneralpage.cpp"},
            "TSplashWnd": {"mapeditor.cpp"},
        })

    def test_the_game_has_no_editor_rtti_origins(self):
        self.assertEqual(board._image_rtti_private_origins(board.images.DEFAULT_IMAGE), {})
