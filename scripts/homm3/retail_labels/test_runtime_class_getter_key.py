"""MFC's macro-defined GetRuntimeClass joins its VA_COMPGEN claim by class."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from homm3.compare.canonicalize import DIRECT_SYMBOL_COMPGEN_KINDS
from homm3.retail_labels import source


GETTER = "?GetRuntimeClass@TMapDoc@@UBEPAUCRuntimeClass@@XZ"


class RuntimeClassGetterKeyTest(unittest.TestCase):
    def test_claim_joins_the_class_getter(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "MapDoc.cpp"
            path.write_text(
                "VA(0x00401000, 0x35)\n"
                "IMPLEMENT_DYNCREATE(TMapDoc, CDocument)\n"
                "VA_COMPGEN(0x00401035, 0x6, RUNTIME_CLASS_GETTER, TMapDoc)\n")
            rows = source.scan_file(path, {0x1000, 0x1035})
        other = "?GetRuntimeClass@TMapView@@UBEPAUCRuntimeClass@@XZ"
        groups = {source._demangle_key(symbol): [(symbol, 6)] for symbol in (GETTER, other)}
        with mock.patch.object(source, "_base_authority_scan", return_value=(groups, {})):
            source.join_unit("MapDoc", rows)
        getter = [row for row in rows if row["rva"] == 0x1035]
        self.assertEqual([row.get("joined") for row in getter], [GETTER])

    def test_a_va_on_the_macro_labels_its_create_object(self):
        # a TU clang cannot read keeps the lexical label, which must still
        # key like the CreateObject the macro defines first
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "MapDoc.cpp"
            path.write_text("VA(0x00401000, 0x35)\n"
                            "IMPLEMENT_DYNCREATE(TMapDoc, CDocument)\n")
            rows = source.scan_file(path, {0x1000})
        create = "?CreateObject@TMapDoc@@SGPAVCObject@@XZ"
        groups = {source._demangle_key(create): [(create, 0x35)]}
        with mock.patch.object(source, "_base_authority_scan", return_value=(groups, {})):
            source.join_unit("MapDoc", rows)
        self.assertEqual([row.get("joined") for row in rows], [create])

    def test_kind_names_an_emitted_symbol(self):
        self.assertEqual(source._demangle_key(GETTER), "tmapdoc_getruntimeclass")
        self.assertIn("RUNTIME_CLASS_GETTER", source.COMPGEN_KINDS)
        self.assertIn("RUNTIME_CLASS_GETTER", DIRECT_SYMBOL_COMPGEN_KINDS)
        self.assertNotIn("RUNTIME_CLASS_GETTER", source.ANONYMOUS_COMPGEN_KINDS)


if __name__ == "__main__":
    unittest.main()
