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


class TestUsageMetadata(unittest.TestCase):
    """What the API charged, read off the response instead of guessed.

    The token budgets in caption.py were written by hand and never confronted
    with the bill. usageMetadata IS the bill, and it arrives with every answer.
    Field names taken from the GenerateContentResponse.usageMetadata schema, not
    from memory.
    """

    RESPONSE = {
        "candidates": [{"content": {"parts": [{"text": '{"caption": "ok"}'}]}}],
        "usageMetadata": {"promptTokenCount": 588, "candidatesTokenCount": 103,
                          "totalTokenCount": 691},
    }

    def test_it_reads_the_two_fields_google_actually_writes(self):
        self.assertEqual(gemini.usage_of(self.RESPONSE), (588, 103))

    def test_a_response_without_usage_is_unknown_and_never_zero(self):
        self.assertIsNone(gemini.usage_of({"candidates": []}),
                          "zero would read as a free image and quietly corrupt the total")

    def test_nothing_at_all_is_unknown_too(self):
        self.assertIsNone(gemini.usage_of(None))

    def test_thinking_tokens_are_output_tokens_because_they_are_billed(self):
        response = dict(self.RESPONSE, usageMetadata={
            "promptTokenCount": 588, "candidatesTokenCount": 103,
            "thoughtsTokenCount": 40, "totalTokenCount": 731})
        self.assertEqual(gemini.usage_of(response), (588, 143),
                         "thoughts are charged as output; dropping them under-counts")

    def test_a_half_filled_usage_block_still_yields_a_number(self):
        self.assertEqual(gemini.usage_of({"usageMetadata": {"promptTokenCount": 600}}),
                         (600, 0))


