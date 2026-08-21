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


class TestResumeBatchIsDeclaredForBothVerbs(unittest.TestCase):
    """A batch already paid for can only be resumed if the flag exists on the
    verb the user actually types — and `index` and `update` are the same door."""

    def test_the_flag_is_declared(self):
        source = CLI.read_text(encoding="utf-8")
        self.assertIn('"--resume-batch"', source)

    def test_it_is_declared_in_the_loop_shared_by_index_and_update(self):
        tree = ast.parse(CLI.read_text(encoding="utf-8"))
        loops = [node for node in ast.walk(tree)
                 if isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple)
                 and [getattr(element, "value", None) for element in node.iter.elts]
                 == ["index", "update"]]
        self.assertTrue(loops, "the shared verb loop disappeared from cli.py")
        self.assertIn("--resume-batch", ast.unparse(loops[0]),
                      "--resume-batch must reach `update` too, not only `index`")


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


class IndexCommandHarness(unittest.TestCase):
    """The rig the behavioral `lupa index` tests below share. It holds no test.

    An exit code, a printed line and the order of the two are only observable by
    running the command, so those tests drive `cli.main` for real and stub only
    what would reach the network or a credential.
    """

    KEYS = ("LUPA_ENV", "LUPA_CONFIG", "LUPA_INDEXES", "LUPA_STATE_DIR",
            "GEMINI_API_KEY", "LUPA_MODEL", "LUPA_BATCH", "LUPA_LANG",
            "LUPA_CONFIRM_ABOVE", "LUPA_OAUTH_CLIENT", "LUPA_OAUTH_TOKEN")

    class FakeSource:
        """Two images, no network, no credentials."""

        def list(self):
            return [{"id": name, "file": f"{name}.png", "hash": name,
                     "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
                     "url": f"https://example.invalid/{name}",
                     "trashed": False, "size": 100}
                    for name in ("a", "b")]

        def fetch(self, file_id):
            return b"bytes", "image/png"

    def setUp(self):
        import os
        import tempfile

        self.saved = {key: os.environ.pop(key, None) for key in self.KEYS}
        self.home = Path(tempfile.mkdtemp(prefix="lupa-exit-"))
        self.collection = self.home / "photos"
        self.collection.mkdir()

        env_file = self.home / "lupa.env"
        env_file.write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
        os.environ["LUPA_ENV"] = str(env_file)
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

    def run_index(self, describe, *extra):
        """Runs `lupa index` over the fake source. Returns (exit code, output)."""
        import contextlib
        import io

        from lupa import cli

        source = self.FakeSource()
        original_source, original_describer = cli.build_source, cli.make_describer
        cli.build_source = lambda *a, **k: (source, None)
        cli.make_describer = lambda *a, **k: describe

        # Per image by default, so `describe` is the stub above and no batch is
        # ever built. A test asking for --resume-batch is asking for the batch
        # path, and the CLI refuses the two flags together on purpose.
        base = ["--yes", "--no-push", "--no-contact-sheets"]
        if "--resume-batch" not in extra:
            base.append("--no-batch")

        printed, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
                try:
                    cli.main(["index", str(self.collection), *base, *extra])
                except SystemExit as stop:
                    if isinstance(stop.code, int) or stop.code is None:
                        code = stop.code or 0
                    else:
                        # sys.exit("message") does not print anything itself: the
                        # interpreter does, on the way out, and catching the
                        # exception here is what would swallow it. Refusals are
                        # made of that message, so it goes into the capture.
                        code = 1
                        print(stop.code)
        finally:
            cli.build_source, cli.make_describer = original_source, original_describer
        return code, printed.getvalue()


