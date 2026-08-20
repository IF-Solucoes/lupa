"""MCP server: JSON-RPC dispatch over an index already written."""
import json
import tempfile
import unittest
from pathlib import Path

from lupa.mcp import Server

ITEM = {"id": "1", "file": "bridge.png", "url": "https://example.invalid/1",
        "kind": "design", "medium": "digital", "orientation": "portrait",
        "has_text": True, "caption": "Bridge at night", "tags": ["bridge", "night"],
        "text": "", "labels": []}


class McpTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        collection = self.root / "if-editorial"
        collection.mkdir()
        (collection / "catalog.jsonl").write_text(json.dumps(ITEM, ensure_ascii=False) + "\n")
        (collection / "MANIFEST.json").write_text(
            json.dumps({"collection": "if-editorial", "total": 1}))
        self.server = Server(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, params=None, request_id=1):
        return self.server.dispatch({"jsonrpc": "2.0", "id": request_id,
                                     "method": method, "params": params or {}})


class TestHandshake(McpTestCase):
    def test_initialize_announces_the_server(self):
        result = self.call("initialize")["result"]
        self.assertIn("protocolVersion", result)
        self.assertEqual(result["serverInfo"]["name"], "lupa")

    def test_an_unknown_method_returns_the_standard_error(self):
        self.assertEqual(self.call("tools/nonexistent")["error"]["code"], -32601)

    def test_a_notification_without_an_id_produces_no_response(self):
        self.assertIsNone(self.server.dispatch(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))


class TestTools(McpTestCase):
    def test_it_lists_both_tools(self):
        names = [tool["name"] for tool in self.call("tools/list")["result"]["tools"]]
        self.assertEqual(sorted(names), ["lupa_search", "lupa_status"])

    def test_every_tool_declares_an_input_schema(self):
        for tool in self.call("tools/list")["result"]["tools"]:
            self.assertIn("inputSchema", tool)


class TestSearch(McpTestCase):
    def _search(self, **args):
        result = self.call("tools/call", {"name": "lupa_search", "arguments": args})
        return result["result"]["content"][0]["text"]

    def test_it_finds_by_tag(self):
        self.assertIn("bridge.png", self._search(query="bridge", collection="if-editorial"))

    def test_the_result_carries_the_link(self):
        self.assertIn("https://example.invalid/1",
                      self._search(query="bridge", collection="if-editorial"))

    def test_an_empty_result_explains_itself_instead_of_crashing(self):
        self.assertIn("no results",
                      self._search(query="helicopter", collection="if-editorial").lower())

    def test_an_unknown_collection_lists_the_available_ones(self):
        self.assertIn("if-editorial", self._search(query="x", collection="nope"))

    def test_the_kind_filter_is_honored(self):
        self.assertIn("no results",
                      self._search(query="bridge", collection="if-editorial", kind="photo").lower())

    def test_without_a_collection_it_searches_all_of_them(self):
        self.assertIn("bridge.png", self._search(query="bridge"))


class TestStatus(McpTestCase):
    def test_status_lists_collections_and_totals(self):
        result = self.call("tools/call", {"name": "lupa_status", "arguments": {}})
        text = result["result"]["content"][0]["text"]
        self.assertIn("if-editorial", text)
        self.assertIn("1", text)


if __name__ == "__main__":
    unittest.main()
