"""homm3 patterns: signature, cleanup, loop, store-order and naming helpers on
hand-assembled x86 bodies."""
import struct
import unittest

from homm3.analysis import patterns as P


class SignatureTests(unittest.TestCase):
    def test_cdecl_body_pops_nothing_and_reads_no_register(self):
        # mov eax,[esp+4]; ret
        self.assertEqual(P.signature(bytes.fromhex("8b442404c3")), (frozenset({0}), frozenset()))

    def test_fastcall_body_reads_ecx_and_edx_and_pops_stack_arguments(self):
        # mov eax,ecx; add eax,edx; add eax,[esp+4]; ret 4
        pops, live = P.signature(bytes.fromhex("8bc103c2034424" "04c20400"))
        self.assertEqual(pops, frozenset({4}))
        self.assertEqual(live, frozenset({"ecx", "edx"}))

    def test_written_register_and_frame_push_are_not_arguments(self):
        # push ecx; xor ecx,ecx; mov [esp],ecx; pop ecx; ret
        self.assertEqual(P.signature(bytes.fromhex("5133c9890c2459c3"))[1], frozenset())

    def test_a_call_clobbers_the_argument_registers(self):
        # call +0; mov eax,ecx; ret
        self.assertEqual(P.signature(bytes.fromhex("e8000000008bc1c3"))[1], frozenset())


class CleanupTests(unittest.TestCase):
    def test_caller_cleanup_forms(self):
        body = bytes.fromhex("e800000000" "83c40c" "e800000000" "59" "e800000000" "5959"
                             "e800000000" "c3")
        relocs = {1: ("_f", P.REL32), 9: ("_f", P.REL32), 15: ("_g", P.REL32),
                  22: ("_f", P.REL32)}
        self.assertEqual(P.call_sites(body, relocs), {"_f": [12, 4, 0], "_g": [8]})


class LoopTests(unittest.TestCase):
    def test_rotated_and_unrotated_back_edges(self):
        # top: dec ecx; jne top; ret          (rotated)
        rotated = bytes.fromhex("4975fdc3")
        # top: test ecx,ecx; je out; dec ecx; jmp top; out: ret
        plain = bytes.fromhex("85c9740349ebf9c3")
        self.assertEqual(P.loop_shape(rotated), {"jcc_back": 1, "ret": 1})
        self.assertEqual(P.loop_shape(plain), {"jcc_fwd": 1, "jmp_back": 1, "ret": 1})


class StoreOrderTests(unittest.TestCase):
    def test_adjacent_swapped_stores_through_one_base(self):
        ours = bytes.fromhex("83c8ff" "8945b8" "8945bc" "c3")
        retail = bytes.fromhex("83c8ff" "8945bc" "8945b8" "c3")
        found = P.store_permutations(ours, retail)
        self.assertEqual(len(found["blocks"]), 1)
        self.assertEqual(found["permuted"], 2)

    def test_different_values_are_not_a_permutation(self):
        ours = bytes.fromhex("8945b8" "895dbc" "c3")
        retail = bytes.fromhex("8945b8" "8945bc" "c3")
        self.assertEqual(P.store_permutations(ours, retail)["blocks"], [])


class NameTests(unittest.TestCase):
    def test_c_conventions_from_decoration(self):
        self.assertEqual(P.convention("@adler32@12", {}), "__fastcall")
        self.assertEqual(P.convention("_MessageBoxA@16", {}), "__stdcall")
        self.assertEqual(P.convention("_strlen", {}), "__cdecl")

    def test_ob1_profiles(self):
        self.assertTrue(P.ob1(["/O2", "/MT"]))
        self.assertTrue(P.ob1(["/O1"]))
        self.assertFalse(P.ob1(["/O1", "/Ob2"]))
        self.assertFalse(P.ob1(["/Od"]))

    def test_unnamed_retail_labels(self):
        self.assertTrue(P.UNNAMED.match("fn_112257"))
        self.assertTrue(P.UNNAMED.match("$gap_176030"))
        self.assertFalse(P.UNNAMED.match("?OnOK@CPropertyPage@@UAEXXZ"))


def _object(names):
    """A minimal i386 COFF with one symbol per long name."""
    strtab = bytearray(4)
    symbols = bytearray()
    for name in names:
        symbols += struct.pack("<II", 0, len(strtab)) + struct.pack("<IhHBB", 0, 0, 0, 2, 0)
        strtab += name.encode() + b"\0"
    struct.pack_into("<I", strtab, 0, len(strtab))
    header = struct.pack("<HHIIIHH", 0x14C, 0, 0, 20, len(names), 0, 0)
    return header + bytes(symbols) + bytes(strtab)


class RenameTests(unittest.TestCase):
    def test_rename_rewrites_only_the_mapped_symbol(self):
        from homm3.delink.coffx import Obj
        data = P.rename_symbols(_object(["?f@@YIXH@Z", "?g@@YAXXZ"]), {"?f@@YIXH@Z": "?f@@YAXH@Z"})
        obj = Obj(data)
        self.assertEqual([obj.sym_name(i) for i, _v, _s in obj.iter_symbols()],
                         ["?f@@YAXH@Z", "?g@@YAXXZ"])


if __name__ == "__main__":
    unittest.main()