class TestTheExitCodeTellsTheTruth(IndexCommandHarness):
    """A failed run must be detectable by a script, not only by a careful reader.

    Regression, 2026-08-20: 875 of 875 images failed with the same HTTP 404 and
    `lupa index` printed "Done." on the first line, "875 images failed" on the
    last, and exited 0 — so `lupa index && lupa publish` published nothing.

    Behavioral on purpose: an exit code is only observable by running the command.
    """

    RETIRED = ("HTTP 404: gemini-2.5-flash-lite is no longer available; "
               "use gemini-3.5-flash-lite instead")

    def working_model(self):
        def describe(item, image, mime):
            return {"caption": "ok", "tags": ["t"]}
        return describe

    def broken_model(self, only=None):
        def describe(item, image, mime):
            if only is None or item["id"] == only:
                raise RuntimeError(self.RETIRED)
            return {"caption": "ok", "tags": ["t"]}
        return describe

    def test_a_total_failure_does_not_exit_zero(self):
        code, _ = self.run_index(self.broken_model())
        self.assertNotEqual(0, code)

    def test_a_single_failure_is_enough_to_change_the_exit_code(self):
        code, _ = self.run_index(self.broken_model(only="b"))
        self.assertNotEqual(0, code)

    def test_a_total_failure_never_says_done(self):
        _, printed = self.run_index(self.broken_model())
        self.assertNotIn("Done.", printed)

    def test_a_total_failure_speaks_before_it_reports_anything_else(self):
        _, printed = self.run_index(self.broken_model())
        lines = [line for line in printed.splitlines() if line.strip()]
        verdict = next(i for i, line in enumerate(lines) if "failed" in line.lower())
        location = next(i for i, line in enumerate(lines) if "local index:" in line)
        self.assertLess(verdict, location,
                        "the failure must be read before anything else in the report")

    def test_a_total_failure_names_the_error_that_repeated(self):
        _, printed = self.run_index(self.broken_model())
        self.assertIn("no longer available", printed)

    def test_nothing_that_failed_is_counted_as_added(self):
        """The plan may promise 2; the result must report the 1 that happened."""
        _, printed = self.run_index(self.broken_model(only="b"))
        done = next(line for line in printed.splitlines() if line.startswith("Done."))
        self.assertIn("+1 added", done)
        self.assertNotIn("+2 added", done)
        self.assertIn("!1 failed", done)

    def test_a_healthy_run_still_exits_zero_and_still_says_done(self):
        code, printed = self.run_index(self.working_model())
        self.assertEqual(0, code)
        self.assertIn("Done. +2 added · ~0 changed · -0 removed · =0 unchanged",
                      printed)

    def test_a_dry_run_still_exits_zero(self):
        code, printed = self.run_index(self.broken_model(), "--dry-run")
        self.assertEqual(0, code)
        self.assertIn("--dry-run", printed)


class TestSearchAcceptsTheTextFilter(unittest.TestCase):
    """`has_text` is a filter everywhere except the CLI, and that gap is silent.

    The MCP has accepted it since the first version and the skill's filter table
    lists it, so an agent that falls back to the command line runs
    `--has-text false` and gets `unrecognized arguments`. The value also has to
    arrive as a real boolean: the catalog stores `true`/`false` as JSON booleans
    and the filter is an equality test, so the string "false" would match no
    image at all — a wrong answer instead of an error.
    """

    def search(self, argv):
        """Runs `lupa search` with the Server replaced by a spy. Nothing is read
        from disk and no index is touched: only the filter dict is captured."""
        from lupa import cli

        captured = {}

        class Spy:
            def __init__(self, _root):
                pass

            def tool_search(self, args):
                captured.update(args)
                return ""

        original = cli.Server
        cli.Server = Spy
        try:
            cli.main(argv)
        finally:
            cli.Server = original
        return captured

    def test_false_reaches_the_filter_as_a_boolean(self):
        filters = self.search(["search", "banner", "--has-text", "false"])
        self.assertIn("has_text", filters)
        self.assertIs(filters["has_text"], False)

    def test_true_reaches_the_filter_as_a_boolean(self):
        self.assertIs(self.search(
            ["search", "banner", "--has-text", "true"])["has_text"], True)

    def test_the_underscore_spelling_is_accepted_too(self):
        """`has_text` is how the field is spelled in the catalog, in the schema
        and in the MCP; whoever copies it must not hit a parser error."""
        self.assertIs(self.search(
            ["search", "banner", "--has_text", "true"])["has_text"], True)

    def test_nothing_is_filtered_when_the_flag_is_absent(self):
        self.assertNotIn("has_text", self.search(["search", "banner"]))


