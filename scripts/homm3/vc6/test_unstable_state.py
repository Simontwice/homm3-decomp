"""Tooling contracts of the unrelated-edit state tools (no compiler runs)."""
from __future__ import annotations

import random
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from homm3.vc6 import _il, unstable_state as us
from homm3.vc6.test_context_variants import _coff


class StateTest(unittest.TestCase):
    def test_labels_and_environment(self):
        self.assertEqual(us.State().label(), "captured")
        self.assertEqual(us.State(1, 5).label(), "phase=1 decl-offset=5")
        env = us.state_env(us.State(0, 3))
        self.assertEqual((env["HOMM3_VC6_PHASE"], env["HOMM3_VC6_HANDLE_SHIFT"]), ("0", "1:3"))
        self.assertNotIn("HOMM3_VC6_HANDLE_SHIFT", us.state_env(us.State(1, 0)))

    def test_shift_raises_the_gl_high_water_only(self):
        gl = _il.GL_MAGIC + struct.pack("<I", 0x2d24) + b"rest"
        out = us.shifted_streams({"gl": gl, "ex": b"x"}, 7)
        self.assertEqual(struct.unpack_from("<I", out["gl"], len(_il.GL_MAGIC))[0], 0x2d2b)
        self.assertEqual(out["ex"], b"x")
        self.assertIs(us.shifted_streams({"gl": gl}, 0)["gl"], gl)


class ReadTest(unittest.TestCase):
    def test_each_function_receives_what_the_previous_one_left(self):
        log = ("driver left=1 base=28b1 name=?a@@YAXXZ\n"
               "phase-read root=00000000 value=0\n"
               "driver left=0 base=2900 name=?b@@YAXXZ\n"
               "driver left=1 base=2941 name=?c@@YAXXZ\n")
        rows = us.received_states(us.parse_drivers(log))
        self.assertEqual([(r["name"], r["phase"]) for r in rows],
                         [("?a@@YAXXZ", 0), ("?b@@YAXXZ", 1), ("?c@@YAXXZ", 0)])
        self.assertEqual(rows[0]["handle_residue"], 0x28b1 % 64)


class CalleeOrderTest(unittest.TestCase):
    def test_prefixes_follow_compile_order_and_rounds_clamp(self):
        order = ["?c", "?a", "?f", "?b"]
        prefixes = us.callee_prefixes(order, {"?f": ["?b", "?a", "?inline_only", "?f"]})
        self.assertEqual(prefixes, {"?f": ["?a", "?b"]})  # no emitted body: never compiled
        self.assertEqual(us.compiled_round(prefixes, 0), {"?f": []})
        self.assertEqual(us.compiled_round(prefixes, 1), {"?f": ["?a"]})
        self.assertEqual(us.compiled_round(prefixes, 9), {"?f": ["?a", "?b"]})
        self.assertEqual(us.State(None, 0, 2).label(), "callees-compiled-first=2")


class FuzzEditTest(unittest.TestCase):
    TEXT = "#include <x.h>\nint g;\nVA(0x00401000, 0x10)\nvoid f() {}\nVA(0x00401010, 0x10)\nvoid h() {}\n"

    def test_edits_only_insert_at_top_or_before_annotations(self):
        rng = random.Random(3)
        while True:
            edited, desc, shadows = us.unrelated_edit(self.TEXT, rng, 0)
            if not desc[0].startswith("swap"):
                break
        self.assertTrue(desc)
        self.assertEqual(shadows, {})
        kept = "".join(line for line in edited.splitlines(True) if "h3fz" not in line
                       and not line.startswith(("struct h3fz", "int h3fz")))
        self.assertEqual(kept, self.TEXT)  # nothing original moved or changed
        self.assertEqual(us.unrelated_edit(self.TEXT, random.Random(3), 0),
                         us.unrelated_edit(self.TEXT, random.Random(3), 0))

    def test_swap_exchanges_adjacent_definition_blocks(self):
        rng = random.Random(0)
        for _ in range(50):
            edited, desc, _ = us.unrelated_edit(self.TEXT, rng, 0)
            if desc[0].startswith("swap"):
                break
        self.assertTrue(edited.index("void h()") < edited.index("void f()"))
        self.assertEqual(sorted(edited.splitlines()), sorted(self.TEXT.splitlines()))

    def test_header_edit_shadows_a_copy(self):
        rng = random.Random(0)
        for _ in range(50):
            edited, desc, shadows = us.unrelated_edit(self.TEXT, rng, 0, {"a.h": "#ifndef A\n#define A\n#endif\n"})
            if shadows:
                break
        self.assertEqual(edited, self.TEXT)
        self.assertTrue(shadows["a.h"].startswith("#ifndef A\n#define A\n"))
        self.assertTrue(shadows["a.h"].endswith("#endif\n"))


class ObjectFunctionsTest(unittest.TestCase):
    def test_every_function_masked_and_trimmed(self):
        code = bytes([0x55, 0xa1, 1, 2, 3, 4, 0xc3, 0xcc, 0x33, 0xc0, 0xc3])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.obj"
            path.write_bytes(_coff(code, [2], [("?f@@Y", 0), ("?g@@Y", 8)]))
            self.assertEqual(us.object_functions(path),
                             {"?f@@Y": bytes([0x55, 0xa1, 0, 0, 0, 0, 0xc3]),
                              "?g@@Y": bytes([0x33, 0xc0, 0xc3])})

    def test_scored_compile_m_scores_only_new_assemblies_and_records_its_source(self):
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "u.cpp"
            source.write_text("int f();\n")

            class FakeUnit:
                name = "u"

                def __init__(self):
                    self.source = source

                def plain(self):
                    return Path(raw) / "plain.obj"

                def replay(self, state, slot, log=False, compiled=None):
                    directory = Path(raw) / slot
                    directory.mkdir(exist_ok=True)
                    obj = directory / "o.obj"
                    obj.write_text(f"{state.phase}:{state.offset % 2}")
                    return obj, ""

            def functions(obj):
                text = Path(obj).read_text() if Path(obj).exists() else "None:0"
                phase, odd = text.split(":")
                return {"f": b"\x01" if phase in ("None", "0") else b"\x02",
                        "g": b"\x03" + odd.encode()}

            scored = []

            def score(unit, obj):
                scored.append(Path(obj).read_text() if Path(obj).exists() else "plain")
                return {"f": 90.0 if b"\x01" in functions(obj)["f"] else 100.0, "g": 50.0}

            with patch.object(us, "object_functions", side_effect=functions), \
                 patch.object(us, "score_object", side_effect=score), \
                 patch.object(us, "inline_callees", return_value={}), \
                 patch.object(us, "read_state", return_value=[{"name": "f"}, {"name": "g"}]):
                result = us.compile_m(FakeUnit(), offsets=range(4), jobs=1, score=True)
            self.assertEqual(result["source_sha256"], us.source_digest(source))
        self.assertTrue(result["scored"])
        # plain, then one object per new (function, assembly): phase 0 odd
        # offset (new g), phase 1 even offset (new f) -- never a repeat
        self.assertEqual(len(scored), 3)
        f = {v["sha"]: v["score"] for v in result["functions"]["f"]["variants"]}
        self.assertEqual(sorted(f.values()), [90.0, 100.0])


if __name__ == "__main__":
    unittest.main()
