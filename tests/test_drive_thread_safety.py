"""httplib2 is not thread-safe, so no two requests may share one Http.

The describe pipeline downloads with a ThreadPoolExecutor. With the single Http
that build() makes by default, two threads ended up reading the same SSL socket;
that corrupts memory inside OpenSSL and kills the process with a segmentation
fault. There is no Python traceback to catch — the fault is native — so the only
thing a test can assert is the property that prevents it: every request gets its
own Http, and no two of them are the same object.
"""
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


class TestOneHttpPerRequest(unittest.TestCase):
    def setUp(self):
        self.build_request = request_builder_for(FakeCredentials())

    def _http_of(self):
        request = self.build_request(None, lambda resp, content: content,
                                     "https://www.googleapis.com/drive/v3/files")
        return request.http

    def test_two_requests_never_share_an_http(self):
        first, second = self._http_of(), self._http_of()
        self.assertIsNot(first, second)

    def test_every_request_in_a_burst_gets_its_own(self):
        objects = [self._http_of() for _ in range(8)]
        self.assertEqual(len({id(each) for each in objects}), 8)

    def test_the_http_underneath_is_distinct_too(self):
        # AuthorizedHttp wraps an httplib2.Http, and it is that inner object
        # which owns the socket. A fresh wrapper around a shared socket would
        # crash exactly the same way.
        first, second = self._http_of(), self._http_of()
        self.assertIsNot(first.http, second.http)


if __name__ == "__main__":
    unittest.main()
