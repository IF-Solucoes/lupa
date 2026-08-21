"""Google Drive layer.

Parsing is pure and tested. Network access is isolated in the functions at the
bottom, imported only when credentials exist — so the core runs without the
Google client libraries installed.
"""
import hashlib

# Fields requested from the API. Each one saves a later round trip.
#
# Every name here must be a real property of the Drive v3 `File` resource. An
# unknown name is not ignored: `fields=` answers it with HTTP 400 and the whole
# listing dies. tests/test_drive.py checks each one against the discovery document
# that ships inside google-api-python-client, because the opposite mistake — reading
# a field nobody ever asked for — is silent, and cost this repository `has_text`,
# `text` and `labels` on every image it ever indexed.
FIELDS = ("files(id,name,mimeType,md5Checksum,size,modifiedTime,trashed,"
          "webViewLink,thumbnailLink,"
          "imageMediaMetadata(width,height,cameraMake,cameraModel)),nextPageToken")


INDEX_FOLDER = "_lupa"
FOLDER_MIME = "application/vnd.google-apps.folder"

# Fields for `lupa map`, which counts what an index will never see. It asks for
# EVERY child of a folder, not only the images, so this is the smallest list that
# can tell a folder from a file and a file from its type. Same rule as FIELDS
# above: every name is a real File property, and tests/test_drive.py checks it
# against the discovery document.
MAP_FIELDS = "files(id,name,mimeType,size),nextPageToken"


def children_query(folder_id):
    """Everything directly inside this folder — files AND subfolders.

    `folder_query` filters to `mimeType contains 'image/'`, which is exactly why
    video, PSD and Google Docs are invisible to an index. Counting what gets
    ignored means asking for all of it.
    """
    return f"'{folder_id}' in parents and trashed = false"


def folder_query(folder_id):
    """Images directly inside this folder, nothing from the trash."""
    return (f"'{folder_id}' in parents and mimeType contains 'image/' "
            f"and trashed = false")


def subfolder_query(folder_id):
    """Subfolders directly inside this folder."""
    return (f"'{folder_id}' in parents and mimeType = '{FOLDER_MIME}' "
            f"and trashed = false")


def _hash_of(raw):
    """md5 when the API provides one; otherwise a fingerprint of size and date."""
    if raw.get("md5Checksum"):
        return raw["md5Checksum"]
    seed = f"{raw.get('size', '')}|{raw.get('modifiedTime', '')}"
    return hashlib.md5(seed.encode()).hexdigest()


def normalize_file(raw):
    """Converts an API response into the shape the rest of lupa consumes."""
    media = raw.get("imageMediaMetadata") or {}

    exif = {}
    if media.get("cameraMake"):
        exif["Make"] = media["cameraMake"]
    if media.get("cameraModel"):
        exif["Model"] = media["cameraModel"]

    return {
        "id": raw.get("id"),
        "file": raw.get("name"),
        "mime": raw.get("mimeType"),
        "hash": _hash_of(raw),
        "size": int(raw.get("size") or 0),
        "w": int(media.get("width") or 0),
        "h": int(media.get("height") or 0),
        "exif": exif,
        "url": raw.get("webViewLink") or f"https://drive.google.com/file/d/{raw.get('id')}/view",
        "thumbnail": raw.get("thumbnailLink"),
        "trashed": bool(raw.get("trashed")),
    }


# --- network below this line. None of it is imported by the core. ---

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",  # read the collection
    "https://www.googleapis.com/auth/drive.file",      # write ONLY what we create
]


def connect(client_secret, token_path, with_credentials=False):
    """Returns the Drive service, prompting for sign-in only the first time.

    with_credentials=True also returns the credentials, which the thumbnail
    endpoint needs (it is a plain HTTP GET, outside the API client).
    """
    from pathlib import Path

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    if not token_path:
        # Never reached through config.environment(), which always fills this
        # in. A caller that builds its own env deserves a sentence, not a
        # TypeError from inside pathlib.
        raise ValueError("no path to store the Google sign-in: "
                         "LUPA_OAUTH_TOKEN is empty")

    token_path = Path(token_path).expanduser()
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(Path(client_secret).expanduser()), SCOPES)
            credentials = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        # google-auth reads this file back as utf-8 whatever the host locale is,
        # so it is the encoding to write it in.
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return (service, credentials) if with_credentials else service


