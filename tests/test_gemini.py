"""Building Gemini requests and reading batch results."""
import base64
import io
import json
import unittest
import urllib.error
import urllib.request

from lupa import gemini
from lupa.gemini import build_content, batch_line, read_batch_results

IMG = b"\x89PNG\r\n\x1a\n-test-bytes"


class TestContent(unittest.TestCase):
    def test_it_sends_the_image_as_base64(self):
        c = build_content("describe", IMG, "image/png")
        data = c["contents"][0]["parts"][1]["inline_data"]
        self.assertEqual(data["mime_type"], "image/png")
        self.assertEqual(base64.b64decode(data["data"]), IMG)

    def test_it_sends_the_prompt_alongside(self):
        c = build_content("describe this", IMG, "image/png")
        self.assertEqual(c["contents"][0]["parts"][0]["text"], "describe this")

    def test_it_asks_the_model_for_json(self):
        c = build_content("x", IMG, "image/png")
        self.assertEqual(c["generationConfig"]["responseMimeType"], "application/json")


class TestBatch(unittest.TestCase):
    def test_each_line_carries_its_key_back(self):
        line = json.loads(batch_line("id-42", "prompt", IMG, "image/png"))
        self.assertEqual(line["key"], "id-42")

    def test_each_line_is_single_line_json(self):
        self.assertNotIn("\n", batch_line("id-42", "p", IMG, "image/png"))

    def test_results_come_back_keyed(self):
        raw = "\n".join([
            json.dumps({"key": "a", "response": {"candidates": [
                {"content": {"parts": [{"text": '{"caption": "first"}'}]}}]}}),
            json.dumps({"key": "b", "response": {"candidates": [
                {"content": {"parts": [{"text": '{"caption": "second"}'}]}}]}}),
        ])
        r = read_batch_results(raw)
        self.assertEqual(r["a"]["caption"], "first")
        self.assertEqual(r["b"]["caption"], "second")

    def test_a_failed_item_does_not_take_down_the_others(self):
        raw = "\n".join([
            json.dumps({"key": "a", "error": {"message": "quota"}}),
            json.dumps({"key": "b", "response": {"candidates": [
                {"content": {"parts": [{"text": '{"caption": "ok"}'}]}}]}}),
        ])
        r = read_batch_results(raw)
        self.assertNotIn("a", r)
        self.assertEqual(r["b"]["caption"], "ok")

    def test_a_blank_line_in_the_batch_is_ignored(self):
        raw = '\n\n{"key": "b", "response": {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}}\n\n'
        self.assertEqual(list(read_batch_results(raw)), ["b"])


class FakePolling:
    """Stands in for gemini._get, the only line this module has to the network.

    Substituting the module attribute — instead of injecting a getter nobody but
    the tests would ever pass — keeps the production signature honest and leaves
    the real await_batch running: its own deadline, its own loop, its own state
    machine. Only the socket is missing. interval/timeout_s are tightened to
    milliseconds so a real timeout takes a real (short) amount of real time.
    """

    def __init__(self, state="JOB_STATE_RUNNING"):
        self.state = state
        self.calls = []

    def __call__(self, url, api_key):
        self.calls.append(url)
        return json.dumps({"metadata": {"state": self.state}}).encode()


