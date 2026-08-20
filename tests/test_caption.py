"""Vision description: prompt, parsing, and the merge with what was already free."""
import unittest
from lupa.caption import (build_prompt, parse_response, merge, estimate_cost,
                          format_cost, InvalidResponse, MODEL_PRICES, resolve_pricing)
from lupa.gemini import DEFAULT_MODEL

PHOTO_META = {"file": "table.jpg", "kind": "photo", "medium": "na", "source": "camera",
              "has_text": False, "aspect": "3:2", "orientation": "landscape",
              "ocr_text": "", "labels": []}
AMBIGUOUS_META = {"file": "banner.jpg", "kind": None, "medium": None, "source": "camera",
                  "has_text": True, "aspect": "3:2", "orientation": "landscape",
                  "ocr_text": "SALE", "labels": []}

VISION = {"caption": "Wooden table with bread", "tags": ["Food", "WOOD", "food"],
          "scene": "indoor", "people": 0, "palette": ["#c8a06a"],
          "kind": "design", "medium": "digital"}


class TestPrompt(unittest.TestCase):
    def test_it_forbids_transcription_because_drive_already_did_ocr(self):
        self.assertIn("do not transcribe", build_prompt(PHOTO_META).lower())

    def test_it_does_not_pay_the_model_to_list_objects(self):
        # Google labels are already free; asking again pays twice
        prompt = build_prompt(PHOTO_META).lower()
        self.assertNotIn("list the objects", prompt)
        self.assertNotIn("identify the objects", prompt)

    def test_it_asks_for_json_and_states_the_closed_taxonomy(self):
        prompt = build_prompt(AMBIGUOUS_META)
        self.assertIn("JSON", prompt)
        for kind in ("photo", "design", "screenshot", "diagram", "logo", "other"):
            self.assertIn(kind, prompt)

    def test_a_known_kind_is_not_asked_about_again(self):
        self.assertNotIn("kind", build_prompt(PHOTO_META))

    def test_an_ambiguous_kind_is_asked_about(self):
        self.assertIn("kind", build_prompt(AMBIGUOUS_META))

    def test_the_output_language_defaults_to_english(self):
        self.assertIn("English", build_prompt(PHOTO_META))

    def test_the_output_language_can_be_switched(self):
        self.assertIn("Portuguese", build_prompt(PHOTO_META, language="pt"))


class TestParsing(unittest.TestCase):
    def test_clean_json(self):
        self.assertEqual(parse_response('{"caption": "hi"}')["caption"], "hi")

    def test_json_inside_a_markdown_fence(self):
        self.assertEqual(parse_response('```json\n{"caption": "hi"}\n```')["caption"], "hi")

    def test_json_surrounded_by_chatter(self):
        self.assertEqual(parse_response('Sure!\n{"caption": "hi"}\nHope that helps')["caption"], "hi")

    def test_a_response_without_json_raises_a_clear_error(self):
        with self.assertRaises(InvalidResponse):
            parse_response("sorry, I cannot see the image")


class TestMerge(unittest.TestCase):
    def test_metadata_beats_the_model(self):
        # metadata said photo/na; the model guessed design/digital and must be ignored
        r = merge(PHOTO_META, VISION)
        self.assertEqual(r["kind"], "photo")
        self.assertEqual(r["medium"], "na")

    def test_the_model_fills_what_metadata_did_not_know(self):
        r = merge(AMBIGUOUS_META, VISION)
        self.assertEqual(r["kind"], "design")
        self.assertEqual(r["medium"], "digital")

    def test_a_kind_invented_by_the_model_becomes_other(self):
        self.assertEqual(merge(AMBIGUOUS_META, dict(VISION, kind="fine-art-photo"))["kind"], "other")

    def test_a_medium_invented_by_the_model_becomes_na(self):
        self.assertEqual(merge(AMBIGUOUS_META, dict(VISION, medium="print-digital"))["medium"], "na")

    def test_tags_are_lowercased_and_deduplicated(self):
        self.assertEqual(sorted(merge(PHOTO_META, VISION)["tags"]), ["food", "wood"])

    def test_the_drive_ocr_lands_in_the_text_field(self):
        self.assertEqual(merge(AMBIGUOUS_META, VISION)["text"], "SALE")

    def test_a_missing_caption_does_not_crash(self):
        self.assertEqual(merge(PHOTO_META, {})["caption"], "")


class TestCost(unittest.TestCase):
    def test_batch_costs_less_than_synchronous(self):
        self.assertLess(estimate_cost(1000, batch=True), estimate_cost(1000, batch=False))

    def test_a_thousand_images_cost_cents(self):
        self.assertLess(estimate_cost(1000, batch=True), 0.50)

    def test_an_empty_collection_costs_nothing(self):
        self.assertEqual(estimate_cost(0, batch=True), 0.0)


class TestCostFormatting(unittest.TestCase):
    def test_a_tiny_value_is_not_scientific_notation(self):
        self.assertNotIn("e-", format_cost(0.00007))

    def test_below_a_cent_is_spelled_out(self):
        self.assertIn("under", format_cost(0.00007))

    def test_an_ordinary_value_gets_two_decimals(self):
        self.assertEqual(format_cost(1.234), "US$ 1.23")

    def test_zero_reads_as_zero(self):
        self.assertIn("0", format_cost(0))


if __name__ == "__main__":
    unittest.main()


