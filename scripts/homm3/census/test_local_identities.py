"""placements: a unit's `static` that another unit's definition also names."""
import unittest

from homm3.census.placements import LOCAL, fold_label, local_identities, plain

RGB = "?RGBToHSV@@YAXIIIPAM00@Z"


class LocalIdentityTests(unittest.TestCase):
    def test_a_static_beside_another_units_definition_is_keyed_by_unit(self):
        # bitmap24.cpp's static RGBToHSV and palette.cpp's external one
        linkages = {"palette": {RGB: 2, "?ftol@@YAJN@Z": 3},
                    "bitmap24": {RGB: 3},
                    "bitmap16": {"?ftol@@YAJN@Z": 3}}
        self.assertEqual(local_identities(linkages),
                         {("bitmap24", RGB), ("palette", "?ftol@@YAJN@Z"),
                          ("bitmap16", "?ftol@@YAJN@Z")})

    def test_unique_statics_externals_and_initializer_ordinals_stay_plain(self):
        linkages = {"a": {"?only@@YAXXZ": 3, "?inline@@YAXXZ": 2, "_$E48": 3},
                    "b": {"?inline@@YAXXZ": 2, "_$E48": 3}}
        self.assertEqual(local_identities(linkages), set())

    def test_plain_spells_the_decorated_name(self):
        self.assertEqual(plain(f"{RGB}{LOCAL}bitmap24"), RGB)
        self.assertEqual(plain(RGB), RGB)


class SameSpellingFoldTests(unittest.TestCase):
    def test_the_external_name_labels_an_address_its_static_twin_shares(self):
        # h3maped 0x4e4ef0: palette's HSVToRGB (reached by its caller) and
        # bitmap24's static copy (its masked body) are one spelling, whatever
        # the bodies: the external name labels the address.
        static = f"{RGB}{LOCAL}bitmap24"
        names = {RGB: {0x10}, static: {0x10}}
        bodies = {RGB: (b"\x8b\x01\xc3", {}), static: (b"\x8b\x02\xc3", {})}
        definers = {RGB: ["palette"], static: ["bitmap24"]}
        self.assertEqual(fold_label({RGB, static}, names, bodies, definers, set()), RGB)

    def test_two_statics_of_one_spelling_take_the_first(self):
        first, second = f"{RGB}{LOCAL}a", f"{RGB}{LOCAL}b"
        names = {first: {0x10}, second: {0x10}}
        self.assertEqual(fold_label({first, second}, names, {},
                                    {first: ["a"], second: ["b"]}, set()), first)


if __name__ == "__main__":
    unittest.main()