class TestTheScreenClosesTheCycle(unittest.TestCase):
    """The run prints an estimate before spending; it must come back and say
    whether the estimate was right.

    Until now the user saw "estimated cost: under US$ 0.01" and never learned
    what the API had actually counted — which is exactly why the token budgets
    in caption.py were never confronted with the bill.
    """

    KEYS = ("LUPA_ENV", "LUPA_CONFIG", "LUPA_INDEXES", "LUPA_STATE_DIR",
            "GEMINI_API_KEY", "LUPA_MODEL", "LUPA_BATCH", "LUPA_LANG",
            "LUPA_CONFIRM_ABOVE", "LUPA_OAUTH_CLIENT", "LUPA_OAUTH_TOKEN")

    class FakeSource:
        def list(self):
            return [{"id": name, "file": f"{name}.png", "hash": name,
                     "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
                     "url": f"https://example.invalid/{name}",
                     "trashed": False, "size": 100}
                    for name in ("a", "b")]

        def fetch(self, file_id):
            return b"bytes", "image/png"

    def setUp(self):
        import os
        import tempfile

        self.saved = {key: os.environ.pop(key, None) for key in self.KEYS}
        self.home = Path(tempfile.mkdtemp(prefix="lupa-usage-"))
        self.collection = self.home / "photos"
        self.collection.mkdir()

        env_file = self.home / "lupa.env"
        env_file.write_text("GEMINI_API_KEY=abc\n", encoding="utf-8")
        os.environ["LUPA_ENV"] = str(env_file)
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

    def run_index(self, usage=(588, 103)):
        """Runs `lupa index` with a describer that reports `usage` per image."""
        import contextlib
        import io

        from lupa import cli

        def make_describer(*args, on_usage=None, **kw):
            def describe(item, image, mime):
                if on_usage:
                    on_usage(usage)
                return {"caption": "ok", "tags": ["t"]}
            return describe

        source = self.FakeSource()
        originals = cli.build_source, cli.make_describer
        cli.build_source = lambda *a, **k: (source, None)
        cli.make_describer = make_describer

        printed, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
                try:
                    cli.main(["index", str(self.collection), "--yes", "--no-push",
                              "--no-batch", "--no-contact-sheets"])
                except SystemExit as stop:
                    code = stop.code if isinstance(stop.code, int) else 1
        finally:
            cli.build_source, cli.make_describer = originals
        return code, printed.getvalue()

    def index_dir(self):
        return self.home / "indexes" / "photos"

    def test_the_screen_reports_the_tokens_the_api_counted(self):
        code, printed = self.run_index()
        self.assertEqual(0, code)
        self.assertIn("1176", printed)   # 2 images × 588 input
        self.assertIn("206", printed)    # 2 images × 103 output

    def test_the_screen_puts_the_budget_next_to_the_measurement(self):
        _, printed = self.run_index()
        from lupa.caption import INPUT_TOKENS_PER_IMAGE
        self.assertIn(str(INPUT_TOKENS_PER_IMAGE), printed)
        self.assertIn("1600", printed)   # the measured budget, spelled out
        self.assertIn("588", printed)    # what was really counted, per image

    def test_the_screen_compares_the_estimate_with_the_money_counted(self):
        _, printed = self.run_index()
        lowered = printed.lower()
        self.assertIn("estimated", lowered)
        self.assertIn("counted", lowered)

    def test_a_model_that_reports_nothing_does_not_print_a_free_run(self):
        _, printed = self.run_index(usage=None)
        self.assertIn("unknown", printed.lower())

    def test_a_run_that_measured_nothing_still_exits_zero(self):
        code, _ = self.run_index(usage=None)
        self.assertEqual(0, code)

    def test_the_measurement_survives_on_disk_in_the_run_report(self):
        self.run_index()
        reports = list((self.index_dir() / "runs").glob("*.md"))
        self.assertTrue(reports, "no run report was written")
        self.assertIn("1176", reports[0].read_text(encoding="utf-8"))

    def test_the_measurement_is_the_last_word_of_the_run(self):
        """It closes the cycle, so it closes the output. A bookkeeping line
        printed after it would bury the one number the user came back for."""
        _, printed = self.run_index()
        lines = [line for line in printed.splitlines() if line.strip()]
        counted = max(i for i, line in enumerate(lines) if "counted" in line.lower())
        saved = max(i for i, line in enumerate(lines) if "saved as" in line)
        self.assertGreater(counted, saved)