class TestPriceTable(unittest.TestCase):
    """A price per model, and the arithmetic pinned to a literal per model.

    The bug this guards is not a crash: it is a number quoted with confidence for
    the wrong model. Every row carries its expected cost per image written out, so
    editing a price without meaning to breaks a test instead of a bill.
    """

    # cost of ONE image, synchronous, at 600 input + 200 output tokens.
    PER_IMAGE = {
        "gemini-2.5-flash-lite": 0.00014,   # 600·$0.10/1M + 200·$0.40/1M
        "gemini-3.5-flash-lite": 0.00068,   # 600·$0.30/1M + 200·$2.50/1M
    }

    def test_every_model_in_the_table_has_its_cost_pinned(self):
        self.assertEqual(set(MODEL_PRICES), set(self.PER_IMAGE),
                         "a model was added to the table with no expected cost pinned")

    def test_each_model_costs_exactly_what_is_written_here(self):
        for model, expected in self.PER_IMAGE.items():
            with self.subTest(model=model):
                self.assertEqual(estimate_cost(1, batch=False, model=model), expected)

    def test_batch_is_still_exactly_half(self):
        for model in self.PER_IMAGE:
            with self.subTest(model=model):
                self.assertEqual(estimate_cost(1000, batch=True, model=model),
                                 estimate_cost(1000, batch=False, model=model) / 2)

    def test_the_retired_model_still_prices_exactly_as_it_always_did(self):
        # 0.07 batch / 0.14 synchronous per thousand: the numbers this repo shipped.
        self.assertEqual(estimate_cost(1000, batch=True,
                                       model="gemini-2.5-flash-lite"), 0.07)
        self.assertEqual(estimate_cost(1000, batch=False,
                                       model="gemini-2.5-flash-lite"), 0.14)

    def test_the_default_model_is_priced_from_the_table(self):
        pricing = resolve_pricing(DEFAULT_MODEL)
        self.assertTrue(pricing.known)
        self.assertIn(DEFAULT_MODEL, pricing.origin)

    def test_a_model_outside_the_table_gets_no_number_at_all(self):
        self.assertIsNone(estimate_cost(1000, model="gemini-9-imagined"))
        self.assertFalse(resolve_pricing("gemini-9-imagined").known)

    def test_an_unpriceable_estimate_reads_as_unknown_not_as_zero(self):
        self.assertIn("unknown", format_cost(None).lower())
        self.assertEqual(format_cost(0.0), "US$ 0.00")


class TestPriceFromTheEnvironment(unittest.TestCase):
    """The number lives in the env so that fixing it is not a code change."""

    def test_the_env_overrides_the_table(self):
        pricing = resolve_pricing("gemini-2.5-flash-lite",
                                  {"LUPA_INPUT_PRICE": "1.00", "LUPA_OUTPUT_PRICE": "2.00"})
        self.assertEqual((pricing.input_price, pricing.output_price), (1.0, 2.0))

    def test_the_env_can_price_a_model_the_table_never_heard_of(self):
        pricing = resolve_pricing("gemini-9-imagined",
                                  {"LUPA_INPUT_PRICE": "0.5", "LUPA_OUTPUT_PRICE": "1.5"})
        self.assertTrue(pricing.known)
        self.assertEqual(estimate_cost(1000, batch=False, model="gemini-9-imagined",
                                       env={"LUPA_INPUT_PRICE": "0.5",
                                            "LUPA_OUTPUT_PRICE": "1.5"}), 0.6)

    def test_the_origin_says_the_env_overrode_the_table(self):
        pricing = resolve_pricing("gemini-2.5-flash-lite", {"LUPA_INPUT_PRICE": "1.00"})
        self.assertIn("LUPA_INPUT_PRICE", pricing.origin)

    def test_junk_in_the_env_does_not_take_the_run_down(self):
        pricing = resolve_pricing("gemini-2.5-flash-lite",
                                  {"LUPA_INPUT_PRICE": "cheap", "LUPA_OUTPUT_PRICE": "-3"})
        self.assertEqual((pricing.input_price, pricing.output_price), (0.10, 0.40))
        self.assertTrue(pricing.complaints, "a rejected value must be said out loud")
        self.assertIn("LUPA_INPUT_PRICE", " ".join(pricing.complaints))
        self.assertIn("LUPA_OUTPUT_PRICE", " ".join(pricing.complaints))

    def test_junk_in_the_env_with_no_table_to_fall_back_on_is_unknown(self):
        pricing = resolve_pricing("gemini-9-imagined", {"LUPA_INPUT_PRICE": "cheap"})
        self.assertFalse(pricing.known)

    def test_an_empty_value_is_simply_absent(self):
        pricing = resolve_pricing("gemini-2.5-flash-lite", {"LUPA_INPUT_PRICE": ""})
        self.assertEqual(pricing.input_price, 0.10)
        self.assertFalse(pricing.complaints)

    def test_free_is_a_legitimate_price(self):
        pricing = resolve_pricing("gemini-9-imagined",
                                  {"LUPA_INPUT_PRICE": "0", "LUPA_OUTPUT_PRICE": "0"})
        self.assertTrue(pricing.known)
        self.assertEqual(estimate_cost(1000, model="gemini-9-imagined",
                                       env={"LUPA_INPUT_PRICE": "0",
                                            "LUPA_OUTPUT_PRICE": "0"}), 0.0)
