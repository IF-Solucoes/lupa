"""A Windows console is cp1252. The report symbols are not.

Everything lupa prints on the way in — the preflight report on stdout, the
blocker message on stderr — carries characters cp1252 cannot encode. Nobody
should have to prefix PYTHONIOENCODING=utf-8 to run `lupa index`.

The streams here are real: a TextIOWrapper actually opened as cp1252. A mock
would encode anything and prove nothing.
"""
import io
import os
import sys
import unittest

from lupa import cli
from lupa.preflight import BLOCKER, SYMBOL, diagnose, format_report
from lupa.target import Target


def cp1252_stream():
    """A stand-in for the console a Windows user actually has."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")


class TestWindowsConsole(unittest.TestCase):
    def setUp(self):
        self.real_stdout = sys.stdout
        self.real_stderr = sys.stderr
        sys.stdout = cp1252_stream()
        sys.stderr = cp1252_stream()

    def tearDown(self):
        try:
            sys.stdout = self.real_stdout
        finally:
            sys.stderr = self.real_stderr

    def enter_lupa(self):
        """The real entry point, stopped at argument parsing — nothing is spent.

        Whatever main() does to prepare the output streams has happened by the
        time this returns.
        """
        with self.assertRaises(SystemExit):
            cli.main([])

    def test_the_preflight_report_prints_on_a_cp1252_console(self):
        target = Target("drive", "if-editorial", folder_id="ABC123")
        checks = diagnose(target, env={}, existing_files=set())

        self.enter_lupa()
        print(format_report(checks, target))
        sys.stdout.flush()

        written = sys.stdout.buffer.getvalue().decode("utf-8")
        self.assertIn(SYMBOL[BLOCKER], written)

    def test_the_blocker_exit_message_prints_on_a_cp1252_console(self):
        self.enter_lupa()
        print(f"Fix the items marked {SYMBOL[BLOCKER]} and run again.",
              file=sys.stderr)
        sys.stderr.flush()

        written = sys.stderr.buffer.getvalue().decode("utf-8")
        self.assertIn(SYMBOL[BLOCKER], written)


if __name__ == "__main__":
    unittest.main()


class TestTheMCPServerSpeaksUTF8(unittest.TestCase):
    """For the MCP server the encoding is not cosmetic — it is the protocol.

    Regression, 2026-08-20: `lupa_search` over MCP returned every accented
    character as a replacement byte. `Clínica Veterinária NOROESTE` came back as
    `Clinica Veterin?ria NOROESTE`, `Captação` as `Capta??o`, `Vídeos` as
    `V?deos`. The tool's own description tells the agent that entities are the
    sharpest query available — and then hands it a corrupted vocabulary to
    search with, plus file paths that no longer name a real file.

    `lupa/cli.py` grew prepare_output_streams() when the same cp1252 default
    broke the preflight report. `server/lupa_mcp.py` never got it, and it is the
    one entry point where a mangled character is data, not decoration. The MCP
    stdio transport is specified as UTF-8 in both directions.
    """

    SERVER = None

    def setUp(self):
        from pathlib import Path
        if TestTheMCPServerSpeaksUTF8.SERVER is None:
            root = Path(__file__).resolve().parent.parent
            TestTheMCPServerSpeaksUTF8.SERVER = (
                root / "server" / "lupa_mcp.py").read_text(encoding="utf-8")
        self.source = TestTheMCPServerSpeaksUTF8.SERVER

    def test_it_prepares_its_streams_before_speaking(self):
        self.assertIn("reconfigure", self.source,
                      "the MCP entry point never sets its stream encoding")

    def test_the_running_server_answers_in_utf8(self):
        """The real proof: spawn it with a cp1252 default and read the bytes.

        Asserting on how the reconfigure is written would test the shape of the
        code, not what leaves the process. This starts the entry point exactly
        as an MCP client does, with PYTHONIOENCODING forcing the Windows default
        onto any platform, and reads what comes back off the pipe.

        `tools/list` needs no index and no credentials, and the tool
        descriptions already carry em dashes — non-ASCII that survives or does
        not.
        """
        import json
        import subprocess
        import sys as _sys
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parent.parent
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        done = subprocess.run(
            [_sys.executable, str(root / "server" / "lupa_mcp.py")],
            input=(request + chr(10)).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, env=env)

        raw = done.stdout
        self.assertTrue(raw.strip(), f"server said nothing; stderr: {done.stderr!r}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as broken:
            self.fail(f"the server did not answer in utf-8: {broken}")
        self.assertNotIn("�", text, "a character was lost on the way out")
        self.assertIn("—", text,
                      "the em dash in the tool description did not survive")

    def test_an_accented_response_survives_a_cp1252_default(self):
        """The bug in miniature, and the mechanism matters.

        cp1252 encodes these characters perfectly well, so nothing raises and
        nothing looks wrong on the writing side. The corruption happens at the
        seam: the server emits cp1252 bytes and the MCP client decodes them as
        UTF-8, which the transport says it may.
        """
        import json
        caption = "Clínica Veterinária NOROESTE · Captação de Vídeos"
        payload = json.dumps({"text": caption}, ensure_ascii=False)

        stream = cp1252_stream()
        stream.write(payload)
        stream.flush()
        as_the_client_reads_it = stream.buffer.getvalue().decode("utf-8",
                                                                errors="replace")
        self.assertNotIn(caption, as_the_client_reads_it,
                         "fixture stopped reproducing the corruption")
        self.assertIn("�", as_the_client_reads_it)

        fixed = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")
        fixed.reconfigure(encoding="utf-8")
        fixed.write(payload)
        fixed.flush()
        self.assertIn(caption, fixed.buffer.getvalue().decode("utf-8"))