class TestRebuildReallyRebuilds(IndexCommandHarness):
    """The reproduction, from the command line, of what `--rebuild` did instead.

    Regression, 2026-08-20, against a real collection of 15 images already
    indexed and unchanged:

        $ python -m lupa index <url> --rebuild --confirm "2-kit-marca" --yes
          ✓ index state: already exists — this is an update, only changes cost
        Plan for this run
          +0 added · ~0 changed · -0 removed · =15 unchanged
          images to describe: 0
        Nothing changed since the last run. Nothing to do, nothing to pay.
        exit 0

    A backup was taken, nothing was described, the index came out byte for byte
    what it was — and the exit code said it had worked. `skills/index/SKILL.md`
    documents this command as the way to pick up a schema change; the schema had
    just gained `entities`.
    """

    def model(self, caption="ok"):
        calls = []

        def describe(item, image, mime):
            calls.append(item["id"])
            return {"caption": caption, "tags": ["t"]}

        describe.calls = calls
        return describe

    def already_indexed(self):
        code, _ = self.run_index(self.model("first pass"))
        self.assertEqual(0, code, "the setup run itself failed")

    def rebuild(self, describe):
        return self.run_index(describe, "--rebuild", "--confirm", "photos")

    def test_every_image_is_described_again(self):
        self.already_indexed()
        again = self.model("rebuilt")
        code, _ = self.rebuild(again)
        self.assertEqual(0, code)
        self.assertEqual(["a", "b"], sorted(again.calls))

    def test_it_never_claims_nothing_changed(self):
        self.already_indexed()
        _, printed = self.rebuild(self.model("rebuilt"))
        self.assertNotIn("Nothing changed since the last run", printed)

    def test_the_plan_on_screen_counts_the_whole_collection(self):
        self.already_indexed()
        _, printed = self.rebuild(self.model("rebuilt"))
        self.assertIn("images to describe: 2", printed)

    def test_the_price_on_screen_is_not_zero(self):
        """It is the number a person reads before authorizing a whole acervo."""
        self.already_indexed()
        _, printed = self.rebuild(self.model("rebuilt"))
        estimate = next(line for line in printed.splitlines()
                        if "estimated cost" in line)
        self.assertNotIn("US$ 0.00", estimate)

    def test_the_preflight_does_not_call_it_an_update(self):
        self.already_indexed()
        _, printed = self.rebuild(self.model("rebuilt"))
        state = next(line for line in printed.splitlines() if "index state" in line)
        self.assertNotIn("only changes cost anything", state)

    def test_the_new_descriptions_are_the_ones_on_disk(self):
        self.already_indexed()
        self.rebuild(self.model("rebuilt"))
        catalog = (self.home / "indexes" / "photos" / "catalog.jsonl").read_text(
            encoding="utf-8")
        self.assertIn("rebuilt", catalog)
        self.assertNotIn("first pass", catalog)

    def test_the_previous_index_is_kept_in_the_backup(self):
        self.already_indexed()
        self.rebuild(self.model("rebuilt"))
        backups = list((self.home / "indexes" / "photos" / ".backup").glob("*"))
        self.assertEqual(1, len(backups))
        kept = (backups[0] / "catalog.jsonl").read_text(encoding="utf-8")
        self.assertIn("first pass", kept)

    def test_without_rebuild_the_second_run_still_costs_nothing(self):
        """The promise of the tool, guarded on the same path."""
        self.already_indexed()
        again = self.model("must not happen")
        code, printed = self.run_index(again)
        self.assertEqual(0, code)
        self.assertEqual([], again.calls)
        self.assertIn("Nothing changed since the last run", printed)


