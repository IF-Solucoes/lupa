"""Building Gemini requests and reading batch results."""
import base64
import json
import unittest
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


if __name__ == "__main__":
    unittest.main()
