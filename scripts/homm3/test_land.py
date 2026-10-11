"""`homm3 land`: gate verdicts, Mac relevance and generated-file rebase conflicts.

The lock and queue are tested in homm3.core.test_land_queue. Nothing here
compiles: build verdicts are read from recorded summary lines.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from homm3 import land

IMAGES = ["h3maped", "h3ccmped"]


def build_output(game="all gates passed", **images):
    """A full build's summary lines; images map KEY -> its gates line or None
    (did not compile) or "skip"."""
    lines = ["[build] MAX 4545/4785 functions exact (95.0%), 99.10% weighted MAX across 160 unit(s)"]
    failed = [] if game == "all gates passed" else [game]
    for key in IMAGES:
        state = images.get(key, "all gates passed")
        if state == "skip":
            lines.append(f"[build] image {key}: SKIPPED (--skip-image {key})")
            continue
        lines.append(f"[build] image {key}: building")
        if state is None:
            failed.append(f"image {key}")
            continue
        lines.append(f"[build] {key}: MAX 10/20 functions exact (50.0%), 60.00% weighted MAX "
                     "across 3 unit(s)")
        if state == "all gates passed":
            lines.append(f"[build] {key}: all gates passed")
        else:
            lines.append(f"[build] {key}: FAILED gates: {state}")
            failed.append(f"image {key}")
    lines.append("[build] FAILED gates (details above): " + "; ".join(failed) if failed
                 else "[build] all gates passed")
    return "\n".join(lines) + "\n"


STALE = ("placements (`homm3 --image h3maped placements --write` after a shared-source "
         "change, then `homm3 --image h3maped build` again)")


class BuildVerdictTests(unittest.TestCase):
    def test_green_build_of_every_image(self):
        output = build_output()
        self.assertEqual(land.build_problems(output, IMAGES), [])
        self.assertEqual(land.compiled_images(output, IMAGES), IMAGES)

    def test_a_skipped_or_missing_image_is_not_green(self):
        problems = land.build_problems(build_output(h3ccmped="skip"), IMAGES)
        self.assertIn("image h3ccmped was skipped", problems)
        output = build_output().replace("[build] image h3maped: building\n", "")
        self.assertTrue(any("h3maped was not built" in p for p in
                            land.build_problems(output, IMAGES)))

    def test_stale_placements_alone_continue_the_cycle(self):
        output = build_output(h3maped=STALE, h3ccmped=STALE.replace("h3maped", "h3ccmped"))
        self.assertTrue(land.build_problems(output, IMAGES))
        self.assertTrue(land.placements_only(output, IMAGES))
        self.assertEqual(land.compiled_images(output, IMAGES), IMAGES)

    def test_other_failures_stop_the_cycle(self):
        self.assertFalse(land.placements_only(
            build_output(h3maped=STALE + "; banked_rows (2 finding(s))"), IMAGES))
        self.assertFalse(land.placements_only(
            build_output(game="cleanliness board (1 violation(s))", h3maped=STALE), IMAGES))
        # An image that did not compile has no objects to place.
        output = build_output(h3maped=None)
        self.assertFalse(land.placements_only(output, IMAGES))
        self.assertEqual(land.compiled_images(output, IMAGES), ["h3ccmped"])
        self.assertFalse(land.placements_only("[build] boom\n", IMAGES))


class MacRelevanceTests(unittest.TestCase):
    def test_game_sources_and_shared_headers_need_the_mac_build(self):
        paths = ["src/hero.cpp", "include/hero.h", "vendor/zlib-1.1.3/zlib.h",
                 "config/units.toml", "config/mac/units.toml"]
        self.assertEqual(land.mac_paths(paths), paths)

    def test_editor_trees_and_other_files_do_not(self):
        self.assertEqual(land.mac_paths([
            "src/editor/MapView.cpp", "include/editor/GameMap.h",
            "src/campaign_editor/Campaign.cpp", "include/campaign_editor/Campaign.h",
            "config/units.h3maped.toml", "config/match_baseline.tsv", "README.md",
            "docs/tooling/land.md", "scripts/homm3/land.py"]), [])


README = """# Title

Prose.

<!-- match-score:start -->
{score}
<!-- match-score:end -->