class TestRebuildAndTheOtherRecoveryFlags(IndexCommandHarness):
    """`--rebuild` next to the two flags that also decide what gets re-described.

    Neither may end in a surprise: `--retry-failed` edits MANIFEST.json in place,
    and it does so BEFORE the pipeline takes its backup — under a rebuild that
    would quietly alter the copy the backup exists to preserve, for no gain at
    all, since a rebuild re-describes every image anyway.
    """

    def model(self, caption="ok"):
        def describe(item, image, mime):
            return {"caption": caption, "tags": ["t"]}
        return describe

    def index_dir(self):
        return self.home / "indexes" / "photos"

    def test_retry_failed_under_a_rebuild_says_it_is_doing_nothing(self):
        self.run_index(self.model("first pass"))
        _, printed = self.run_index(self.model("rebuilt"), "--rebuild",
                                    "--confirm", "photos", "--retry-failed")
        self.assertIn("--retry-failed", printed)
        self.assertIn("--rebuild", printed)

    def test_retry_failed_under_a_rebuild_does_not_touch_the_manifest(self):
        import json

        self.run_index(self.model("first pass"))
        manifest = self.index_dir() / "MANIFEST.json"
        (self.index_dir() / "runs").mkdir(exist_ok=True)
        (self.index_dir() / "runs" / "2026-08-20T10-00-00.errors.jsonl").write_text(
            json.dumps({"id": "a", "file": "a.png", "error": "boom"}) + "\n",
            encoding="utf-8")
        before = manifest.read_text(encoding="utf-8")

        self.run_index(self.model("rebuilt"), "--rebuild", "--confirm", "photos",
                       "--retry-failed")
        backups = list((self.index_dir() / ".backup").glob("*"))
        kept = (backups[0] / "MANIFEST.json").read_text(encoding="utf-8")
        self.assertEqual(before, kept,
                         "the backup must hold the manifest exactly as it was")

    def test_a_rebuild_still_refuses_to_run_over_a_batch_already_paid_for(self):
        from lupa import gemini, inflight

        self.run_index(self.model("first pass"))
        inflight.remember(self.index_dir(), "batches/abc", "photos",
                          gemini.DEFAULT_MODEL, ["a", "b"])
        code, printed = self.run_index(self.model("rebuilt"), "--rebuild",
                                       "--confirm", "photos")
        self.assertNotEqual(0, code)
        self.assertIn("ALREADY CHARGED", printed)

    def test_resuming_a_batch_that_covered_less_than_the_rebuild_is_refused(self):
        """The receipt's fingerprint is the id set that was paid for. A rebuild
        describes every image, so a batch submitted for a subset cannot serve it
        — and the answers come back keyed by id, so accepting would write a
        silently incomplete index."""
        from lupa import gemini, inflight

        self.run_index(self.model("first pass"))
        inflight.remember(self.index_dir(), "batches/abc", "photos",
                          gemini.DEFAULT_MODEL, ["a"])
        code, printed = self.run_index(self.model("rebuilt"), "--rebuild",
                                       "--confirm", "photos", "--resume-batch")
        self.assertNotEqual(0, code)
        self.assertIn("changed since that batch was submitted", printed)


class TestAFailedRunDoesNotPublish(IndexCommandHarness):
    """Publishing is how a run leaves the machine. A failed run must not.

    Regression, 2026-08-20: `command_index` calls `publish()` and only then
    raises SystemExit(1). The exit code was fixed; the order was not. So a run
    where every image failed still pushed the index to the client's Drive —
    overwriting a good index with an empty one — and only afterwards admitted
    it had failed. The exit code is read by the next command; publish already
    happened by then.
    """

    def working_model(self):
        def describe(item, image, mime):
            return {"caption": "ok", "tags": ["t"]}
        return describe

    def broken_model(self, only=None):
        def describe(item, image, mime):
            if only is None or item["id"] == only:
                raise RuntimeError("HTTP 404: model is no longer available")
            return {"caption": "ok", "tags": ["t"]}
        return describe

    def run_index_pushing(self, describe):
        """Runs `lupa index` with a Drive service attached and push enabled.

        Returns (exit code, number of publish calls).
        """
        import contextlib
        import io

        import lupa.publish
        from lupa import cli

        source = self.FakeSource()
        calls = []
        original_source = cli.build_source
        original_describer = cli.make_describer
        original_publish = lupa.publish.publish
        cli.build_source = lambda *a, **k: (source, object())
        cli.make_describer = lambda *a, **k: describe
        lupa.publish.publish = lambda *a, **k: calls.append(a)

        printed, code = io.StringIO(), 0
        try:
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
                try:
                    cli.main(["index", str(self.collection), "--yes",
                              "--no-contact-sheets", "--no-batch"])
                except SystemExit as stop:
                    code = stop.code or 0 if isinstance(stop.code, (int, type(None))) else 1
        finally:
            cli.build_source, cli.make_describer = original_source, original_describer
            lupa.publish.publish = original_publish
        return code, len(calls)

    def test_a_healthy_run_still_publishes(self):
        """Anti-tautology: proves the stub sees the call it is meant to count."""
        code, published = self.run_index_pushing(self.working_model())
        self.assertEqual(0, code)
        self.assertEqual(1, published, "a good run stopped publishing")

    def test_a_total_failure_publishes_nothing(self):
        code, published = self.run_index_pushing(self.broken_model())
        self.assertNotEqual(0, code)
        self.assertEqual(0, published,
                         "a run where every image failed pushed itself to Drive")

    def test_a_single_failure_is_enough_to_hold_the_publish_back(self):
        code, published = self.run_index_pushing(self.broken_model(only="b"))
        self.assertNotEqual(0, code)
        self.assertEqual(0, published,
                         "a partial index was published as if it were complete")


