"""Every text file lupa reads or writes is UTF-8, said out loud.

On Windows `open()`, `Path.read_text()` and `Path.write_text()` with no
`encoding=` do not mean "whatever the file is". They mean cp1252. A collection
belonging to a Brazilian client — "4 - Fotos & Vídeos", "Conscientização e
Incentivo Vacinação" — is full of bytes cp1252 cannot decode, and the failure
lands *after* the images were described and billed:

    File "lupa/build.py", line 401, in _write_manifest
      runs = json.loads(path.read_text()).get("runs", 0)
    UnicodeDecodeError: 'charmap' codec can't decode byte 0x81 in position
    173059: character maps to <undefined>

875 images, already paid for, and the run dies while writing the one file that
makes the next run incremental.

Two kinds of test live here:

  * `TestNoUndeclaredEncoding` sweeps `lupa/` and `scripts/` with the `ast`
    module and fails on any text read or write that does not name its encoding.
    That is the one that stops the defect coming back, and it is the only one
    that means the same thing on every platform.
  * the rest exercise the real functions with real accented content, which on a
    cp1252 host reproduces the crash above byte for byte. On a host whose
    default encoding is already UTF-8 they pass either way — they document the
    payload, the sweep enforces the rule.
"""
import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from lupa import build, config, guards

REPO = Path(__file__).resolve().parent.parent

# The directories that ship. `tests/` is deliberately not swept: a test may open
# a file in a broken encoding on purpose, which is the point of the test.
SWEPT = (REPO / "lupa", REPO / "scripts")

# Calls that read or write text and therefore have to name an encoding.
TEXT_CALLS = frozenset({"open", "read_text", "write_text"})

# ---------------------------------------------------------------------------
# The exceptions, in full. Anything not on this list needs `encoding=`.
#
#   binary mode      open(p, "rb") / open(p, "wb") / entry.open("rb")
#                    — bytes have no encoding. Detected from the mode argument.
#   Image.open       PIL. Takes a path or a BytesIO and decodes a JPEG, not
#                    text; it has no encoding parameter at all.
#   urlopen          urllib.request.urlopen. A socket, not a file; the response
#                    is bytes and the caller decodes it explicitly. Never
#                    matched here anyway — the attribute is `urlopen`, not
#                    `open` — and it is listed so nobody has to rediscover why.
#   read_bytes /     bytes in, bytes out. Not matched, listed for the same
#   write_bytes      reason.
# ---------------------------------------------------------------------------
BINARY_MODE = "b"

# Objects whose `.open()` is not the file builtin. Keyed by the expression the
# call hangs off, exactly as it is written in the source.
NOT_A_TEXT_FILE = {
    "Image": "PIL — decodes an image, has no encoding parameter",
}

# Individual calls waived by hand. Empty on purpose: every exception so far is
# structural (binary mode, PIL) and is recognised as such above. An entry here
# is keyed by (path relative to the repo, the call as written) and must carry
# the reason it cannot name an encoding.
WAIVED = {
    # ("lupa/example.py", 'thing.open()'): "reason it cannot",
}


def python_files():
    for directory in SWEPT:
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def is_binary(call, position):
    """True when the mode argument asks for bytes.

    `open(path, "rb")` puts the mode second; `entry.open("rb")` puts it first,
    because the path is the receiver. Hence `position`.
    """
    for argument in list(call.args[position:position + 1]) + [
            keyword.value for keyword in call.keywords if keyword.arg == "mode"]:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            if BINARY_MODE in argument.value:
                return True
    return False