{tail}
"""


class RebaseTests(unittest.TestCase):
    """land.rebase on a scratch repository (ROOT patched)."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.enterContext(patch.object(land, "ROOT", self.root))
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "t")
        self.git("config", "user.email", "t@t")
        self.write(score="MAX 1", tail="end", source="int a;\n")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "base")
        self.git("branch", "upstream")
        self.lines = []

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout

    def write(self, *, score=None, tail=None, source=None):
        if score is not None:
            (self.root / "README.md").write_text(README.format(score=score, tail=tail))
        if source is not None:
            (self.root / "a.cpp").write_text(source)

    def commit(self, message):
        self.git("commit", "-qam", message)

    class _Log:
        def __init__(self, sink):
            self.sink = sink

        def __call__(self, line):
            self.sink.append(line)

        def raw(self, text):
            self.sink.append(text)

    def rebase(self):
        land.rebase(self._Log(self.lines), "upstream")

    def test_score_block_conflicts_take_origin_and_keep_the_lane(self):
        self.git("checkout", "-q", "upstream")
        self.write(score="MAX 2", tail="end")
        self.commit("upstream scores")
        self.git("checkout", "-q", "main")
        self.write(score="MAX 3", tail="end", source="int a = 1;\n")
        self.commit("lane work with scores")
        self.rebase()
        self.assertFalse(land.rebase_in_progress())
        self.assertIn("MAX 2", (self.root / "README.md").read_text())
        self.assertEqual((self.root / "a.cpp").read_text(), "int a = 1;\n")
        self.assertEqual(self.git("log", "--format=%s").split("\n")[:3],
                         ["lane work with scores", "upstream scores", "base"])
        self.assertIn("resolved generated README.md", self.lines)

    def test_a_lane_commit_left_empty_is_dropped(self):
        self.git("checkout", "-q", "upstream")
        self.write(score="MAX 2", tail="end")
        self.commit("upstream scores")
        self.git("checkout", "-q", "main")
        self.write(score="MAX 3", tail="end")
        self.commit("lane refresh")
        self.rebase()
        self.assertFalse(land.rebase_in_progress())
        self.assertEqual(self.git("log", "--format=%s").split("\n")[:2],
                         ["upstream scores", "base"])

    def test_prose_and_source_conflicts_abort_the_rebase(self):
        for upstream, lane in (({"source": "int b;\n"}, {"source": "int c;\n"}),
                               ({"score": "MAX 1", "tail": "origin prose"},
                                {"score": "MAX 1", "tail": "lane prose"})):
            with self.subTest(upstream=upstream):
                self.git("checkout", "-q", "upstream")
                self.write(**upstream)
                self.commit("upstream")
                self.git("checkout", "-q", "main")
                self.write(**lane)
                self.commit("lane")
                head = self.git("rev-parse", "HEAD")
                with self.assertRaises(land.GateFailed) as caught:
                    self.rebase()
                self.assertEqual(caught.exception.gate, "rebase")
                self.assertFalse(land.rebase_in_progress())
                self.assertEqual(self.git("rev-parse", "HEAD"), head)
                self.assertEqual(self.git("status", "--porcelain"), "")
                self.git("reset", "-q", "--hard", "upstream")

    def test_score_block_detector(self):
        inside = README.format(score="<<<<<<< a\nMAX 1\n=======\nMAX 2\n>>>>>>> b", tail="t")
        outside = README.format(score="MAX 1", tail="<<<<<<< a\nx\n=======\ny\n>>>>>>> b")
        self.assertTrue(land.score_block_conflicts_only(inside))
        self.assertFalse(land.score_block_conflicts_only(outside))
        self.assertFalse(land.score_block_conflicts_only(README.format(score="", tail="")))


class RefreshPathTests(unittest.TestCase):
    def test_refresh_commit_takes_only_generated_files(self):
        for path in ("README.md", "build.ninja", "config/match_baseline.tsv",
                     "config/match_baseline.h3ccmped.tsv", "config/retail/h3maped/placements.tsv",
                     "config/mac/match_baseline.tsv", "config/cleanliness/baseline.tsv"):
            self.assertTrue(land._generated(path), path)
        for path in ("src/hero.cpp", "config/units.toml", "config/retail/h3maped/census.tsv",
                     "docs/README.md"):
            self.assertFalse(land._generated(path), path)


if __name__ == "__main__":
    unittest.main()
