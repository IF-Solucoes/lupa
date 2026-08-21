"""The download cache must never hand out half a file.

`DriveSource.fetch` keeps Drive originals under `.cache/<collection>/<file_id>`:

    if not local.exists():
        download(service, file_id, local)
    data = local.read_bytes()

`drive.download` writes straight to that final name, so the file is VISIBLE and
INCOMPLETE for as long as the transfer lasts. In batch mode the same file_id is
asked for by two concurrent paths — the pipeline worker (which wants the
thumbnail) and the batch assembly loop — so one thread reaches `read_bytes()`
while the other is still writing. What comes back is a TRUNCATED image, and a
truncated image goes to the model, is paid for, and lands in the index looking
exactly like a legitimate description.

The same window also buys the file twice: both threads can find `exists()` false
before either has written a byte.

These tests hold the window open on purpose — the download stand-in writes in
chunks with a short sleep between them — so they fail on the defect instead of
passing on scheduling luck. Style follows tests/test_batch_race.py.
"""
import tempfile
import threading
import time
import unittest
from pathlib import Path

import lupa.drive
from lupa import cli
from lupa.target import Target

# A PNG signature so mime_of says image/png, and enough junk after it that
# Pillow refuses to parse — downscale then returns the bytes untouched, which
# is what lets these tests compare what went in with what came out.
PAYLOAD = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 256
FILE_ID = "1aBcDeFgHiJkLmNoPqRsTuVwXyZ012345"
COLLECTION = "prova-cache"


class SlowDownload:
    """A download that takes its time, in chunks, the way a real one does.

    It writes to the destination it is handed and nowhere else. That is the
    whole point of the double: whatever path the cache chooses to write to is
    the path that spends this long being incomplete.
    """

    CHUNKS = 8
    PAUSE = 0.01

    def __init__(self, payload=PAYLOAD, before_first_chunk=0.0, drop_after=None):
        self.payload = payload
        self.before_first_chunk = before_first_chunk
        # Bytes after which the FIRST call dies, like a connection dropping
        # mid-transfer. Only the first: a later call must be able to succeed, or
        # a test could not tell a poisoned cache from a broken double.
        self.drop_after = drop_after
        self.calls = []
        self.guard = threading.Lock()
        self.entered = threading.Event()          # a download has begun
        self.wrote_something = threading.Event()  # bytes are on disk, more coming

    def __call__(self, service, file_id, destination):
        with self.guard:
            self.calls.append(file_id)
            attempt = len(self.calls)
        self.entered.set()
        time.sleep(self.before_first_chunk)

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        step = len(self.payload) // self.CHUNKS + 1
        written = 0
        with open(destination, "wb") as handle:
            for start in range(0, len(self.payload), step):
                handle.write(self.payload[start:start + step])
                handle.flush()
                written += step
                self.wrote_something.set()
                if (self.drop_after is not None and attempt == 1
                        and written >= self.drop_after):
                    raise OSError("the connection dropped mid-transfer")
                time.sleep(self.PAUSE)
        return destination


class CacheTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / ".cache" / COLLECTION
        self.saved = (lupa.drive.connect, lupa.drive.download,
                      lupa.drive.fetch_thumbnail)
        lupa.drive.connect = lambda *a, **kw: (object(), object())
        # No thumbnail link is ever registered (list() was never called), so the
        # cheap path is skipped anyway; this makes that explicit.
        lupa.drive.fetch_thumbnail = lambda *a, **kw: None

    def tearDown(self):
        (lupa.drive.connect, lupa.drive.download,
         lupa.drive.fetch_thumbnail) = self.saved
        self.tmp.cleanup()

    def a_source(self):
        target = Target(kind="drive", name=COLLECTION, folder_id="folder-1")
        source, _service = cli.build_source(target, {}, self.cache)
        return source

    def fetching(self, source, answers, errors, slot, wait_for=None):
        """A thread body: fetch one id and park the bytes under `slot`."""
        def go():
            try:
                if wait_for is not None and not wait_for.wait(10):
                    errors.append(f"{slot}: the download never started")
                    return
                answers[slot] = source.fetch(FILE_ID)[0]
            except BaseException as failure:   # noqa: BLE001 - reported, not hidden
                errors.append(f"{slot}: {failure!r}")
        return threading.Thread(target=go, name=slot)


