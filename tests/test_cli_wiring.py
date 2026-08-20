"""The CLI must honor the environment it documents.

Regression: every CLI entry point resolved the index root with an empty process
environment, so LUPA_INDEXES was silently ignored — a variable the README
promises. Unit tests passed because they called the resolver directly.
"""
import ast
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parent.parent / "lupa" / "cli.py"


class TestIndexRootWiring(unittest.TestCase):
    def test_no_call_site_discards_the_process_environment(self):
        tree = ast.parse(CLI.read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            name = getattr(target, "attr", getattr(target, "id", ""))
            if name != "resolve_index_root" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Dict) and not first.keys:
                offenders.append(node.lineno)
        self.assertEqual(offenders, [],
                         f"resolve_index_root called with an empty dict at lines {offenders}")

    def test_every_call_site_passes_os_environ(self):
        source = CLI.read_text(encoding="utf-8")
        self.assertIn("resolve_index_root(os.environ", source)
        self.assertNotIn("resolve_index_root({}", source)


if __name__ == "__main__":
    unittest.main()
