"""Hermetic tests for `homm3 dreamcast compare-structure`."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from homm3.analysis import dc_compare_structure as compare, source_facts


def _view(side, *, statements=(), calls=None, locals_=(), scopes=(), callees=None, temporaries=None):
    view = compare._empty_view(side)
    view["signature"] = "void run(int)"
    view["parameters"] = [("count", "int")]
    view["statement_lines"] = set(statements)
    for line, tokens in (calls or {}).items():
        view["calls_by_line"][line].extend(tokens)
    view["locals"] = [dict(row) for row in locals_]
    view["scopes"] = [{"span": span, "depth": depth, "key": span} for span, depth in scopes]
    for token, row in (callees or {}).items():
        view["callees"][token].update(row)
    view["temporaries"] = Counter(temporaries or {})
    view["control"] = {"blocks": 3}
    view["reference"] = side
    return view


class NormalizationTest(unittest.TestCase):
    def test_types_drop_keywords_and_spacing(self):
        self.assertEqual(compare.norm_type("class hero *"), "hero*")
        self.assertEqual(compare.norm_type("const struct type_point &"), "const type_point&")
        self.assertEqual(compare.norm_type("char * const"), "char* const")
        self.assertEqual(compare.norm_type("std::vector<int, std::allocator<int> >"), "std::vector<int>")
        self.assertEqual(compare.norm_type("std::basic_string<char,std::char_traits<char>,"
                                           "std::allocator<char> > &"), "std::basic_string<char>&")
        self.assertEqual(compare.norm_type("std::string"), "std::basic_string<char>")
        self.assertTrue(compare.same_type("unsigned char", "bool"))
        self.assertTrue(compare.same_type("void update(unsigned char, long)", "void update(bool, long)"))
        self.assertFalse(compare.same_type("bool", "unsigned char"))
        self.assertEqual(compare.norm_type("char [200]"), "char[200]")
        self.assertEqual(compare.norm_type("__int64"), "long long")

    def test_callee_tokens(self):
        self.assertEqual(compare.callee_token("recruitUnit::UpdateCost"), "updatecost")
        self.assertEqual(compare.callee_token("?updateCost@recruitUnit@@QAEXXZ"), "updatecost")
        self.assertEqual(compare.callee_token("message::message"), "ctor:message")
        self.assertEqual(compare.callee_token("??1message@@QAE@XZ"), "dtor:message")
        self.assertIsNone(compare.callee_token("_sprintf"))
        self.assertIsNone(compare.callee_token("`vector constructor iterator'"))
        self.assertIsNone(compare.callee_token(None))

    def test_statement_runs(self):
        self.assertEqual(compare.statement_runs([0, 1, 3, 4, 8]), (2, 4))
        self.assertEqual(compare.statement_runs([]), (0, 0))

    def test_locals_pair_on_one_key(self):
        dc = [{"name": "pCurrentHero", "type": "hero*", "scope": "function"},
              {"name": "iCount", "type": "int", "scope": "function"}]
        ours = [{"name": "currentHero", "type": "hero*", "scope": "function"},
                {"name": "spare", "type": "int", "scope": "function"}]
        compare.pair_locals(dc, ours)
        self.assertEqual([row["key"] for row in dc], ["currenthero", "count"])
        self.assertEqual([(row["key"], row["paired"]) for row in ours],
                         [("currenthero", True), ("spare", False)])


class RenderTest(unittest.TestCase):
    def test_both_sides_share_one_layout(self):
        dc = _view("dc", statements=(0, 1, 3, 5), calls={1: ["ctor:message"], 3: ["inline:gethero"]},
                   scopes=(((2, 4), 0), ((2, 4), 1)),
                   callees={"ctor:message": {"calls": 1}, "gethero": {"inline": 1}})
        ours = _view("ours", statements=(0, 1, 2, 4), calls={1: ["inline:ctor:message"], 2: ["gethero"]},
                     scopes=(((2, 3), 0),),
                     callees={"ctor:message": {"inline": 1}, "gethero": {"calls": 1}})
        for side in (dc, ours):
            side["locals"] = [{"name": "x", "type": "int", "scope": "function"}]
        compare.pair_locals(dc["locals"], ours["locals"])
        header = ["// FUNCTION: f"]
        left = compare.render(dc, header, (0, 5)).splitlines()
        right = compare.render(ours, header, (0, 5)).splitlines()
        heads = lambda rows: [row.split(" (")[0] for row in rows if row.startswith("== ")]
        self.assertEqual(heads(left), heads(right))
        start = lambda rows: rows.index(next(r for r in rows if r.startswith("== LINES")))
        self.assertEqual(left[start(left) + 1:start(left) + 7],
                         ["+000 stmt", "+001 stmt", "+002 -", "+003 stmt", "+004 -", "+005 stmt"])
        self.assertEqual(right[start(right) + 1:start(right) + 7],
                         ["+000 stmt", "+001 stmt", "+002 stmt", "+003 -", "+004 stmt", "+005 -"])
        # The statement sequence ignores line numbers and the inline marker.
        sequence = lambda rows: rows[rows.index(next(r for r in rows if r.startswith("== STATEMENT"))) + 1:][:4]
        self.assertEqual(sequence(left), ["stmt", "stmt ctor:message", "stmt gethero", "stmt"])
        self.assertEqual(sequence(right), ["stmt", "stmt ctor:message", "stmt gethero", "stmt"])
        self.assertIn("SCOPES (2; distinct extents 1)", "\n".join(left))
        self.assertIn("x: int @function", left)
        self.assertIn("x: int @function", right)

    def test_summary_counts_and_difference(self):
        dc = _view("dc", statements=(0, 1, 2), scopes=(((1, 2), 0), ((1, 2), 1)),
                   callees={"gethero": {"calls": 2}, "dtor:text": {"calls": 1}},
                   temporaries={"text": 1})
        ours = _view("ours", statements=(0, 1, 2, 3), scopes=(),
                     callees={"gethero": {"calls": 1, "inline": 1}, "draw": {"calls": 1}})
        dc["locals"] = [{"name": "iOld", "type": "int", "scope": "function"}]
        ours["locals"] = [{"name": "old", "type": "long", "scope": "function"},
                          {"name": "extra", "type": "int", "scope": "function"}]
        compare.pair_locals(dc["locals"], ours["locals"])
        summary = compare.summarize(dc, ours, (0, 3))
        self.assertEqual(summary["counts"]["statement lines"], (3, 4))
        self.assertEqual(summary["counts"]["distinct scope extents"], (1, 0))
        self.assertEqual(summary["locals_ours_only"], ["int extra"])
        self.assertEqual(summary["local_type_differences"], ["old: int / long"])
        self.assertEqual(summary["temporaries"], {"text": (1, 0)})
        self.assertEqual(summary["callees"], {"draw": (0, 1)})
        self.assertEqual(summary["line_mismatches"], 1)
        # 1 statement + 2 scopes + 1 unpaired local + 1 temporary + 1 callee
        self.assertEqual(summary["difference"], 6)
        self.assertFalse(summary["dreamcast_stub"])
        self.assertTrue(compare.stub((2, 75)))
        self.assertFalse(compare.stub((24, 92)))
        text = compare.render_summary({"name": "f", "va": 0x401000, "unit": "u", "score": None,
                                       "module": "m.obj", "dc_offset": 0x10, "source": "src/u.cpp"},
                                      summary)
        self.assertIn("structural difference: 6", text)

    def test_index_sorts_and_tallies(self):
        dc, ours = _view("dc", statements=(0,)), _view("ours", statements=(0, 1))
        compare.pair_locals(dc["locals"], ours["locals"])
        summary = compare.summarize(dc, ours, (0, 1))
        rows = [{"va": 0x401000, "name": "f", "unit": "u", "stem": "u/00401000_f",
                 "score": {"cur": 99.5, "max": 99.5}, "summary": summary}]
        tsv = compare.render_index_tsv(rows).splitlines()
        self.assertEqual(tsv[0].split("\t"), list(compare.INDEX_COLUMNS))
        self.assertEqual(tsv[1].split("\t")[:6], ["0x00401000", "f", "u", "99.50", "99.50", "1"])
        self.assertIn("0 functions declare a local", compare.render_index_md(rows))


class CompiledFactsTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("llvm-undname"), "llvm-undname is required")
    def test_library_templates_are_undecorated(self):
        names = ["?insert@?$vector@PAVwidget@@V?$allocator@PAVwidget@@@std@@@std@@QAEXPAPAVwidget@@IABQAV3@@Z",
                 "??0textWidget@@QAE@HHHHPBDPBDHHHH@Z", "_sprintf"]
        qualified = compare.undecorate(names)
        self.assertEqual(qualified[names[1]], "textWidget::textWidget")
        self.assertIsNone(compare.callee_token(qualified[names[0]]))
        self.assertEqual(compare.callee_token(qualified[names[1]]), "ctor:textwidget")
        self.assertNotIn("_sprintf", qualified)

    def test_direct_indirect_calls_and_blocks(self):
        text = "\n".join([
            "00000000 <?run@@YAXH@Z>:",
            "       0: 55                           \tpush\tebp",
            "       1: e8 00 00 00 00               \tcall\t0x6 <?run@@YAXH@Z+0x6>",
            "\t\t\t00000002:  IMAGE_REL_I386_REL32\t?getHero@game@@QAEPAVhero@@H@Z",
            "       6: e8 00 00 00 00               \tcall\t0xb <?run@@YAXH@Z+0xb>",
            "\t\t\t00000007:  IMAGE_REL_I386_REL32\t_sprintf",
            "       b: ff 52 24                     \tcall\tdword ptr [edx + 0x24]",
            "       e: 74 01                        \tje\t0x11 <?run@@YAXH@Z+0x11>",
            "      10: 5d                           \tpop\tebp",
            "      11: c3                           \tret",
        ])
        facts = compare.compiled_facts(text)
        self.assertEqual(facts["direct"], Counter({"gethero": 1}))
        self.assertEqual(facts["control"]["direct calls"], 2)
        self.assertEqual(facts["control"]["indirect calls"], 1)
        self.assertEqual(facts["control"]["conditional branches"], 1)


@unittest.skipUnless(shutil.which("clang"), "Clang is required for authored body layouts")
class BodyLayoutTest(unittest.TestCase):
    def test_statements_scopes_and_call_owners(self):
        source = """int get(); void use(int, int); struct Text { Text(int); ~Text(); };
