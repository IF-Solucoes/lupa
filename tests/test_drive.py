"""Reading Drive: parsing the metadata the API returns."""
import json
import unittest

from lupa.drive import FIELDS, folder_query, normalize_file


class TestNormalization(unittest.TestCase):
    def test_it_maps_the_api_fields(self):
        raw = {
            "id": "1a2B", "name": "post-24.png", "mimeType": "image/png",
            "md5Checksum": "abc123", "size": "4321764",
            "imageMediaMetadata": {"width": 1080, "height": 1350},
            "webViewLink": "https://drive.google.com/file/d/1a2B/view",
        }
        entry = normalize_file(raw)
        self.assertEqual(entry["id"], "1a2B")
        self.assertEqual(entry["file"], "post-24.png")
        self.assertEqual(entry["hash"], "abc123")
        self.assertEqual((entry["w"], entry["h"]), (1080, 1350))
        self.assertEqual(entry["url"], "https://drive.google.com/file/d/1a2B/view")

    def test_without_md5_it_fingerprints_size_and_date(self):
        # Google Docs and some formats carry no md5Checksum
        entry = normalize_file({"id": "x", "name": "a.png", "size": "100",
                                "modifiedTime": "2026-08-20T10:00:00Z"})
        self.assertTrue(entry["hash"])

    def test_it_extracts_the_camera_exif(self):
        raw = {"id": "x", "name": "f.jpg", "imageMediaMetadata": {
            "width": 4032, "height": 3024, "cameraMake": "Apple", "cameraModel": "iPhone 15"}}
        self.assertEqual(normalize_file(raw)["exif"]["Make"], "Apple")

    def test_missing_dimensions_become_zero(self):
        entry = normalize_file({"id": "x", "name": "a.png"})
        self.assertEqual((entry["w"], entry["h"]), (0, 0))

    def test_a_trashed_file_is_flagged(self):
        self.assertTrue(normalize_file({"id": "x", "name": "a.png", "trashed": True})["trashed"])


class TestQuery(unittest.TestCase):
    def test_it_restricts_to_the_folder_and_to_images(self):
        query = folder_query("FOLDER123")
        self.assertIn("'FOLDER123' in parents", query)
        self.assertIn("image/", query)

    def test_it_excludes_the_trash(self):
        self.assertIn("trashed = false", folder_query("X"))


if __name__ == "__main__":
    unittest.main()


class FakeDriveService:
    """A Drive stand-in: answers files().list() from a folder tree in memory.

    tree: {folder_id: {"folders": [(id, name)], "images": [(id, name)]}}
    """

    def __init__(self, tree):
        self.tree = tree
        self.queries = []

    def files(self):
        return self

    def list(self, q=None, **_):
        self.queries.append(q)
        parent = q.split("'")[1]
        node = self.tree.get(parent, {})
        if "mimeType = 'application/vnd.google-apps.folder'" in q:
            entries = [{"id": fid, "name": name,
                        "mimeType": "application/vnd.google-apps.folder"}
                       for fid, name in node.get("folders", [])]
        else:
            entries = [{"id": fid, "name": name, "mimeType": "image/png",
                        "md5Checksum": f"hash-{fid}",
                        "imageMediaMetadata": {"width": 100, "height": 100}}
                       for fid, name in node.get("images", [])]
        return FakeRequest({"files": entries})


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


TREE = {
    "root": {"folders": [("sub", "Campaigns"), ("idx", "_lupa")],
             "images": [("a", "cover.png")]},
    "sub": {"folders": [("deep", "2026")], "images": [("b", "post.png")]},
    "deep": {"folders": [], "images": [("c", "story.png")]},
    "idx": {"folders": [], "images": [("z", "contact-sheet.png")]},
}