class TestThePriceQuotedIsThePriceOfThisRun(IndexCommandHarness):
    """The plan quotes a cost. It must be the cost of the run about to happen.

    Regression, 2026-08-20: the preview that produces "estimated cost" was
    called without `batch` and without `model`, so it always quoted batch — half
    price — for the default model. Two ways to be wrong at once: `--no-batch`
    was quoted at half of what it charges, and `LUPA_MODEL` pointing at a
    pricier model was quoted at the cheap model's price. The preflight block
    above it had the right numbers, which made the disagreement invisible: two
    prices on one screen, and the wrong one is the one with the total on it.

    Behavioral: the printed line is the only place the two meet.
    """

    class FortyImages:
        """Enough images that the difference survives format_cost's rounding."""

        def list(self):
            return [{"id": f"i{n}", "file": f"i{n}.png", "hash": f"h{n}",
                     "mime": "image/png", "w": 1080, "h": 1350, "exif": {},
                     "url": f"https://example.invalid/i{n}",
                     "trashed": False, "size": 100}
                    for n in range(40)]

        def fetch(self, file_id):
            return b"bytes", "image/png"

    COUNT = 40

    def quoted_cost(self, *extra):
        """Runs the preflight only (--dry-run) and returns the cost line."""
        import contextlib
        import io

        from lupa import cli

        original_source = cli.build_source
        cli.build_source = lambda *a, **k: (self.FortyImages(), None)
        printed = io.StringIO()
        try:
            with contextlib.redirect_stdout(printed), contextlib.redirect_stderr(printed):
                try:
                    cli.main(["index", str(self.collection), "--yes", "--dry-run",
                              "--no-contact-sheets", *extra])
                except SystemExit:
                    pass
        finally:
            cli.build_source = original_source
        line = next(l for l in printed.getvalue().splitlines()
                    if "estimated cost" in l)
        return line

    def expected(self, batch, model=None):
        from lupa import caption, gemini
        return caption.format_cost(
            caption.estimate_cost(self.COUNT, batch=batch,
                                  model=model or gemini.DEFAULT_MODEL))

    def test_batch_is_still_quoted_at_half_price(self):
        """Anti-tautology: the default path must keep quoting the batch price."""
        self.assertIn(self.expected(batch=True), self.quoted_cost())

    def test_no_batch_is_quoted_at_full_price(self):
        cheap = self.expected(batch=True)
        real = self.expected(batch=False)
        self.assertNotEqual(cheap, real, "the fixture stopped telling the two apart")
        self.assertIn(real, self.quoted_cost("--no-batch"))

    def test_the_configured_model_is_the_model_priced(self):
        import os
        os.environ["LUPA_MODEL"] = "gemini-2.5-flash-lite"
        expected = self.expected(batch=False, model="gemini-2.5-flash-lite")
        default = self.expected(batch=False)
        self.assertNotEqual(expected, default,
                            "the fixture stopped telling the two models apart")
        self.assertIn(expected, self.quoted_cost("--no-batch"))
