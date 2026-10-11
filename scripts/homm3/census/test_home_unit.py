"""placements.home_unit: which definer's copy of a template sits at an address."""
import unittest

from homm3.census.placements import home_unit


class HomeUnitTests(unittest.TestCase):
    def test_the_definer_whose_body_equals_retail_owns_the_address(self):
        # resourcemanager (/O2) comes first in the manifest, MapDoc (/O1)
        # compiled the bytes the linker kept
        bodies = {('resourcemanager', 'f'): (b'\x33\xc0\xc3', {}),
                  ('MapDoc', 'f'): (b'\x8b\x01\xc3', {})}
        self.assertEqual(home_unit('f', ['resourcemanager', 'MapDoc'], bodies, 3,
                                   lambda n: b'\x8b\x01\xc3'[:n]), 'MapDoc')

    def test_relocation_fields_are_masked(self):
        bodies = {('a', 'f'): (b'\xe8\x00\x00\x00\x00\xc3', {1: ('g', 'REL32')})}
        self.assertEqual(home_unit('f', ['a'], bodies, 6,
                                   lambda n: b'\xe8\x12\x34\x56\x78\xc3'[:n]), 'a')

    def test_the_first_definer_keeps_an_address_no_body_equals(self):
        bodies = {('a', 'f'): (b'\x33\xc0\xc3', {}), ('b', 'f'): (b'\x31\xc0\xc3', {})}
        self.assertEqual(home_unit('f', ['a', 'b'], bodies, 3, lambda n: b'\x90\x90\xc3'[:n]),
                         'a')

    def test_equal_definers_keep_manifest_order(self):
        bodies = {('a', 'f'): (b'\xc3', {}), ('b', 'f'): (b'\xc3', {})}
        self.assertEqual(home_unit('f', ['a', 'b'], bodies, 1, lambda n: b'\xc3'), 'a')


if __name__ == '__main__':
    unittest.main()
