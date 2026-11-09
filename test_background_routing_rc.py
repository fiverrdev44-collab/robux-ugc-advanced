"""Background UGC family and asset classification regression."""
import os
import unittest
os.environ.setdefault("ROBLOSECURITY_COOKIE", "test-cookie")
from product_understanding import classify_family, from_text, validate_title
from category_configs import detect_family_from_asset_type, get_category_config
from convergence_engine import resolve_family_ids, family_for_asset
from chain import _map_family

class BackgroundRoutingTests(unittest.TestCase):
    def test_real_user_example(self):
        msg = "i made a background starry sky fence and a distant village"
        self.assertEqual(classify_family(msg)[0], "backgrounds")
        self.assertEqual(from_text(msg)["family"], "backgrounds")
        self.assertEqual(_map_family("backgrounds"), "backgrounds")
        self.assertEqual(get_category_config("backgrounds")["asset_type_ids"], [92])
    def test_category_isolation(self):
        self.assertEqual(resolve_family_ids("backgrounds"), [92])
        self.assertEqual(family_for_asset(92), "backgrounds")
        self.assertEqual(detect_family_from_asset_type(92), "backgrounds")
        self.assertEqual(resolve_family_ids("back"), [46,67])
        self.assertEqual(classify_family("starry wings cape")[0], "back")
    def test_wings_never_recommended_as_background(self):
        concept = "i made a background starry sky fence and a distant village"
        ok, reason = validate_title(concept, "Cozy Starry Night Wings",
                                    family="backgrounds")
        self.assertFalse(ok)
        self.assertIn("wearable", reason)
        self.assertTrue(validate_title(concept, "Starry Village Background",
                                       family="backgrounds")[0])
    def test_substring_safe(self):
        self.assertNotEqual(classify_family("backpack with stars")[0], "backgrounds")

if __name__ == "__main__":
    unittest.main()
