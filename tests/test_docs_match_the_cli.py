"""The skills must describe the CLI that exists, not the one we remember.

Every SKILL.md under `skills/` is an instruction sheet an agent will follow
literally. When it names a flag the parser does not have, the agent runs a
command that dies; when it omits a flag that changes what leaves the user's
machine, the agent never offers the user that choice. Both are silent, and both
were found by hand in a review — which is exactly the work this file exists to
stop repeating.

The reference is always the real `argparse` parser built by `lupa.cli.main`,
never a list copied into this file. Nothing here runs a command, spends money,
touches `~/.lupa/`, or reaches the network: the parser is captured mid-build and
the skills are read as text.

Extending this file:

  * a new flag whose absence from the docs would be a privacy or money problem
    goes in CONSEQUENTIAL_FLAGS below;
  * a documented error message that is generated rather than written verbatim
    goes in ERRORS_NOT_IN_THE_SOURCE below, with the reason;
  * a new skill needs no registration — every `skills/*/SKILL.md` is swept.
"""
import argparse
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = sorted((REPO / "skills").glob("*/SKILL.md"))
SOURCES = sorted((REPO / "lupa").glob("*.py"))

# Flags that change what leaves the user's machine, or what it costs. A skill is
# free to leave ordinary flags out — it curates, it is not `--help` — but not
# these: an agent that never learned them cannot offer the user the choice.
# key: the flag. value: the skill that has to mention it.
CONSEQUENTIAL_FLAGS = {
    "--no-push": "index",     # the only way to keep the index off Google Drive
}

# Error text quoted in a skill that the source cannot contain verbatim (built at
# runtime, translated, coming from a library). Each entry needs a reason.
ERRORS_NOT_IN_THE_SOURCE = {
    # ("index", "some message"): "why it cannot be found literally",
}

LONG_FLAG = re.compile(r"--[A-Za-z0-9][A-Za-z0-9_-]*")
PYTHON3 = re.compile(r"\bpython3\b")
MODULE_CALL = re.compile(r"\bpython[0-9.]*\s+-m\s+lupa\s+([a-z][a-z-]*)")
BACKTICKED = re.compile(r"`([^`]+)`")


def read(path):
    return path.read_text(encoding="utf-8")


def numbered(path):
    """(lineno, line) pairs, 1-based, so a failure can name the line."""
    return list(enumerate(read(path).splitlines(), start=1))


class _ParserCaptured(Exception):
    """Carries the parser out of `main` before it can parse anything."""

    def __init__(self, parser):
        super().__init__("captured")
        self.parser = parser


def _capture(self, *args, **kwargs):
    raise _ParserCaptured(self)


def real_parser():
    """The parser `lupa.cli.main` actually builds — asked, not reimplemented.

    `main` builds it locally and calls `parse_args` at the end, so the only way
    in without a subprocess is to interrupt it exactly there. No command runs:
    the exception is raised before dispatch.
    """
    from lupa import cli

    original_parse = argparse.ArgumentParser.parse_args
    original_streams = cli.prepare_output_streams
    argparse.ArgumentParser.parse_args = _capture
    cli.prepare_output_streams = lambda: None   # leave the runner's stdout alone
    try:
        cli.main([])
    except _ParserCaptured as captured:
        return captured.parser
    finally:
        argparse.ArgumentParser.parse_args = original_parse
        cli.prepare_output_streams = original_streams
    raise AssertionError("lupa.cli.main did not reach parse_args")


def subcommands(parser):
    """{name: subparser} for every verb the CLI accepts."""
    found = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            found.update(action.choices)
    return found


def long_flags_of(parser):
    return {option
            for action in parser._actions
            for option in action.option_strings
            if option.startswith("--")}


def table_rows(lines, header_cell):
    """Rows of the markdown table whose first header cell matches `header_cell`.

    Returns (lineno, [cells]). A line that is not a table row closes the table.
    """
    rows, inside = [], False
    for lineno, line in lines:
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            inside = False
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not inside:
            if cells and cells[0].strip("` ").lower() == header_cell.lower():
                inside = True
            continue
        if set(cells[0]) <= set("-: "):        # the |---|---| separator
            continue
        rows.append((lineno, cells))
    return rows


