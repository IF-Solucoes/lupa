"""Vision description: prompt, parsing, and the merge with what was already free."""
import unittest
from lupa.caption import (build_prompt, parse_response, merge, estimate_cost,
                          format_cost, InvalidResponse, MODEL_PRICES, resolve_pricing)
from lupa.gemini import DEFAULT_MODEL

# `kind` pre-settled: classify() no longer does this, but merge() must still honour a
# caller that knows better than the model, and build_prompt() must still stay quiet
# about a field already decided.
PHOTO_META = {"file": "table.jpg", "kind": "photo", "medium": "na", "source": "camera",
              "aspect": "3:2", "orientation": "landscape"}
AMBIGUOUS_META = {"file": "banner.jpg", "kind": None, "medium": None, "source": "camera",
                  "aspect": "3:2", "orientation": "landscape"}

VISION = {"caption": "Wooden table with bread", "tags": ["Food", "WOOD", "food"],
          "scene": "indoor", "people": 0, "palette": ["#c8a06a"],
          "kind": "design", "medium": "digital"}


class TestPrompt(unittest.TestCase):
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

    def test_a_missing_caption_does_not_crash(self):
        self.assertEqual(merge(PHOTO_META, {})["caption"], "")


class TestTheModelSuppliesTheText(unittest.TestCase):
    """`text` and `has_text` come from the only party that can see the image.

    They used to come from Drive's `contentSnippet`, a field that does not exist in
    the API — so both were dead on arrival, and the prompt actively forbade the one
    party that could have filled them.
    """

    def test_the_prompt_no_longer_claims_the_text_was_already_extracted(self):
        prompt = build_prompt(PHOTO_META).lower()
        self.assertNotIn("do not transcribe", prompt)
        self.assertNotIn("already been extracted", prompt)

    def test_the_prompt_asks_for_the_flag_and_for_the_transcription(self):
        prompt = build_prompt(PHOTO_META)
        self.assertIn('"has_text"', prompt)
        self.assertIn('"text"', prompt)

    def test_the_transcription_is_bounded_so_the_output_cost_is_bounded(self):
        self.assertIn("60 words", build_prompt(PHOTO_META))

    def test_the_transcription_lands_in_the_text_field(self):
        item = merge(PHOTO_META, dict(VISION, has_text=True, text="SALE 50% OFF"))
        self.assertTrue(item["has_text"])
        self.assertEqual(item["text"], "SALE 50% OFF")

    def test_metadata_cannot_smuggle_text_in_any_more(self):
        # ocr_text and has_text in the metadata are leftovers from the dead field
        item = merge(dict(PHOTO_META, ocr_text="GHOST", has_text=True), {"caption": "x"})
        self.assertEqual(item["text"], "")
        self.assertIs(item["has_text"], False)

    def test_the_word_false_in_a_string_is_not_true(self):
        # a model answering JSON by hand writes "false" often enough to matter
        self.assertIs(merge(PHOTO_META, dict(VISION, has_text="false"))["has_text"], False)
        self.assertIs(merge(PHOTO_META, dict(VISION, has_text="true"))["has_text"], True)

    def test_a_model_that_forgets_the_two_fields_does_not_crash(self):
        item = merge(PHOTO_META, {"caption": "x"})
        self.assertEqual(item["text"], "")
        self.assertIs(item["has_text"], False)

    def test_the_dead_google_labels_are_not_written_any_more(self):
        self.assertNotIn("labels", merge(PHOTO_META, VISION))