class TestRecursiveListing(unittest.TestCase):
    def setUp(self):
        from lupa.drive import list_images
        self.service = FakeDriveService(TREE)
        self.found = list_images(self.service, "root")

    def test_it_reaches_images_in_subfolders(self):
        self.assertIn("b", [f["id"] for f in self.found])

    def test_it_reaches_images_several_levels_down(self):
        self.assertIn("c", [f["id"] for f in self.found])

    def test_it_still_lists_the_root(self):
        self.assertIn("a", [f["id"] for f in self.found])

    def test_the_file_name_carries_the_relative_path(self):
        deep = [f for f in self.found if f["id"] == "c"][0]
        self.assertEqual(deep["file"], "Campaigns/2026/story.png")

    def test_a_root_file_keeps_its_bare_name(self):
        root = [f for f in self.found if f["id"] == "a"][0]
        self.assertEqual(root["file"], "cover.png")

    def test_it_never_descends_into_its_own_index_folder(self):
        self.assertNotIn("z", [f["id"] for f in self.found])

    def test_a_flat_collection_still_works(self):
        from lupa.drive import list_images
        flat = FakeDriveService({"only": {"folders": [], "images": [("x", "a.png")]}})
        self.assertEqual([f["id"] for f in list_images(flat, "only")], ["x"])

    def test_recursion_can_be_turned_off(self):
        from lupa.drive import list_images
        shallow = list_images(FakeDriveService(TREE), "root", recursive=False)
        self.assertEqual([f["id"] for f in shallow], ["a"])


class TestCycleSafety(unittest.TestCase):
    def test_a_folder_loop_does_not_hang(self):
        from lupa.drive import list_images
        looping = {
            "a": {"folders": [("b", "B")], "images": [("i1", "1.png")]},
            "b": {"folders": [("a", "A")], "images": [("i2", "2.png")]},
        }
        found = list_images(FakeDriveService(looping), "a")
        self.assertEqual(sorted(f["id"] for f in found), ["i1", "i2"])


# --- the guard that would have caught this at the first commit ---

try:
    from googleapiclient.discovery_cache import get_static_doc
except ImportError:                                    # core runs without the Google libs
    get_static_doc = None


def _parse_field_spec(spec):
    """`FIELDS` → {parent_or_None: {names}}, the way the Drive API reads it.

    "files(id,name,imageMediaMetadata(width)),nextPageToken" becomes
    {None: {"files", "nextPageToken"}, "files": {"id", "name", "imageMediaMetadata"},
     "imageMediaMetadata": {"width"}}.
    """
    groups, parent, name, stack = {None: set()}, None, "", []
    for char in spec + ",":
        if char == "(":
            stack.append(parent)
            parent = name
            groups.setdefault(parent, set())
            name = ""
        elif char == ")":
            if name:
                groups[parent].add(name)
            parent, name = stack.pop(), ""
        elif char == ",":
            if name:
                groups[parent].add(name)
            name = ""
        elif not char.isspace():
            name += char
    return groups


@unittest.skipIf(get_static_doc is None, "google-api-python-client is not installed")
class TestEveryRequestedFieldExistsInTheAPI(unittest.TestCase):
    """`fields=` is not a wish list: an unknown name is an HTTP 400 on every listing.

    A name that is never requested at all is worse — it is silent. lupa read
    `contentSnippet` off every listing response since the first commit; the Drive v3
    File schema has no such property and the request never asked for one, so
    `ocr_text` was "" and `labels` was [] in every index ever written, and `has_text`
    was False for all 875 images of the first real collection. The discovery document
    shipped inside google-api-python-client is the authority on what exists, so it is
    what this test reads.
    """

    @classmethod
    def setUpClass(cls):
        cls.file_schema = json.loads(get_static_doc("drive", "v3"))["schemas"]["File"]

    def test_every_name_in_fields_is_a_real_property_at_its_level(self):
        groups = _parse_field_spec(FIELDS)
        unknown = []

        def walk(schema, parent):
            known = set(schema.get("properties") or {})
            for name in sorted(groups.get(parent, ())):
                if name not in known:
                    unknown.append(f"{parent}.{name}")
                    continue
                if name in groups:
                    walk(schema["properties"][name], name)

        walk(self.file_schema, "files")   # files(...) holds File properties
        self.assertEqual(unknown, [], f"lupa asks Drive for {unknown}, which the "
                                      f"File schema does not have")

    def test_the_phantom_field_is_named_here_so_it_cannot_come_back(self):
        self.assertNotIn("contentSnippet", set(self.file_schema["properties"]))
        self.assertNotIn("contentSnippet", FIELDS)


class TestNoPhantomFieldsInTheNormalizedItem(unittest.TestCase):
    def test_it_invents_no_ocr_text(self):
        # Drive never sent it. An empty string here reads like an answer.
        self.assertNotIn("ocr_text", normalize_file({"id": "x", "name": "a.png"}))

    def test_it_invents_no_labels(self):
        self.assertNotIn("labels", normalize_file({"id": "x", "name": "a.png"}))