class TestDocumentedCommands(unittest.TestCase):
    def setUp(self):
        self.parser = real_parser()

    def test_no_skill_tells_anyone_to_run_python3(self):
        """`python3` is not a command on Windows.

        It resolves to the Microsoft Store stub, which prints an advertisement,
        runs nothing, and exits 0 — so the agent reads success and reports an
        index that was never built. `python` is the portable spelling.
        """
        offenders = [f"{path.parent.name}/SKILL.md:{lineno}: {line.strip()}"
                     for path in SKILLS
                     for lineno, line in numbered(path)
                     if PYTHON3.search(line)]
        self.assertEqual(offenders, [], "\n" + "\n".join(
            ["`python3` does not exist on Windows: it hits the Microsoft Store "
             "stub, runs nothing and still exits 0, so the failure is silent and "
             "the agent reports success. Write `python` instead."] + offenders))

    def test_every_documented_subcommand_exists(self):
        verbs = set(subcommands(self.parser))
        offenders = [f"{path.parent.name}/SKILL.md:{lineno}: lupa {verb}"
                     for path in SKILLS
                     for lineno, line in numbered(path)
                     for verb in MODULE_CALL.findall(line)
                     if verb not in verbs]
        self.assertEqual(offenders, [], "\n" + "\n".join(
            [f"documented subcommands the CLI does not have "
             f"(it has: {', '.join(sorted(verbs))})"] + offenders))

    def test_every_documented_long_flag_exists_in_the_parser(self):
        """Asked of argparse, so the list can never drift from the code."""
        known = long_flags_of(self.parser)
        for sub in subcommands(self.parser).values():
            known |= long_flags_of(sub)

        offenders = [f"{path.parent.name}/SKILL.md:{lineno}: {flag}"
                     for path in SKILLS
                     for lineno, line in numbered(path)
                     for flag in LONG_FLAG.findall(line)
                     if flag not in known]
        self.assertEqual(offenders, [], "\n" + "\n".join(
            ["flags documented in a skill that no lupa parser accepts — an agent "
             "following the skill would run a command that dies"] + offenders))

    def test_every_documented_filter_is_a_flag_of_lupa_search(self):
        """The filter table sits under the section that shows the CLI call.

        A name listed there with no matching `lupa search --<name>` reads as a
        flag and is not one. If a filter really is MCP-only, the table has to say
        so — the fix belongs in the skill, not in a loosened check here.
        """
        search = subcommands(self.parser)["search"]
        known = long_flags_of(search)

        offenders = []
        for path in SKILLS:
            for lineno, cells in table_rows(numbered(path), "Filter"):
                for name in BACKTICKED.findall(cells[0]) or [cells[0]]:
                    spellings = {f"--{name}", f"--{name.replace('_', '-')}"}
                    if not spellings & known:
                        offenders.append(
                            f"{path.parent.name}/SKILL.md:{lineno}: `{name}` is "
                            f"presented as a filter, but `lupa search` has no "
                            f"--{name}")
        self.assertEqual(offenders, [], "\n" + "\n".join(
            [f"`lupa search` accepts only: "
             f"{', '.join(sorted(known - {'--help'}))}"] + offenders))


class TestConsequentialFlagsAreDocumented(unittest.TestCase):
    """The inverse check, and deliberately narrow.

    A skill choosing not to list every flag is legitimate curation. A skill
    hiding the flag that decides whether the user's index gets published to
    Google Drive is not.
    """

    def test_the_flags_that_change_what_leaves_the_machine_are_mentioned(self):
        parser = real_parser()
        known = set()
        for sub in subcommands(parser).values():
            known |= long_flags_of(sub)

        missing = []
        for flag, skill in sorted(CONSEQUENTIAL_FLAGS.items()):
            self.assertIn(flag, known,
                          f"{flag} is listed as consequential but the CLI no longer "
                          f"has it — update CONSEQUENTIAL_FLAGS in this file")
            path = REPO / "skills" / skill / "SKILL.md"
            self.assertTrue(path.exists(), f"missing skill: {path}")
            if flag not in read(path):
                missing.append(f"{skill}/SKILL.md never mentions {flag}")
        self.assertEqual(missing, [], "\n" + "\n".join(
            ["a flag with a privacy or cost consequence is missing from the skill "
             "that has to offer it"] + missing))


class TestDocumentedErrorsExist(unittest.TestCase):
    """Symptoms promised by a 'Common errors' table must be real strings.

    Only the literal part is checked: the leading status glyph is dropped (the
    docs write `✗ Gemini key`, the code writes just the label) and so is
    everything from the first placeholder on, so `I could not make sense of
    "<x>"` is looked up as `I could not make sense of`. A message the source
    genuinely cannot contain verbatim belongs in ERRORS_NOT_IN_THE_SOURCE with a
    reason, not in a loosened regex.
    """

    def literal_of(self, quoted):
        text = re.split(r"[\"'`]?[<{]", quoted)[0]
        text = re.sub(r"^[^0-9A-Za-z]+", "", text.strip())    # ✗, ⏳, !!, bullets
        return text.strip().strip("`\"' ")

    def test_every_quoted_symptom_appears_in_the_source(self):
        blob = "\n".join(read(path) for path in SOURCES)

        offenders = []
        for path in SKILLS:
            for lineno, cells in table_rows(numbered(path), "Symptom"):
                for quoted in BACKTICKED.findall(cells[0]):
                    literal = self.literal_of(quoted)
                    if len(literal) < 8:          # too short to identify anything
                        continue
                    if (path.parent.name, quoted) in ERRORS_NOT_IN_THE_SOURCE:
                        continue
                    if literal not in blob:
                        offenders.append(
                            f"{path.parent.name}/SKILL.md:{lineno}: the docs "
                            f'promise "{literal}" but no file in lupa/ emits it')
        self.assertEqual(offenders, [], "\n" + "\n".join(
            ["error messages documented but never produced — the user is told to "
             "look for text that will never appear"] + offenders))


if __name__ == "__main__":
    unittest.main()
