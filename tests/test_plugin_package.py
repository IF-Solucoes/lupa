"""The uploadable package: Cowork's Plugins page also accepts a plugin as a file."""
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_plugin_package import build

REPO = Path(__file__).resolve().parent.parent


class TestPluginPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.zip_path = build(REPO, Path(self.tmp.name) / "lupa.zip")
        self.archive = zipfile.ZipFile(self.zip_path)
        self.names = self.archive.namelist()

    def tearDown(self):
        self.archive.close()
        self.tmp.cleanup()

    def test_it_contains_a_single_top_level_folder(self):
        self.assertEqual({name.split("/")[0] for name in self.names}, {"lupa"})

    def test_it_carries_the_manifest_where_the_runtime_looks(self):
        self.assertIn("lupa/.claude-plugin/plugin.json", self.names)

    def test_it_carries_exactly_the_skills_the_repository_declares(self):
        """Asked of the `skills/` tree, never of a list copied into this file.

        A hardcoded list only polices the direction it was written for: it
        catches a skill that stopped being packaged, and says nothing when a
        skill is deleted from the repository — the assertion simply keeps
        naming a folder nobody ships any more. Both directions are compared
        here, so adding or retiring a skill needs no edit in this file and
        cannot silently disagree with what the package carries.
        """
        declared = {path.parent.name
                    for path in (REPO / "skills").glob("*/SKILL.md")}
        packaged = {name.split("/")[2]
                    for name in self.names
                    if name.startswith("lupa/skills/") and name.endswith("/SKILL.md")}
        self.assertEqual(packaged, declared)
        self.assertIn("index", declared)      # the two the plugin is built around
        self.assertIn("search", declared)

    def test_it_carries_the_mcp_declaration_and_its_server(self):
        self.assertIn("lupa/.mcp.json", self.names)
        self.assertIn("lupa/server/lupa_mcp.py", self.names)

    def test_it_carries_the_code_the_server_imports(self):
        self.assertIn("lupa/lupa/mcp.py", self.names)
        self.assertIn("lupa/lupa/search.py", self.names)

    def test_it_leaves_out_tests_and_local_junk(self):
        self.assertFalse([n for n in self.names if "/tests/" in n])
        self.assertFalse([n for n in self.names if "__pycache__" in n])
        self.assertFalse([n for n in self.names if n.endswith(".db")])

    def test_it_stays_well_under_the_upload_limits(self):
        self.assertLess(self.zip_path.stat().st_size, 5_000_000)
        self.assertLess(len(self.names), 5_000)

    def test_the_manifest_is_valid_json_with_a_name(self):
        import json
        manifest = json.loads(self.archive.read("lupa/.claude-plugin/plugin.json"))
        self.assertEqual(manifest["name"], "lupa")


class TestTheCommittedArtefactIsNotStale(unittest.TestCase):
    """`dist/lupa.zip` is versioned on purpose, and nothing rebuilt it for you.

    The build itself always agrees with the repository — it sweeps `skills/`.
    The committed zip does not: it is whatever the last person to run the script
    produced. Retire a skill without rebuilding and the release keeps handing
    Cowork a plugin containing a skill this repository no longer has. Names are
    compared, not bytes, so a rebuild on another machine is not a failure.
    """

    ARTEFACT = REPO / "dist" / "lupa.zip"

    def test_it_ships_exactly_the_skills_the_repository_declares(self):
        if not self.ARTEFACT.exists():
            self.skipTest("no release artefact committed")
        declared = {path.parent.name
                    for path in (REPO / "skills").glob("*/SKILL.md")}
        with zipfile.ZipFile(self.ARTEFACT) as archive:
            shipped = {name.split("/")[2]
                       for name in archive.namelist()
                       if name.startswith("lupa/skills/")
                       and name.endswith("/SKILL.md")}
        self.assertEqual(shipped, declared,
                         "dist/lupa.zip disagrees with skills/ — rebuild it with "
                         "python scripts/build_plugin_package.py")


class TestBuildScriptOnACp1252Console(unittest.TestCase):
    """b5fd6f4 taught the runtime to survive a Windows console; the tool that
    builds the release was left behind, and it prints an arrow too. A build that
    wrote a good zip must not report failure to whoever reads the exit code."""

    SCRIPT = REPO / "scripts" / "build_plugin_package.py"

    def setUp(self):
        # The script writes dist/lupa.zip. The build is byte-deterministic, but
        # the release artefact is versioned, so put it back exactly as found.
        self.artefact = REPO / "dist" / "lupa.zip"
        self.snapshot = self.artefact.read_bytes() if self.artefact.exists() else None

    def tearDown(self):
        if self.snapshot is not None:
            self.artefact.write_bytes(self.snapshot)

    def run_build(self):
        environment = dict(os.environ, PYTHONIOENCODING="cp1252")
        return subprocess.run(
            [sys.executable, str(self.SCRIPT)],
            cwd=str(REPO), env=environment, capture_output=True,
            encoding="utf-8", errors="replace")

    def test_it_exits_zero_when_the_console_cannot_encode_the_arrow(self):
        result = self.run_build()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_it_still_prints_the_upload_instruction(self):
        result = self.run_build()
        self.assertIn("wrote", result.stdout)
        self.assertIn("Plugins", result.stdout)


if __name__ == "__main__":
    unittest.main()