struct Window { void run(int a); };
void Window::run(int a)
{
    int value = get();

    if (a)
        use(value,
            get());
    else {
        int inner = 1;
        use(inner, 0);
    }
    // note
    do {
        --a;
    } while (get());
    switch (a) {
    case 1:
        use(1, 2);
        break;
    }
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unit.cpp"
            path.write_text(source)
            run = subprocess.run([shutil.which("clang"), "--target=i686-pc-windows-msvc", "-fsyntax-only",
                                  "-Xclang", "-ast-dump=json", "-Xclang", "-ast-dump-filter=Window::run",
                                  str(path)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            docs = source_facts.json_documents(run.stdout)
            root = next(d for d in docs if any(c["kind"] == "CompoundStmt" for c in d.get("inner", [])))
            result = source_facts.extract_function(docs, root["mangledName"], path, source)
        layout = result["layout"]
        self.assertEqual((layout["begin_line"], layout["end_line"]), (4, 23))
        lines = [row["line"] for row in layout["statements"]]
        self.assertEqual(lines, [4, 5, 7, 8, 11, 12, 15, 16, 17, 18, 20, 21, 23])
        self.assertEqual([(s["begin_line"], s["end_line"], s["kind"], s["parent"]) for s in layout["scopes"]],
                         [(7, 13, "statement", None), (8, 9, "substatement", 0),
                          (10, 13, "substatement", 0), (10, 13, "block", 2),
                          (15, 17, "statement", None), (15, 17, "block", 4),
                          (18, 22, "statement", None),
                          (18, 22, "substatement", 6), (18, 22, "block", 7)])
        owners = {call["line"]: layout["calls"][call["offset"]] for call in result["calls"]}
        self.assertEqual(owners[9], 8)  # a continuation line's call belongs to its statement
        self.assertEqual(owners[17], 17)
        scopes = {local["name"]: layout["declarations"][local["offset"]] for local in result["locals"]}
        self.assertEqual(scopes, {"value": None, "inner": 3})


if __name__ == "__main__":
    unittest.main()
