"""A Windows console is cp1252. The report symbols are not.

Everything lupa prints on the way in — the preflight report on stdout, the
blocker message on stderr — carries characters cp1252 cannot encode. Nobody
should have to prefix PYTHONIOENCODING=utf-8 to run `lupa index`.

The streams here are real: a TextIOWrapper actually opened as cp1252. A mock
would encode anything and prove nothing.
"""
import io
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