def _list_page(service, query, fields):
    """Runs one paginated listing to exhaustion."""
    entries, page = [], None
    while True:
        response = service.files().list(
            q=query, fields=fields, pageSize=1000, pageToken=page,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        entries += response.get("files", [])
        page = response.get("nextPageToken")
        if not page:
            return entries


def walk_folders(service, root_id):
    """Breadth-first walk of the folder tree, rooted at root_id.

    Yields (folder_id, relative_prefix). The collection's own index folder is
    never entered, and a shortcut loop cannot hang the walk.
    """
    queue = [(root_id, "")]
    seen = {root_id}
    while queue:
        folder_id, prefix = queue.pop(0)
        yield folder_id, prefix

        for child in _list_page(service, subfolder_query(folder_id),
                                "files(id,name),nextPageToken"):
            child_id, name = child.get("id"), child.get("name") or ""
            if name == INDEX_FOLDER or child_id in seen:
                continue
            seen.add(child_id)
            queue.append((child_id, f"{prefix}{name}/"))


def walk_entries(service, root_id):
    """Breadth-first walk yielding `(relative_prefix, files)` for every folder.

    `files` is every non-folder child, whatever its type — this is what `lupa
    map` counts, and it is the half `list_images` throws away.

    One listing call per folder, not two. `walk_folders` + `list_images` ask the
    same folder twice — once for its subfolders, once for its images — and on a
    collection with a hundred folders that is a hundred avoidable round trips.
    Here the subfolders and the files come out of the same paginated response,
    which is the fewest calls the API allows: `in parents` only ever matches
    direct children, so there is no query that returns a whole tree.

    Yields empty folders too. A folder that vanished from the map because it
    held nothing would be indistinguishable from one holding nothing but video.
    """
    queue = [(root_id, "")]
    seen = {root_id}
    while queue:
        folder_id, prefix = queue.pop(0)
        files = []
        for child in _list_page(service, children_query(folder_id), MAP_FIELDS):
            name = child.get("name") or ""
            if child.get("mimeType") == FOLDER_MIME:
                child_id = child.get("id")
                if name == INDEX_FOLDER or child_id in seen:
                    continue           # never our own index; never a shortcut loop
                seen.add(child_id)
                queue.append((child_id, f"{prefix}{name}/"))
            else:
                files.append({"name": name, "mime": child.get("mimeType"),
                              "size": int(child.get("size") or 0)})
        yield prefix, files


def list_images(service, folder_id, recursive=True):
    """Metadata for every image at or below the folder. Downloads nothing.

    A collection is a starting point, not a flat directory: by default the walk
    branches into every subfolder. `file` carries the path relative to the root,
    so two images named cover.png in different folders stay distinguishable.
    """
    branches = walk_folders(service, folder_id) if recursive else [(folder_id, "")]

    files = []
    for current_id, prefix in branches:
        for entry in _list_page(service, folder_query(current_id), FIELDS):
            item = normalize_file(entry)
            item["file"] = f"{prefix}{item['file']}"
            files.append(item)
    return files


def fetch_thumbnail(credentials, link, size=None):
    """Downloads the thumbnail Google already generated, at the size we ask for.

    This is the cheap path: no full download, no Pillow, and the model receives a
    768px image instead of a 24-megapixel original.
    """
    import urllib.request

    from google.auth.transport.requests import Request

    from lupa.thumbnail import MAX_EDGE_PX, thumbnail_url

    url = thumbnail_url(link, size or MAX_EDGE_PX)
    if not url:
        return None

    if not credentials.valid:
        credentials.refresh(Request())
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {credentials.token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def download(service, file_id, destination):
    """Fetches one file to local disk (a working copy for the vision model)."""
    from pathlib import Path

    from googleapiclient.http import MediaIoBaseDownload

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with open(destination, "wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return destination


def folder_name(service, folder_id):
    """The name the user sees in Drive — it becomes the collection name."""
    info = service.files().get(fileId=folder_id, fields="name",
                               supportsAllDrives=True).execute()
    return info.get("name") or folder_id


def _quoted(value):
    """One value, quoted for a Drive query. A name is somebody else's input.

    Publishing the CVN index died on HTTP 400 at `atrium-d'argent.md`, an
    entity page named after a real client: the apostrophe closed the literal
    and the rest of the name became syntax. Every by-entity and by-tag page is
    named from the archive's own vocabulary, so the archive decides whether
    publish works.

    The backslash is escaped first, or the one added for the quote would
    itself be escaped a second time.
    """
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def list_children(service, folder_id):
    """Everything directly inside a folder — files and subfolders, no trash."""
    return _list_page(service, children_query(folder_id),
                      "files(id,name,mimeType),nextPageToken")


def retire_file(service, file_id):
    """Moves a file to the Drive trash. Recoverable on purpose.

    An index that shrank is never a reason to destroy somebody's file. The trash
    holds it for thirty days, which is the whole difference between a mistake
    that can be undone and one that cannot. The drive.file scope already
    guarantees this can only reach files lupa itself created.
    """
    return service.files().update(fileId=file_id, body={"trashed": True},
                                  supportsAllDrives=True).execute()["id"]


def ensure_folder(service, parent_id, name):
    """Finds (or creates) a subfolder. This is how _lupa/ is born inside a collection."""
    query = (f"'{parent_id}' in parents and name = {_quoted(name)} and "
             f"mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    found = service.files().list(q=query, fields="files(id)",
                                 supportsAllDrives=True).execute()
    if found.get("files"):
        return found["files"][0]["id"]

    body = {"name": name, "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id]}
    return service.files().create(body=body, fields="id",
                                  supportsAllDrives=True).execute()["id"]


def upload_file(service, folder_id, local_path, remote_name=None):
    """Creates or updates one index file. Never touches a file we did not create."""
    from pathlib import Path

    from googleapiclient.http import MediaFileUpload

    local_path = Path(local_path)
    name = remote_name or local_path.name
    media = MediaFileUpload(str(local_path), resumable=False)

    query = f"'{folder_id}' in parents and name = {_quoted(name)} and trashed = false"
    existing = service.files().list(q=query, fields="files(id)",
                                    supportsAllDrives=True).execute()
    if existing.get("files"):
        file_id = existing["files"][0]["id"]
        return service.files().update(fileId=file_id, media_body=media,
                                      supportsAllDrives=True).execute()["id"]

    body = {"name": name, "parents": [folder_id]}
    return service.files().create(body=body, media_body=media, fields="id",
                                  supportsAllDrives=True).execute()["id"]
