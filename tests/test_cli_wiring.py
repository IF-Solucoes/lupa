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


class TestSettingsOverride(unittest.TestCase):
    """An agent driving the CLI must be able to point at a settings file
    without touching the process environment."""

    def test_every_command_accepts_an_env_override(self):
        source = CLI.read_text(encoding="utf-8")
        self.assertIn('"--env"', source)

    def test_the_override_is_applied_before_anything_is_read(self):
        import ast
        tree = ast.parse(CLI.read_text(encoding="utf-8"))
        main = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "main")
        body = ast.unparse(main)
        applied = body.index("LUPA_ENV")
        dispatched = body.index("command_index(args)")
        self.assertLess(applied, dispatched,
                        "--env must be applied before a command reads configuration")


class TestOAuthTokenReachesDrive(unittest.TestCase):
    """The value the CLI hands to drive.connect, and the one preflight inspects,
    must be the same and must never be None.

    Regression: `lupa index <drive folder>` on a clean install passed preflight
    and then died with
        TypeError: argument should be a str or an os.PathLike object where
        __fspath__ returns a str, not 'NoneType'
    because LUPA_OAUTH_TOKEN had no default and connect() does
    Path(token_path).expanduser().
    """

    KEYS = ("LUPA_ENV", "LUPA_OAUTH_TOKEN", "LUPA_OAUTH_CLIENT")
    CLIENT = "/existe/oauth.json"

    def setUp(self):
        import os
        import tempfile
        self.saved = {key: os.environ.pop(key, None) for key in self.KEYS}
        handle = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
        handle.write(f"GEMINI_API_KEY=abc\nLUPA_OAUTH_CLIENT={self.CLIENT}\n")
        handle.close()
        self.env_file = handle.name
        os.environ["LUPA_ENV"] = self.env_file

    def tearDown(self):
        import os
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        Path(self.env_file).unlink(missing_ok=True)

    def target(self):
        from lupa.target import Target
        return Target("drive", "if-editorial", folder_id="ABC123")

    def run_build_source(self):
        """Returns (env, token path actually delivered to drive.connect)."""
        import lupa.drive
        from lupa import cli, config

        seen = {}

        def fake_connect(client_secret, token_path, with_credentials=False):
            seen["client"] = client_secret
            seen["token"] = token_path
            return (None, None) if with_credentials else None

        original = lupa.drive.connect
        lupa.drive.connect = fake_connect
        try:
            env = config.environment()
            cli.build_source(self.target(), env, cache="/tmp/lupa-cache")
        finally:
            lupa.drive.connect = original
        return env, seen["token"]

    def test_the_token_path_delivered_to_connect_is_not_none(self):
        _, token = self.run_build_source()
        self.assertIsNotNone(
            token, "connect() received None and would raise TypeError on Path()")

    def test_the_delivered_path_survives_the_call_that_used_to_crash(self):
        _, token = self.run_build_source()
        self.assertTrue(str(Path(token).expanduser()))

    def test_preflight_and_execution_agree_on_the_token_path(self):
        from lupa.preflight import OK, diagnose

        env, token = self.run_build_source()
        checks = diagnose(self.target(), env,
                          existing_files={self.CLIENT, str(token)})
        sign_in = [check for check in checks if check.name == "Google sign-in"][0]
        self.assertEqual(
            sign_in.status, OK,
            "preflight inspected a different token path than the one execution uses")