def undeclared_calls(path):
    """(line, source) for every text read or write in `path` with no encoding."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    try:
        relative = path.relative_to(REPO).as_posix()
    except ValueError:                       # a file made by a test, not shipped
        relative = path.name
    found = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Name):
            name, owner, mode_at = node.func.id, None, 1
        elif isinstance(node.func, ast.Attribute):
            name, owner, mode_at = node.func.attr, ast.unparse(node.func.value), 0
        else:
            continue

        if name not in TEXT_CALLS:
            continue
        if owner is not None and owner in NOT_A_TEXT_FILE:
            continue
        if is_binary(node, mode_at):
            continue
        if any(keyword.arg == "encoding" for keyword in node.keywords):
            continue
        written = ast.unparse(node)
        if (relative, written) in WAIVED:
            continue
        found.append((node.lineno, written))

    return relative, found


class TestNoUndeclaredEncoding(unittest.TestCase):
    """The sweep. Reads the shipped source as text; runs nothing in it."""

    def test_every_text_read_and_write_names_its_encoding(self):
        offenders = []
        for path in python_files():
            relative, found = undeclared_calls(path)
            offenders += [f"{relative}:{line}: {written}" for line, written in found]

        self.assertEqual(offenders, [], "\n\nThese read or write text without "
                         "encoding=, which is cp1252 on Windows:\n  "
                         + "\n  ".join(offenders) + "\n\nAdd encoding=\"utf-8\". "
                         "If the call really cannot, put it in WAIVED with the "
                         "reason.\n")

    def test_the_sweep_would_catch_the_line_that_broke_the_run(self):
        """The sweep is only worth having if it fails on the real defect."""
        with tempfile.TemporaryDirectory() as folder:
            offender = Path(folder) / "regression.py"
            offender.write_text(
                "import json\n"
                "def broken(path):\n"
                "    return json.loads(path.read_text()).get('runs', 0)\n",
                encoding="utf-8")
            _, found = undeclared_calls(offender)

        self.assertEqual([written for _, written in found],
                         ["path.read_text()"])

    def test_the_sweep_lets_binary_and_pil_through(self):
        with tempfile.TemporaryDirectory() as folder:
            allowed = Path(folder) / "allowed.py"
            allowed.write_text(
                "import urllib.request\n"
                "from PIL import Image\n"
                "def fine(path, entry, request):\n"
                "    with open(path, 'wb') as handle:\n"
                "        handle.write(b'')\n"
                "    entry.open('rb').read(8)\n"
                "    Image.open(path)\n"
                "    urllib.request.urlopen(request, timeout=60)\n"
                "    path.read_bytes()\n",
                encoding="utf-8")
            _, found = undeclared_calls(allowed)

        self.assertEqual(found, [])


# The names that actually broke it: a client folder and its images.
#
# The uppercase Á is not decoration. UTF-8 writes it C3 81, and 0x81 is one of
# the five bytes cp1252 has no character for — it is the byte named in the
# traceback. A lowercase-only fixture ("Vídeos" is C3 AD) would be *decoded* by
# cp1252 into mojibake and the test would pass while the bug stayed.
FOLDER = "4 - Fotos & Vídeos"
IMAGE = "Conscientização e Incentivo Vacinação.jpg"
UPPERCASE = "VACINAÇÃO ANTIRRÁBICA — CÃES E GATOS.jpg"
ACCENTED = f"{FOLDER}/{UPPERCASE}"


def accented_items(count=2):
    names = (UPPERCASE, IMAGE)
    return [{"id": f"id{n}", "hash": f"h{n}",
             "file": f"{FOLDER}/{n} - {names[n % len(names)]}",
             "caption": "Ação de conscientização na recepção da clínica",
             "tags": ["vacinação", "atenção"], "entities": ["Clínica Noroeste"]}
            for n in range(count)]


class AccentedIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class TestManifestSurvivesAccentedFileNames(AccentedIndex):
    """`_write_manifest` re-reads the manifest it is about to replace, only to
    carry the run counter forward. That read is what died, after the money was
    spent."""

    def write_once(self, items, now):
        return build.write_index(
            self.dir, collection="cvn-clinica-veterinaria-noroeste", items=items,
            summary="resumo com acentuação", model="gemini-3.5-flash-lite",
            cost_usd=0.43, now=now, usage=None, batch=True)

    def test_a_second_run_reads_the_first_manifest_and_counts_it(self):
        items = accented_items()
        first = self.write_once(items, "2026-08-20T14-03-00")
        self.assertEqual(first["runs"], 1)

        second = self.write_once(items, "2026-08-20T20-34-00")

        self.assertEqual(second["runs"], 2)
        self.assertEqual(second["total"], len(items))
        stored = json.loads((self.dir / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertIn(FOLDER, json.dumps(stored, ensure_ascii=False))

    def test_the_manifest_on_disk_is_utf8_bytes(self):
        self.write_once(accented_items(), "2026-08-20T14-03-00")
        raw = (self.dir / "MANIFEST.json").read_bytes()
        self.assertIn(FOLDER.encode("utf-8"), raw)

    def test_an_undecodable_manifest_costs_the_counter_not_the_run(self):
        """A manifest no encoding can read must not kill a paid run. The counter
        is worth nothing; the 875 descriptions above it are worth US$ 0.43."""
        self.write_once(accented_items(), "2026-08-20T14-03-00")
        (self.dir / "MANIFEST.json").write_bytes(b'{"runs": 7, "x": "\xff\xfe\x81"}')

        again = self.write_once(accented_items(), "2026-08-20T20-34-00")

        self.assertEqual(again["runs"], 1)      # counter restarted, run survived
        self.assertEqual(again["total"], 2)


class TestGuardsReadTheAccentedManifest(AccentedIndex):
    """`check_before_indexing` opens the same file down a different path, before
    a single image is described."""

    def manifest(self, **extra):
        payload = {"collection": "cvn-clinica-veterinaria-noroeste", "total": 875,
                   "runs": 2, "items": {"id0": {"hash": "h", "file": ACCENTED}}}
        payload.update(extra)
        (self.dir / "MANIFEST.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_it_refuses_and_quotes_the_numbers_it_read(self):
        self.manifest()
        with self.assertRaises(guards.IndexAlreadyExists) as raised:
            guards.check_before_indexing(self.dir, "cvn-clinica-veterinaria-noroeste")
        self.assertIn("875 images, 2 runs", str(raised.exception))

    def test_an_undecodable_manifest_still_refuses_rather_than_crashing(self):
        (self.dir / "MANIFEST.json").write_bytes(b'{"total": 875, \x81\xff}')
        with self.assertRaises(guards.IndexAlreadyExists):
            guards.check_before_indexing(self.dir, "cvn-clinica-veterinaria-noroeste")


class TestLockRoundTrip(AccentedIndex):
    """The `.lock` payload is ASCII today, which is exactly why the missing
    encoding there never showed up. It is still a text file written on one
    machine and read on another."""

    def test_the_lock_is_written_and_read_back_as_utf8(self):
        with guards.Lock(self.dir) as lock:
            raw = (self.dir / ".lock").read_bytes()
            self.assertEqual(json.loads(raw.decode("utf-8")), lock.stamp)
            self.assertEqual(json.loads((self.dir / ".lock").read_text(
                encoding="utf-8"))["pid"], os.getpid())
        self.assertFalse((self.dir / ".lock").exists())

    def test_an_unreadable_lock_is_reclaimed_not_raised(self):
        (self.dir / ".lock").write_bytes(b"\x81\xff not json")
        notices = []
        with guards.Lock(self.dir, on_notice=notices.append):
            pass
        self.assertTrue(any("Reclaiming" in line for line in notices))


class TestConfigKeepsAccentedFolderPaths(AccentedIndex):
    """`collections.json` stores the client's own folder paths. Those have the
    accents in them."""

    def test_a_windows_path_with_accents_survives_the_round_trip(self):
        path = self.dir / "collections.json"
        folder = str(Path("C:/Users/igorf/Fotos") / FOLDER)
        config.write_config({"collections": [
            {"name": "cvn-clinica-veterinaria-noroeste", "folder": folder}]},
            path=path)

        self.assertIn(FOLDER.encode("utf-8"), path.read_bytes())
        back = config.read_config(path=path)
        self.assertEqual(back["collections"][0]["folder"], folder)


class TestErrorReportKeepsAccentedNames(AccentedIndex):
    """`runs/*.errors.jsonl` is the list of what failed — by file name, with the
    provider's message. Both are the client's language."""

    def test_a_failure_line_round_trips(self):
        report = self.dir / "failures.errors.jsonl"
        failures = [{"file": ACCENTED, "error": "não foi possível descrever"}]
        report.write_text(
            "\n".join(json.dumps(f, ensure_ascii=False) for f in failures) + "\n",
            encoding="utf-8")

        self.assertEqual(
            [json.loads(line) for line in
             report.read_text(encoding="utf-8").splitlines()], failures)


if __name__ == "__main__":
    unittest.main()