class TestAwaitBatchTimeout(unittest.TestCase):
    """The batch is charged on creation. A wait that gives up must never read
    like a cancelled purchase."""

    def setUp(self):
        self.original = gemini._get

    def tearDown(self):
        gemini._get = self.original

    def wait(self, state="JOB_STATE_RUNNING", **kw):
        polling = FakePolling(state)
        gemini._get = polling
        with self.assertRaises(gemini.GeminiError) as caught:
            gemini.await_batch("api-key", "batches/xyz-789",
                               interval=0.01, timeout_s=0.05, **kw)
        return polling, caught.exception

    def test_it_really_polls_before_giving_up(self):
        polling, _ = self.wait()
        self.assertGreaterEqual(len(polling.calls), 1,
                                "await_batch never ran; the test proves nothing")

    def test_the_timeout_says_the_batch_was_already_charged(self):
        _, error = self.wait()
        self.assertIn("charged", str(error).lower(),
                      "the message lets the user think the money was not spent")

    def test_the_timeout_names_the_batch(self):
        _, error = self.wait()
        self.assertIn("batches/xyz-789", str(error),
                      "without the batch name the money is unrecoverable")

    def test_the_timeout_spells_out_the_command_that_resumes(self):
        _, error = self.wait(resume_hint="lupa update if-editorial --resume-batch")
        self.assertIn("lupa update if-editorial --resume-batch", str(error))

    def test_a_timeout_is_a_kind_of_its_own(self):
        _, error = self.wait()
        self.assertIsInstance(error, gemini.BatchTimeout)

    def test_a_dead_batch_is_not_a_timeout(self):
        _, error = self.wait("JOB_STATE_FAILED")
        self.assertNotIsInstance(
            error, gemini.BatchTimeout,
            "a batch that ended badly is not resumable and must not look like one")


if __name__ == "__main__":
    unittest.main()


class TestRetiredModel(unittest.TestCase):
    """Google retires a model and every single image fails with the same 404.
    The one thing this must never be is silent about why."""

    # The body Google actually returned on 2026-08-20 for a key created that week.
    BODY = json.dumps({"error": {
        "code": 404,
        "message": ("This model models/gemini-2.5-flash-lite is no longer available "
                    "to new users. Please update your code to use "
                    "models/gemini-3.5-flash-lite"),
        "status": "NOT_FOUND"}}).encode()

    def setUp(self):
        self.original = urllib.request.urlopen

    def tearDown(self):
        urllib.request.urlopen = self.original

    def refuse(self, body=None):
        """Every call to the API answers with one real HTTPError carrying a real body."""
        payload = self.BODY if body is None else body

        def urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                getattr(request, "full_url", "http://x"), 404, "Not Found", {},
                io.BytesIO(payload))

        urllib.request.urlopen = urlopen
        with self.assertRaises(gemini.GeminiError) as caught:
            gemini.describe("api-key", "prompt", IMG, "image/png")
        return caught.exception

    def test_the_default_model_is_not_the_retired_one(self):
        self.assertNotEqual(gemini.DEFAULT_MODEL, "gemini-2.5-flash-lite",
                            "out of the box, every image fails with a 404")

    def test_the_default_model_is_pinned_not_a_floating_alias(self):
        self.assertFalse(gemini.DEFAULT_MODEL.endswith("-latest"))

    def test_a_retirement_is_its_own_kind_of_error(self):
        self.assertIsInstance(self.refuse(), gemini.ModelRetired)

    def test_it_names_the_replacement_google_handed_back(self):
        error = self.refuse()
        self.assertIsInstance(error, gemini.ModelRetired,
                              "a raw body dump happens to contain the name too")
        self.assertIn("gemini-3.5-flash-lite", str(error),
                      "the fix is in Google's own answer; not repeating it wastes it")

    def test_it_names_the_model_that_was_retired(self):
        error = self.refuse()
        self.assertIsInstance(error, gemini.ModelRetired)
        self.assertIn("gemini-2.5-flash-lite", str(error))

    def test_it_says_how_to_override_the_model(self):
        self.assertIn("LUPA_MODEL", str(self.refuse()))

    def test_it_carries_the_replacement_as_data_too(self):
        self.assertEqual(self.refuse().replacement, "gemini-3.5-flash-lite")

    def test_an_ordinary_404_is_not_mistaken_for_a_retirement(self):
        error = self.refuse(json.dumps(
            {"error": {"code": 404, "message": "Requested entity was not found."}}).encode())
        self.assertNotIsInstance(error, gemini.ModelRetired)
        self.assertIn("404", str(error))