class TestCosmeticProbeNeverLogsIn(unittest.TestCase):
    """The folder-name probe in command_index is cosmetic: it may not sign in.

    Behavioral, not AST-based: the other classes in this file read cli.py as
    text, but "does a browser open" is only answerable by running the command.

    Regression: once LUPA_OAUTH_TOKEN gained a default, connect() stopped dying
    with TypeError inside the probe's try/except and started walking into
    InstalledAppFlow.run_local_server(port=0) — which opens a browser and blocks,
    BEFORE the preflight report explains why, and even under --dry-run.
    """

    KEYS = ("LUPA_ENV", "LUPA_CONFIG", "LUPA_INDEXES", "LUPA_OAUTH_TOKEN",
            "LUPA_OAUTH_CLIENT", "GEMINI_API_KEY", "LUPA_STATE_DIR")
    FOLDER_ID = "15fvulcdmebag7t2tm"

    def setUp(self):
        import os
        import tempfile

        self.saved = {key: os.environ.pop(key, None) for key in self.KEYS}
        self.home = Path(tempfile.mkdtemp(prefix="lupa-probe-"))

        self.client = self.home / "oauth_client.json"
        self.client.write_text('{"installed": {"client_id": "x"}}', encoding="utf-8")
        self.token = self.home / "oauth_token.json"   # deliberately absent

        self.env_file = self.home / "lupa.env"
        # No GEMINI_API_KEY on purpose: preflight blocks and the run stops right
        # after the report, which is all this test needs to observe.
        self.env_file.write_text(
            f"LUPA_OAUTH_CLIENT={self.client}\nLUPA_OAUTH_TOKEN={self.token}\n",
            encoding="utf-8")

        os.environ["LUPA_ENV"] = str(self.env_file)
        os.environ["LUPA_CONFIG"] = str(self.home / "collections.json")
        os.environ["LUPA_INDEXES"] = str(self.home / "indexes")

    def tearDown(self):
        import os
        import shutil
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.home, ignore_errors=True)

    def interactive_spy(self):
        """Stands in for the real InstalledAppFlow, the thing that opens a browser.

        Recording happens at from_client_secrets_file — the first step of the
        interactive flow — then it raises, so run_local_server can never block.
        """
        reached = []

        class SpyFlow:
            @staticmethod
            def from_client_secrets_file(path, scopes):
                reached.append(Path(path))
                raise RuntimeError("a browser would open here")

        return reached, SpyFlow

    def run_index(self, argv):
        """Runs the CLI and returns everything it printed."""
        import contextlib
        import io

        from lupa import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                cli.main(argv)
        return out.getvalue()

    def test_the_spy_really_detects_the_interactive_flow(self):
        """Anti-tautology: with no stored session, real connect() DOES reach it."""
        import google_auth_oauthlib.flow as flow_module

        from lupa.drive import connect

        reached, spy = self.interactive_spy()
        original = flow_module.InstalledAppFlow
        flow_module.InstalledAppFlow = spy
        try:
            with self.assertRaises(RuntimeError):
                connect(str(self.client), str(self.token))
        finally:
            flow_module.InstalledAppFlow = original

        self.assertEqual([Path(self.client)], reached,
                         "the spy is not wired to the interactive flow")

    def test_probe_does_not_sign_in_when_no_session_is_stored(self):
        import google_auth_oauthlib.flow as flow_module

        reached, spy = self.interactive_spy()
        original = flow_module.InstalledAppFlow
        flow_module.InstalledAppFlow = spy
        try:
            printed = self.run_index(["index", self.FOLDER_ID])
        finally:
            flow_module.InstalledAppFlow = original

        self.assertIn("Preflight", printed,
                      "the report must be printed; the run stopped somewhere else")
        self.assertEqual(
            [], reached,
            "the cosmetic probe walked into the interactive login: a browser "
            "would have opened before the preflight report was printed")

    def test_probe_does_not_sign_in_under_dry_run_either(self):
        import google_auth_oauthlib.flow as flow_module

        reached, spy = self.interactive_spy()
        original = flow_module.InstalledAppFlow
        flow_module.InstalledAppFlow = spy
        try:
            self.run_index(["index", self.FOLDER_ID, "--dry-run"])
        finally:
            flow_module.InstalledAppFlow = original

        self.assertEqual([], reached,
                         "--dry-run must not open a browser")

    def test_probe_still_names_the_collection_when_a_session_is_stored(self):
        """The other side: with a stored session the pretty name still wins."""
        import lupa.drive

        self.token.write_text("{}", encoding="utf-8")
        seen = {}

        def fake_connect(client_secret, token_path, with_credentials=False):
            seen["client"] = Path(client_secret)
            seen["token"] = Path(token_path)
            return "service-double"

        original_connect = lupa.drive.connect
        original_name = lupa.drive.folder_name
        lupa.drive.connect = fake_connect
        lupa.drive.folder_name = lambda service, folder_id: "Referencias Editorial"
        try:
            printed = self.run_index(["index", self.FOLDER_ID])
        finally:
            lupa.drive.connect = original_connect
            lupa.drive.folder_name = original_name

        self.assertEqual(Path(self.client), seen.get("client"),
                         "the probe did not run with a stored session")
        self.assertEqual(Path(self.token), seen.get("token"))
        self.assertIn("referencias-editorial", printed,
                      "the Drive name stopped reaching the collection name")