class TestSynchronousUsageReachesTheCaller(unittest.TestCase):
    """The per-image path must hand back what it spent, not only what it said."""

    def setUp(self):
        self.original = urllib.request.urlopen

    def tearDown(self):
        urllib.request.urlopen = self.original

    def answering(self, payload):
        def urlopen(request, timeout=None):
            return io.BytesIO(json.dumps(payload).encode())
        urllib.request.urlopen = urlopen

    def test_describe_reports_what_the_api_counted(self):
        self.answering(TestUsageMetadata.RESPONSE)
        seen = []
        gemini.describe("api-key", "prompt", IMG, "image/png", on_usage=seen.append)
        self.assertEqual(seen, [(588, 103)])

    def test_an_answer_with_no_content_still_reports_the_tokens_it_burned(self):
        # The money left before the content failed to arrive. Reporting only on
        # success is how a run of failures looks free.
        self.answering({"candidates": [],
                        "usageMetadata": {"promptTokenCount": 588,
                                          "candidatesTokenCount": 0}})
        seen = []
        with self.assertRaises(gemini.GeminiError):
            gemini.describe("api-key", "prompt", IMG, "image/png", on_usage=seen.append)
        self.assertEqual(seen, [(588, 0)])

    def test_a_model_that_reports_nothing_reports_unknown_once(self):
        self.answering({"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})
        seen = []
        gemini.describe("api-key", "prompt", IMG, "image/png", on_usage=seen.append)
        self.assertEqual(seen, [None])

    def test_describe_without_a_listener_still_works(self):
        self.answering(TestUsageMetadata.RESPONSE)
        self.assertEqual(gemini.describe("api-key", "p", IMG, "image/png"),
                         {"caption": "ok"})


class TestBatchUsageReachesTheCaller(unittest.TestCase):
    """Batch is the default path — the one that pays for almost every token.

    If usage only came back from the synchronous path, the measurement would
    describe the mode nobody uses.
    """

    @staticmethod
    def item(key, text='{"caption": "ok"}', usage=(588, 103)):
        response = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
        if usage is not None:
            response["usageMetadata"] = {"promptTokenCount": usage[0],
                                         "candidatesTokenCount": usage[1],
                                         "totalTokenCount": sum(usage)}
        return json.dumps({"key": key, "response": response})

    def test_every_batch_item_reports_its_own_usage(self):
        seen = []
        raw = "\n".join([self.item("a"), self.item("b", usage=(600, 120))])
        read_batch_results(raw, on_usage=seen.append)
        self.assertEqual(sorted(seen), [(588, 103), (600, 120)])

    def test_the_descriptions_still_come_back_while_usage_is_collected(self):
        results = read_batch_results(self.item("a"), on_usage=lambda u: None)
        self.assertEqual(results["a"]["caption"], "ok")

    def test_a_batch_item_that_reports_no_usage_is_unknown_not_zero(self):
        seen = []
        read_batch_results(self.item("a", usage=None), on_usage=seen.append)
        self.assertEqual(seen, [None])

    def test_a_failed_batch_item_is_still_accounted_for(self):
        seen = []
        raw = json.dumps({"key": "a", "error": {"message": "quota"}})
        read_batch_results(raw, on_usage=seen.append)
        self.assertEqual(seen, [None],
                         "an item that fell out of the results must not fall out "
                         "of the accounting too")

    def test_reading_a_batch_without_a_listener_still_works(self):
        self.assertEqual(list(read_batch_results(self.item("a"))), ["a"])


# The body the live API returned for a real, already-paid batch on 2026-08-20,
# pasted here verbatim (minus fields nothing reads). It is the fixture because it
# is the contract: the state is BATCH_STATE_SUCCEEDED, not the JOB_STATE_SUCCEEDED
# this module used to compare against, and that one word cost three hours of
# polling per run.
REAL_BATCH = {
    "name": "batches/3a96ht58d9rd3fci7tg3qlrhlfawe5ykp6ge",
    "metadata": {
        "@type": "type.googleapis.com/google.ai.generativelanguage.v1main.GenerateContentBatch",
        "model": "models/gemini-3.5-flash-lite",
        "displayName": "lupa-batch",
        "inputConfig": {"fileName": "files/voe5u4gdj968"},
        "output": {"responsesFile": "files/batch-3a96ht58d9rd3fci7tg3qlrhlfawe5ykp6ge"},
        "createTime": "2026-08-20T20:08:31.015405218Z",
        "endTime": "2026-08-20T20:10:25.852081585Z",
        "batchStats": {"requestCount": "9", "successfulRequestCount": "9"},
        "state": "BATCH_STATE_SUCCEEDED",
        "name": "batches/3a96ht58d9rd3fci7tg3qlrhlfawe5ykp6ge",
    },
    "done": True,
    "response": {
        "@type": "type.googleapis.com/google.ai.generativelanguage.v1main."
                 "GenerateContentBatchOutput",
        "responsesFile": "files/batch-3a96ht58d9rd3fci7tg3qlrhlfawe5ykp6ge",
    },
}

# One line of the results file that batch really produced, downloaded from
# .../download/v1beta/files/batch-...:download?alt=media
REAL_RESULT_LINE = json.dumps({
    "response": {
        "candidates": [{"content": {"parts": [
            {"text": ('{\n  "caption": "A white text logo on a black background '
                      'reading Clinica Veterinaria NOROESTE.",\n'
                      '  "tags": ["logo", "text"],\n  "scene": "na",\n'
                      '  "people": 0,\n  "palette": ["#000000", "#ffffff"],\n'
                      '  "has_text": true,\n  "text": "Clinica Veterinaria NOROESTE",\n'
                      '  "kind": "logo",\n  "medium": "digital"\n}')},
            {"thoughtSignature": "El4KXAERTTIP"}], "role": "model"},
            "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 1427, "candidatesTokenCount": 144,
                          "totalTokenCount": 1571},
        "modelVersion": "gemini-3.5-flash-lite",
        "responseId": "CV-Haon5MNuA_PUP95Gg2Q4",
    },
    "key": "00_COM.png",
})

# The full enum, read from the live discovery document (v1beta, revision
# 20260816) — the non-terminal names matter as much as the terminal ones, because
# treating one of them as unknown would abort a batch that is merely working.
LIVE_TERMINAL = ("BATCH_STATE_SUCCEEDED", "BATCH_STATE_FAILED",
                 "BATCH_STATE_CANCELLED", "BATCH_STATE_EXPIRED")
LIVE_PENDING = ("BATCH_STATE_UNSPECIFIED", "BATCH_STATE_PENDING",
                "BATCH_STATE_RUNNING")


class FakeApi:
    """Serves the two GETs await_batch makes: the poll and the results download."""

    def __init__(self, state, batch=None, body=REAL_RESULT_LINE + "\n"):
        self.state = state
        self.batch = json.loads(json.dumps(batch if batch is not None else REAL_BATCH))
        self.body = body
        self.polls = []
        self.downloads = []

    def __call__(self, url, api_key):
        if ":download" in url:
            self.downloads.append(url)
            return self.body.encode()
        self.polls.append(url)
        job = self.batch
        if self.state is None:
            job["metadata"].pop("state", None)
        else:
            job["metadata"]["state"] = self.state
        return json.dumps(job).encode()


class TestRealBatchStateNames(unittest.TestCase):
    """The API answers BATCH_STATE_*. Comparing against JOB_STATE_* meant a batch
    that finished in two minutes was never seen to finish at all: the wait ran to
    its three-hour ceiling and raised BatchTimeout on a job that had SUCCEEDED."""

    def setUp(self):
        self.original = gemini._get

    def tearDown(self):
        gemini._get = self.original

    def wait(self, state, **kw):
        api = FakeApi(state)
        gemini._get = api
        kw.setdefault("interval", 0.001)
        kw.setdefault("timeout_s", 0.5)
        return api, gemini.await_batch("api-key", REAL_BATCH["name"], **kw)

    def test_batch_state_succeeded_is_recognised_as_finished(self):
        _, raw = self.wait("BATCH_STATE_SUCCEEDED")
        self.assertIn("Clinica", raw)

    def test_it_does_not_poll_on_after_success(self):
        api, _ = self.wait("BATCH_STATE_SUCCEEDED")
        self.assertEqual(len(api.polls), 1,
                         "a finished batch was polled again; the ceiling is next")

    def test_the_results_of_a_real_batch_parse(self):
        _, raw = self.wait("BATCH_STATE_SUCCEEDED")
        parsed = gemini.read_batch_results(raw)
        self.assertEqual(parsed["00_COM.png"]["kind"], "logo")

    def test_the_real_usage_metadata_is_reported(self):
        _, raw = self.wait("BATCH_STATE_SUCCEEDED")
        seen = []
        gemini.read_batch_results(raw, on_usage=seen.append)
        self.assertEqual(seen, [(1427, 144)])

    def test_the_results_file_is_found_when_only_metadata_carries_it(self):
        batch = json.loads(json.dumps(REAL_BATCH))
        batch.pop("response")
        api = FakeApi("BATCH_STATE_SUCCEEDED", batch=batch)
        gemini._get = api
        raw = gemini.await_batch("api-key", REAL_BATCH["name"],
                                 interval=0.001, timeout_s=0.5)
        self.assertIn("Clinica", raw)

    def test_every_terminal_state_ends_the_wait(self):
        for state in LIVE_TERMINAL[1:]:
            with self.subTest(state=state):
                api = FakeApi(state)
                gemini._get = api
                with self.assertRaises(gemini.GeminiError) as caught:
                    gemini.await_batch("api-key", REAL_BATCH["name"],
                                       interval=0.001, timeout_s=5)
                self.assertIn(state, str(caught.exception))
                self.assertNotIsInstance(caught.exception, gemini.BatchTimeout)
                self.assertEqual(len(api.polls), 1)

    def test_the_states_that_mean_it_is_working_keep_the_wait_going(self):
        for state in LIVE_PENDING:
            with self.subTest(state=state):
                api = FakeApi(state)
                gemini._get = api
                with self.assertRaises(gemini.BatchTimeout):
                    gemini.await_batch("api-key", REAL_BATCH["name"],
                                       interval=0.001, timeout_s=0.05)
                self.assertGreater(len(api.polls), 1,
                                   "a batch still running was abandoned early")

    def test_the_old_job_state_spelling_is_still_honoured(self):
        """Tolerance runs both ways: a name Google may not have finished retiring
        must not hang the wait either."""
        _, raw = self.wait("JOB_STATE_SUCCEEDED")
        self.assertIn("Clinica", raw)


class TestUnknownBatchState(unittest.TestCase):
    """A state this code cannot read must never become a silent three-hour wait.
    That is exactly how the JOB_STATE_* defect stayed invisible."""

    def setUp(self):
        self.original = gemini._get

    def tearDown(self):
        gemini._get = self.original

    def wait(self, state="BATCH_STATE_HIBERNATING", **kw):
        api = FakeApi(state)
        gemini._get = api
        seen = []
        kw.setdefault("interval", 0.001)
        kw.setdefault("timeout_s", 30)
        with self.assertRaises(gemini.GeminiError) as caught:
            gemini.await_batch("api-key", REAL_BATCH["name"],
                               on_update=seen.append, **kw)
        return api, seen, caught.exception

    def test_it_gives_up_long_before_the_deadline(self):
        api, _, _ = self.wait()
        self.assertLessEqual(len(api.polls), gemini.UNKNOWN_STATE_LIMIT,
                             "an unreadable state was polled until the ceiling")

    def test_the_error_names_the_state_nobody_understood(self):
        _, _, error = self.wait()
        self.assertIn("BATCH_STATE_HIBERNATING", str(error))

    def test_the_error_names_the_batch_so_the_money_stays_reachable(self):
        _, _, error = self.wait()
        self.assertIn(REAL_BATCH["name"], str(error))

    def test_the_screen_is_warned_while_it_happens(self):
        _, seen, _ = self.wait()
        self.assertTrue(any("BATCH_STATE_HIBERNATING" in str(line)
                            and "!!" in str(line) for line in seen),
                        "nothing on screen said the state was unreadable: %r" % (seen,))

    def test_an_unreadable_state_keeps_the_batch_resumable(self):
        """It is charged and may well still be running. Treating it as dead would
        make the caller delete the receipt, the only pointer to paid work."""
        _, _, error = self.wait()
        self.assertIsInstance(error, gemini.BatchTimeout)

    def test_a_missing_state_is_unknown_too(self):
        _, _, error = self.wait(state=None)
        self.assertIn("state", str(error).lower())