class TestCost(unittest.TestCase):
    def test_batch_costs_less_than_synchronous(self):
        self.assertLess(estimate_cost(1000, batch=True), estimate_cost(1000, batch=False))

    def test_a_thousand_images_cost_under_a_dollar(self):
        # Was "cost cents", against a 600/200 budget nobody had ever checked. At
        # the measured budget the same thousand images quote US$ 0.58 in batch on
        # the default model: still small, no longer a fantasy.
        self.assertLess(estimate_cost(1000, batch=True), 1.00)

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

    # cost of ONE image, synchronous, at the MEASURED budget of
    # 1600 input + 275 output tokens (see caption.py for where those came from).
    PER_IMAGE = {
        "gemini-2.5-flash-lite": 0.00027,     # 1600·$0.10/1M + 275·$0.40/1M
        # 0.0011675 exactly, as estimate_cost rounds it to six decimals
        "gemini-3.5-flash-lite": 0.001168,    # 1600·$0.30/1M + 275·$2.50/1M
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

    def test_the_retired_model_is_still_priced_from_the_same_two_numbers(self):
        # $0.10 in / $0.40 out per 1M, unchanged and unchangeable without breaking
        # a test. The quote per thousand moved — 0.07/0.14 before, 0.135/0.27 now —
        # because the token BUDGET was measured, not because a price was touched.
        # That is the whole point of keeping the two apart.
        self.assertEqual(MODEL_PRICES["gemini-2.5-flash-lite"], (0.10, 0.40))
        self.assertEqual(estimate_cost(1000, batch=True,
                                       model="gemini-2.5-flash-lite"), 0.135)
        self.assertEqual(estimate_cost(1000, batch=False,
                                       model="gemini-2.5-flash-lite"), 0.27)

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
        # 1000 × (1600 in · $0.5/1M + 275 out · $1.5/1M)
        self.assertEqual(estimate_cost(1000, batch=False, model="gemini-9-imagined",
                                       env={"LUPA_INPUT_PRICE": "0.5",
                                            "LUPA_OUTPUT_PRICE": "1.5"}), 1.2125)

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


class TestTheMeterAddsUpWhatWasCounted(unittest.TestCase):
    """One number per run, built from the per-response numbers the API returned.

    The budgets INPUT_TOKENS_PER_IMAGE / OUTPUT_TOKENS_PER_IMAGE were never
    checked against anything. This is the instrument that checks them.
    """

    def meter(self, *usages):
        from lupa.caption import UsageMeter
        instrument = UsageMeter()
        for usage in usages:
            instrument.record(usage)
        return instrument

    def test_it_sums_the_input_and_the_output_of_the_whole_run(self):
        instrument = self.meter((588, 103), (600, 120))
        self.assertEqual((instrument.input_tokens, instrument.output_tokens),
                         (1188, 223))

    def test_it_counts_how_many_responses_actually_reported(self):
        self.assertEqual(self.meter((1, 2), (3, 4)).counted, 2)

    def test_an_unreported_response_is_unknown_and_adds_nothing(self):
        instrument = self.meter((588, 103), None)
        self.assertEqual(instrument.unknown, 1)
        self.assertEqual(instrument.counted, 1)
        self.assertEqual(instrument.input_tokens, 588,
                         "an unreported response must not be counted as a free one")

    def test_a_meter_that_heard_nothing_knows_nothing(self):
        self.assertFalse(self.meter(None, None).known)

    def test_a_meter_that_heard_something_knows_it(self):
        self.assertTrue(self.meter((1, 1)).known)

    def test_it_averages_over_the_responses_that_reported(self):
        instrument = self.meter((580, 100), (620, 106), None)
        self.assertEqual(instrument.per_image, (600.0, 103.0))

    def test_without_any_report_there_is_no_average(self):
        self.assertIsNone(self.meter(None).per_image)

    def test_the_meter_survives_being_fed_from_several_threads(self):
        import threading

        instrument = self.meter()
        threads = [threading.Thread(target=lambda: [instrument.record((1, 1))
                                                    for _ in range(200)])
                   for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(instrument.input_tokens, 1600)


class TestWhatTheseTokensReallyCost(unittest.TestCase):
    def meter(self, *usages):
        from lupa.caption import UsageMeter
        instrument = UsageMeter()
        for usage in usages:
            instrument.record(usage)
        return instrument

    def test_the_cost_comes_from_the_counted_tokens_and_the_table(self):
        # 1M input at US$ 0.30 and 1M output at US$ 2.50, synchronous.
        instrument = self.meter((1_000_000, 1_000_000))
        self.assertAlmostEqual(instrument.cost(batch=False, model=DEFAULT_MODEL), 2.80)

    def test_batch_still_costs_exactly_half(self):
        instrument = self.meter((1_000_000, 1_000_000))
        self.assertAlmostEqual(instrument.cost(batch=True, model=DEFAULT_MODEL), 1.40)

    def test_a_model_with_no_price_yields_no_number_at_all(self):
        self.assertIsNone(self.meter((100, 100)).cost(model="gemini-does-not-exist"))

    def test_a_meter_that_heard_nothing_has_no_cost_either(self):
        self.assertIsNone(self.meter(None).cost(model=DEFAULT_MODEL))


class TestTheBudgetMeetsTheBill(unittest.TestCase):
    """The line that closes the cycle: what was quoted, against what was charged.

    Until now the run printed an estimate before spending and never came back to
    say whether it had been right.
    """

    def meter(self, *usages):
        from lupa.caption import UsageMeter
        instrument = UsageMeter()
        for usage in usages:
            instrument.record(usage)
        return instrument

    def lines(self, instrument, **kw):
        from lupa.caption import usage_lines
        return "\n".join(usage_lines(instrument, **kw))

    def test_it_states_the_totals_the_api_counted(self):
        text = self.lines(self.meter((588, 103), (600, 120)))
        self.assertIn("1188", text)
        self.assertIn("223", text)

    def test_it_puts_the_budget_on_record_next_to_the_measurement(self):
        from lupa.caption import INPUT_TOKENS_PER_IMAGE, OUTPUT_TOKENS_PER_IMAGE
        text = self.lines(self.meter((589, 103)))
        self.assertIn(str(INPUT_TOKENS_PER_IMAGE), text)
        self.assertIn(str(OUTPUT_TOKENS_PER_IMAGE), text)
        self.assertIn("589", text)

    def test_it_says_out_loud_when_the_measurement_overran_the_budget(self):
        text = self.lines(self.meter((1900, 400))).lower()
        self.assertIn("over", text,
                      "a budget that no longer covers the bill has to say so")

    def test_it_puts_the_estimate_next_to_the_money_actually_counted(self):
        text = self.lines(self.meter((1_000_000, 1_000_000)), estimated_cost=1.0,
                          batch=True, model=DEFAULT_MODEL)
        self.assertIn("1.00", text)   # estimated
        self.assertIn("1.40", text)   # measured

    def test_without_a_single_report_it_says_unknown_and_never_zero(self):
        text = self.lines(self.meter(None, None), estimated_cost=0.5)
        self.assertIn("unknown", text.lower())
        self.assertNotIn("0 input", text)

    def test_it_says_how_many_images_never_reported(self):
        text = self.lines(self.meter((588, 103), None, None))
        self.assertIn("2", text)
        self.assertIn("did not report", text.lower())

    def test_a_run_where_every_image_reported_does_not_nag_about_it(self):
        text = self.lines(self.meter((588, 103)))
        self.assertNotIn("did not report", text.lower())

    def test_an_axis_over_budget_never_claims_the_run_cost_more_than_quoted(self):
        """Input a hair over, output far under: this run cost LESS than it quoted.

        Crying under-quote here would be a false alarm about money, which is the
        exact failure mode this whole measurement exists to end.
        """
        text = self.lines(self.meter((1601, 100)), estimated_cost=1.0,
                          batch=True, model=DEFAULT_MODEL).lower()
        self.assertIn("input", text)
        self.assertNotIn("cost more than", text)

    def test_a_run_that_really_did_cost_more_than_quoted_says_so(self):
        text = self.lines(self.meter((1_000_000, 1_000_000)), estimated_cost=0.01,
                          batch=True, model=DEFAULT_MODEL).lower()
        self.assertIn("cost more than", text)

    def test_a_run_inside_both_budgets_raises_no_alarm_at_all(self):
        text = self.lines(self.meter((500, 100)), estimated_cost=1.0,
                          batch=True, model=DEFAULT_MODEL).lower()
        self.assertNotIn("no longer covers", text)
        self.assertNotIn("cost more than", text)

    def test_it_never_proposes_a_new_budget_by_changing_one(self):
        from lupa import caption
        self.assertEqual(caption.INPUT_TOKENS_PER_IMAGE, 1600)
        self.assertEqual(caption.OUTPUT_TOKENS_PER_IMAGE, 275)


class TestTheBudgetsAgreeWithTheMeasurement(unittest.TestCase):
    """The two budgets are a measurement now. This class is the receipt.

    Measured on 2026-08-20, on one real batch run of 9 images through
    gemini-3.5-flash-lite: 12741 input and 1970 output tokens over 9 responses,
    which is 1415.7 input and 218.9 output per image. The input side was then
    split with the free countTokens endpoint: 333 tokens of prompt, 1080–1107
    tokens for the image part — and that image part costs the same whether the
    thumbnail goes up at 128px or at 1536px, so no downscaling moves it.

    What is pinned here is the RELATIONSHIP, not the literal. A budget under the
    measurement quotes a price nobody will be charged, which is the defect that
    produced these numbers; a budget far above it frightens people away from a
    run that really does cost cents. Both directions have a test.
    """
    # per image, from the run of 2026-08-20 (n=9, gemini-3.5-flash-lite, batch)
    MEASURED_INPUT = 1415.7
    MEASURED_OUTPUT = 218.9

    # countTokens, same day, same model: the prompt is fixed and the image part
    # is flat, so the input side of one request is these two added together.
    PROMPT_TOKENS = 333
    LARGEST_IMAGE_PART = 1107

    def budgets(self):
        from lupa.caption import INPUT_TOKENS_PER_IMAGE, OUTPUT_TOKENS_PER_IMAGE
        return INPUT_TOKENS_PER_IMAGE, OUTPUT_TOKENS_PER_IMAGE

    def test_the_input_budget_covers_what_the_api_counted(self):
        inbound, _ = self.budgets()
        self.assertGreaterEqual(inbound, self.MEASURED_INPUT,
                                "the input budget quotes less than the API charged")

    def test_the_output_budget_covers_what_the_api_counted(self):
        _, outbound = self.budgets()
        self.assertGreaterEqual(outbound, self.MEASURED_OUTPUT,
                                "the output budget quotes less than the API charged")

    def test_the_input_budget_covers_the_prompt_plus_the_dearest_image_part(self):
        inbound, _ = self.budgets()
        self.assertGreaterEqual(inbound, self.PROMPT_TOKENS + self.LARGEST_IMAGE_PART)

    def test_neither_budget_is_padded_past_a_sane_margin(self):
        inbound, outbound = self.budgets()
        self.assertLess(inbound, self.MEASURED_INPUT * 1.5)
        self.assertLess(outbound, self.MEASURED_OUTPUT * 1.5)


class TestTheModelIsAskedForProperNouns(unittest.TestCase):
    """`entities` — the names on the piece, which generic tags can never carry.

    A collection of 875 images from one veterinary clinic came back with a
    vocabulary of `dog`, `medical`, `clinic`, `gloves` — true of every clinic on
    earth and therefore useless to the agency that owns THIS one. The prompt never
    asked for a single proper noun, so none was ever written down.

    The dangerous half of the fix is invention: a hallucinated service name reads
    exactly like a real one, and a human trusts a proper noun on sight. The prompt
    has to forbid it in as many words, and the test has to hold that line.
    """

    def test_the_prompt_asks_for_the_field(self):
        self.assertIn('"entities"', build_prompt(PHOTO_META))

    def test_the_prompt_names_what_counts_as_one(self):
        prompt = build_prompt(PHOTO_META).lower()
        for word in ("service", "product", "campaign", "brand"):
            self.assertIn(word, prompt)

    def test_the_prompt_forbids_inventing_them(self):
        """The whole field is worthless the moment one name in it is made up:
        a human who reads a proper noun stops checking."""
        block = build_prompt(PHOTO_META).split('"entities"')[1].lower()
        self.assertIn("do not invent", block)

    def test_the_prompt_says_an_empty_list_is_a_valid_answer(self):
        """Most photographs have no entity at all. A model that believes the field
        must be filled fills it, and every fill is a lie."""
        self.assertIn("[]", build_prompt(PHOTO_META))

    def test_the_prompt_says_the_overlap_with_text_is_wanted(self):
        """The service names usually ARE in the transcribed text. A model left to
        guess reads the repetition as redundancy and drops the field."""
        prompt = build_prompt(PHOTO_META)
        entities_block = prompt.split('"entities"')[1]
        self.assertIn("text", entities_block)


class TestEntitiesReachTheItem(unittest.TestCase):
    def test_the_names_survive_the_merge(self):
        item = merge(PHOTO_META, dict(VISION, entities=["Castração", "VacinAÇÃO"]))
        self.assertEqual(item["entities"], ["Castração", "VacinAÇÃO"])

    def test_case_is_preserved_because_these_are_proper_nouns(self):
        item = merge(PHOTO_META, dict(VISION, entities=["Banho e Tosa"]))
        self.assertEqual(item["entities"], ["Banho e Tosa"])

    def test_a_model_that_says_nothing_leaves_an_empty_list(self):
        self.assertEqual(merge(PHOTO_META, VISION)["entities"], [])

    def test_null_is_an_empty_list_and_not_a_string(self):
        self.assertEqual(merge(PHOTO_META, dict(VISION, entities=None))["entities"], [])

    def test_the_word_none_is_not_an_entity(self):
        """`["none"]` is the classic way a model fills a field it should leave
        empty, and it would land in by-entity/ as a proper noun of its own."""
        for junk in (["none"], ["N/A"], ["nenhum"], ["unknown"], [""], ["  "], ["-"]):
            self.assertEqual(merge(PHOTO_META, dict(VISION, entities=junk))["entities"], [],
                             f"{junk!r} should not survive")

    def test_a_string_instead_of_a_list_is_not_exploded_into_letters(self):
        item = merge(PHOTO_META, dict(VISION, entities="Castração"))
        self.assertEqual(item["entities"], ["Castração"])

    def test_duplicates_collapse_ignoring_case(self):
        item = merge(PHOTO_META, dict(VISION, entities=["Vacinação", "vacinação", "V "]))
        self.assertEqual(item["entities"], ["Vacinação", "V"])

    def test_entities_are_not_mixed_into_the_generic_tags(self):
        item = merge(PHOTO_META, dict(VISION, entities=["Castração"]))
        self.assertNotIn("castração", item["tags"])