class TestTheCacheNeverHandsOutHalfAFile(CacheTestCase):
    def test_a_reader_arriving_mid_download_gets_the_whole_image(self):
        downloading = SlowDownload()
        lupa.drive.download = downloading
        source = self.a_source()
        answers, errors = {}, []

        writer = self.fetching(source, answers, errors, "writer")
        reader = self.fetching(source, answers, errors, "reader",
                               wait_for=downloading.wrote_something)
        writer.start()
        reader.start()
        writer.join(30)
        reader.join(30)

        self.assertEqual([], errors)
        got = answers.get("reader", b"")
        self.assertEqual(
            len(PAYLOAD), len(got),
            f"the reader was handed {len(got)} of {len(PAYLOAD)} bytes — a "
            f"truncated image, on its way to the model and into the index")
        self.assertEqual(PAYLOAD, got)
        self.assertEqual(PAYLOAD, answers.get("writer"))

    def test_the_cached_name_never_exists_half_written(self):
        """Watched from outside fetch, so no lock can make this pass by luck.

        Whenever the final cache name exists at all, it must already be whole:
        that is what makes the rename atomic rather than merely serialized.
        """
        downloading = SlowDownload()
        lupa.drive.download = downloading
        source = self.a_source()
        cached = self.cache / FILE_ID
        sizes, unopenable, done = [], [], threading.Event()

        def look():
            if not cached.exists():
                return
            try:
                sizes.append(len(cached.read_bytes()))
            except OSError as refused:
                # Expected on Windows, and NOT a dirty read: for the instant
                # os.replace takes, an opener can be turned away with a sharing
                # violation. Being told "not now" is the opposite of being
                # handed half a file, so it is counted apart. lupa's own readers
                # never even see this window — the per-id lock in DriveSource
                # keeps them out of it.
                unopenable.append(repr(refused))

        def watch():
            while not done.is_set():
                look()
                time.sleep(0.002)
            look()   # one last look, so the assertion is never vacuous

        watcher = threading.Thread(target=watch, name="watcher")
        watcher.start()
        try:
            source.fetch(FILE_ID)
        finally:
            done.set()
            watcher.join(30)

        self.assertTrue(sizes, f"the watcher never once read the cached file "
                               f"(refused {len(unopenable)} times: {unopenable[:2]})")
        partial = sorted({size for size in sizes if size != len(PAYLOAD)})
        self.assertEqual(
            [], partial,
            f"the cached name was readable at sizes {partial} while the "
            f"download was still running (whole file is {len(PAYLOAD)} bytes)")


class TestOneFileIsDownloadedOnce(CacheTestCase):
    def test_two_threads_asking_for_the_same_id_buy_it_once(self):
        # Slow to produce its first byte: both threads get past exists() before
        # either has written anything. This is the window, held open.
        downloading = SlowDownload(before_first_chunk=0.05)
        lupa.drive.download = downloading
        source = self.a_source()
        answers, errors = {}, []

        first = self.fetching(source, answers, errors, "first")
        second = self.fetching(source, answers, errors, "second")
        first.start()
        self.assertTrue(downloading.entered.wait(10),
                        "the first download never started")
        second.start()
        first.join(30)
        second.join(30)

        self.assertEqual(
            1, len(downloading.calls),
            f"{len(downloading.calls)} downloads of the same file in one run — "
            f"the same bytes bought {len(downloading.calls)} times")
        self.assertEqual([], errors)
        self.assertEqual(PAYLOAD, answers.get("first"))
        self.assertEqual(PAYLOAD, answers.get("second"))


