"""Thumbnails: the vision model must never receive a 24-megapixel original."""
import unittest
from lupa.thumbnail import thumbnail_url, MAX_EDGE_PX


class TestDriveThumbnailUrl(unittest.TestCase):
    def test_it_rewrites_the_size_suffix(self):
        url = thumbnail_url("https://lh3.googleusercontent.com/abc=s220")
        self.assertTrue(url.endswith(f"=s{MAX_EDGE_PX}"))

    def test_it_rewrites_a_width_suffix_too(self):
        url = thumbnail_url("https://lh3.googleusercontent.com/abc=w200-h150")
        self.assertTrue(url.endswith(f"=s{MAX_EDGE_PX}"))

    def test_a_link_without_a_suffix_gets_one(self):
        url = thumbnail_url("https://lh3.googleusercontent.com/abc")
        self.assertEqual(url, f"https://lh3.googleusercontent.com/abc=s{MAX_EDGE_PX}")

    def test_a_custom_size_is_honored(self):
        self.assertTrue(thumbnail_url("https://x/abc=s220", size=512).endswith("=s512"))

    def test_an_empty_link_returns_nothing(self):
        self.assertIsNone(thumbnail_url(""))
        self.assertIsNone(thumbnail_url(None))


class TestLocalDownscale(unittest.TestCase):
    def test_downscaling_without_pillow_returns_the_original(self):
        from lupa.thumbnail import downscale
        data = b"not-an-image"
        self.assertEqual(downscale(data, "image/png"), data)

    def test_a_small_image_is_left_alone(self):
        from lupa.thumbnail import needs_downscale
        self.assertFalse(needs_downscale(640, 480))

    def test_a_large_image_is_flagged(self):
        from lupa.thumbnail import needs_downscale
        self.assertTrue(needs_downscale(6000, 4000))

    def test_unknown_dimensions_are_treated_as_large(self):
        from lupa.thumbnail import needs_downscale
        self.assertTrue(needs_downscale(0, 0))


class TestTokenEstimate(unittest.TestCase):
    def test_the_cost_model_matches_the_thumbnail_we_actually_send(self):
        # the estimate assumes a 768px thumbnail; assert the constant agrees
        from lupa.caption import INPUT_TOKENS_PER_IMAGE
        self.assertEqual(MAX_EDGE_PX, 768)
        self.assertLessEqual(INPUT_TOKENS_PER_IMAGE, 800)


if __name__ == "__main__":
    unittest.main()
