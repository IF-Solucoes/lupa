"""One Http per thread: never shared, always reused.

Two opposite failures pin this down, and a test that only checks one of them
lets the other back in.

Sharing one Http across the download pool puts two threads on the same SSL
socket, which corrupts memory inside OpenSSL and kills the process with a
segmentation fault. There is no Python traceback to assert on — the fault is
native — so the test asserts the property that prevents it: threads never share.

Handing out a fresh Http per request prevents that too, and then dies the other
way: every request opens a TLS connection, Windows holds each closed socket in
TIME_WAIT, and ~6000 images exhausted the ephemeral port range — 5843 connection
resets and DNS failures for a host that had been answering all along. So the
test also asserts the other half: within one thread, the Http is reused.
"""
import threading
import unittest

from lupa.drive import request_builder_for


class FakeCredentials:
    """Enough of a credentials object for AuthorizedHttp to wrap it."""

    def __init__(self):
        self.token = "fake-token"
        self.valid = True
        self.expired = False

    def before_request(self, request, method, url, headers):
        headers["authorization"] = f"Bearer {self.token}"


class TestOneHttpPerThread(unittest.TestCase):
    def setUp(self):
        self.build_request = request_builder_for(FakeCredentials())

    def _http(self):
        request = self.build_request(None, lambda resp, content: content,
                                     "https://www.googleapis.com/drive/v3/files")
        return request.http

    def test_the_same_thread_reuses_its_connection(self):
        # The half that keeps a real archive from exhausting the port range.
        self.assertIs(self._http(), self._http())

    def test_a_burst_on_one_thread_still_opens_only_one(self):
        objects = {id(self._http()) for _ in range(50)}
        self.assertEqual(len(objects), 1)

    def test_two_threads_never_share_one(self):
        # The half that keeps OpenSSL from being handed the same socket twice.
        collected = {}

        def grab(name):
            collected[name] = self._http()

        first = threading.Thread(target=grab, args=("a",))
        second = threading.Thread(target=grab, args=("b",))
        first.start(), second.start()
        first.join(), second.join()

        self.assertIsNot(collected["a"], collected["b"])
        self.assertIsNot(collected["a"].http, collected["b"].http)

    def test_every_worker_in_a_pool_gets_its_own(self):
        from concurrent.futures import ThreadPoolExecutor

        def one(_):
            return id(self._http()), threading.get_ident()

        with ThreadPoolExecutor(max_workers=8) as pool:
            seen = list(pool.map(one, range(200)))

        # However the pool schedules the 200 calls, an Http never crosses from
        # the thread that made it into another one.
        by_thread = {}
        for http_id, thread_id in seen:
            by_thread.setdefault(thread_id, set()).add(http_id)
        for thread_id, http_ids in by_thread.items():
            self.assertEqual(len(http_ids), 1, f"thread {thread_id} reused badly")

        owners = {}
        for http_id, thread_id in seen:
            owners.setdefault(http_id, set()).add(thread_id)
        for http_id, threads in owners.items():
            self.assertEqual(len(threads), 1, f"http {http_id} crossed threads")


if __name__ == "__main__":
    unittest.main()