class TestAFailedDownloadLeavesNothingBehind(CacheTestCase):
    def test_a_dropped_transfer_does_not_poison_the_cache(self):
        broken = SlowDownload(drop_after=len(PAYLOAD) // 4)
        lupa.drive.download = broken
        source = self.a_source()

        with self.assertRaises(OSError):
            source.fetch(FILE_ID)

        again, _mime = source.fetch(FILE_ID)   # the same double, second attempt
        self.assertEqual(2, len(broken.calls),
                         "the retry was served from the cache instead of "
                         "downloading — the half file was treated as a hit")
        self.assertEqual(
            PAYLOAD, again,
            "the half file the failed transfer left behind was served as a hit")

    def test_it_leaves_no_litter_in_the_cache(self):
        broken = SlowDownload(drop_after=len(PAYLOAD) // 4)
        lupa.drive.download = broken
        source = self.a_source()

        with self.assertRaises(OSError):
            source.fetch(FILE_ID)

        leftovers = sorted(entry.name for entry in self.cache.iterdir()) \
            if self.cache.exists() else []
        self.assertEqual([], leftovers,
                         f"a failed download left {leftovers} in the cache")


if __name__ == "__main__":
    unittest.main()


class TestTheThumbnailIsFetchedOncePerImage(CacheTestCase):
    """The cheap path had no cache, so batch mode paid for it twice.

    `fetch` prefers the thumbnail Google already made. In batch mode the same
    file_id arrives from two paths — the batch assembly loop, which builds the
    request, and the pipeline worker, which wants bytes for the local thumbnail.
    The full-download path below has held a disk cache all along; the thumbnail
    path sat above it with nothing, so every image crossed the network twice.

    Bandwidth, not money: the model is charged once either way. On the first
    client archive it was 875 images downloaded twice over a domestic link.
    """

    LINK = "https://example.invalid/thumbnail"

    class CountingThumbnail:
        def __init__(self, payload=PAYLOAD):
            self.payload = payload
            self.calls = 0

        def __call__(self, credentials, link, size=None):
            self.calls += 1
            return self.payload

    def a_source_with_a_thumbnail(self, thumb):
        lupa.drive.fetch_thumbnail = thumb
        source = self.a_source()
        source.thumbnails = {FILE_ID: self.LINK}
        return source

    def test_the_second_fetch_does_not_cross_the_network(self):
        thumb = self.CountingThumbnail()
        source = self.a_source_with_a_thumbnail(thumb)
        source.fetch(FILE_ID)
        source.fetch(FILE_ID)
        self.assertEqual(1, thumb.calls,
                         "the same image was pulled from Drive twice")

    def test_both_fetches_return_the_same_bytes(self):
        """Anti-tautology: a cache that serves the wrong bytes is worse than none."""
        thumb = self.CountingThumbnail()
        source = self.a_source_with_a_thumbnail(thumb)
        first, first_mime = source.fetch(FILE_ID)
        second, second_mime = source.fetch(FILE_ID)
        self.assertEqual(PAYLOAD, first)
        self.assertEqual(first, second)
        self.assertEqual(first_mime, second_mime)

    def test_a_thumbnail_that_fails_still_falls_through_to_the_download(self):
        """The cheap path is an optimisation, never a requirement."""
        def broken(credentials, link, size=None):
            raise RuntimeError("no thumbnail today")

        # Before build_source: it binds `download` by value when it is called,
        # so a stand-in installed afterwards never reaches the source.
        lupa.drive.download = SlowDownload()
        source = self.a_source_with_a_thumbnail(broken)
        data, _ = source.fetch(FILE_ID)
        self.assertEqual(PAYLOAD, data)

    def test_two_threads_asking_at_once_fetch_it_once(self):
        """The batch loop and the pipeline worker, arriving together."""
        thumb = self.CountingThumbnail()
        source = self.a_source_with_a_thumbnail(thumb)
        answers, errors = {}, []
        first = self.fetching(source, answers, errors, "a")
        second = self.fetching(source, answers, errors, "b")
        first.start(), second.start()
        first.join(), second.join()
        self.assertEqual([], errors)
        self.assertEqual(1, thumb.calls, "both threads crossed the network")
