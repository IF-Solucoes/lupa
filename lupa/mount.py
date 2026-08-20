"""Recognizes a local folder that is really Google Drive mounted on disk.

Indexing through the mount works, but it loses three things only the API
provides: free OCR, shareable links, and immutable file ids. Preflight says so —
it does not block.
"""
import re

# Roots that Google Drive for Desktop creates on the platforms that matter.
MARKERS = (
    r"[/\\](meu drive|my drive)([/\\]|$)",
    r"[/\\](drives compartilhados|shared drives)([/\\]|$)",
    r"[/\\]google ?drive([/\\]|$)",
    r"cloudstorage[/\\]googledrive",
)


def looks_like_mounted_drive(path):
    """True when the path looks like Drive synchronized onto the local disk."""
    text = str(path).lower()
    return any(re.search(marker, text) for marker in MARKERS)
