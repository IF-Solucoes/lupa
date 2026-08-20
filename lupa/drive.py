"""Google Drive layer.

Parsing is pure and tested. Network access is isolated in the functions at the
bottom, imported only when credentials exist — so the core runs without the
Google client libraries installed.
"""
import hashlib
import re

LABELS_MARKER = "Image labels:"

# Fields requested from the API. Each one saves a later round trip.
FIELDS = ("files(id,name,mimeType,md5Checksum,size,modifiedTime,trashed,"
          "webViewLink,imageMediaMetadata(width,height,cameraMake,cameraModel)),nextPageToken")


INDEX_FOLDER = "_lupa"
FOLDER_MIME = "application/vnd.google-apps.folder"


def folder_query(folder_id):
    """Images directly inside this folder, nothing from the trash."""
    return (f"'{folder_id}' in parents and mimeType contains 'image/' "
            f"and trashed = false")


def subfolder_query(folder_id):
    """Subfolders directly inside this folder."""
    return (f"'{folder_id}' in parents and mimeType = '{FOLDER_MIME}' "
            f"and trashed = false")


def split_ocr_and_labels(snippet):
    """Drive returns OCR text and labels glued into one field. This separates them.

    The OCR is useful and free. The labels are generic Google noise — kept raw,
    never trusted for classification.
    """
    if not snippet:
        return "", []

    parts = snippet.split(LABELS_MARKER, 1)
    ocr = parts[0].strip()
    if len(parts) == 1:
        return ocr, []

    raw = parts[1].strip().strip("\\").strip()
    raw = re.sub(r"^\\?\[|\\?\]$", "", raw).strip()
    labels = [label.strip().strip("\\").strip() for label in raw.split(";")]
    return ocr, [label for label in labels if label]


def _hash_of(raw):
    """md5 when the API provides one; otherwise a fingerprint of size and date."""
    if raw.get("md5Checksum"):
        return raw["md5Checksum"]
    seed = f"{raw.get('size', '')}|{raw.get('modifiedTime', '')}"
    return hashlib.md5(seed.encode()).hexdigest()


def normalize_file(raw):
    """Converts an API response into the shape the rest of lupa consumes."""
    media = raw.get("imageMediaMetadata") or {}
    ocr, labels = split_ocr_and_labels(raw.get("contentSnippet"))

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
        "ocr_text": ocr,
        "labels": labels,
        "url": raw.get("webViewLink") or f"https://drive.google.com/file/d/{raw.get('id')}/view",
        "trashed": bool(raw.get("trashed")),
    }


# --- network below this line. None of it is imported by the core. ---

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",  # read the collection
    "https://www.googleapis.com/auth/drive.file",      # write ONLY what we create
]


def connect(client_secret, token_path):
    """Returns the Drive service, prompting for sign-in only the first time."""
    from pathlib import Path

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

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
        token_path.write_text(credentials.to_json())

    return build("drive", "v3", credentials=credentials, cache_discovery=False)


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


def ensure_folder(service, parent_id, name):
    """Finds (or creates) a subfolder. This is how _lupa/ is born inside a collection."""
    query = (f"'{parent_id}' in parents and name = '{name}' and "
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

    query = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    existing = service.files().list(q=query, fields="files(id)",
                                    supportsAllDrives=True).execute()
    if existing.get("files"):
        file_id = existing["files"][0]["id"]
        return service.files().update(fileId=file_id, media_body=media,
                                      supportsAllDrives=True).execute()["id"]

    body = {"name": name, "parents": [folder_id]}
    return service.files().create(body=body, media_body=media, fields="id",
                                  supportsAllDrives=True).execute()["id"]
