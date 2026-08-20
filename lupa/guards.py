"""Guardrails. Rebuilding an index costs money and destroys history.

Rule: `index` never overwrites. It detects the existing index and points the user
at `update`. Rebuilding requires typed intent.
"""
import json
import os
import sys
import time
from pathlib import Path

MAX_LOCK_AGE_S = 30 * 60  # half an hour: past that, the lock owner is gone

# A lock is a claim staked by a process. There are two ways that claim goes void:
# the process is gone, or it has held the lock too long to still be believed.
# Age alone was the only check for a while, and it made a killed run block its own
# recovery for half an hour -- with a paid batch sitting there waiting to be
# collected and the receipt telling the user to resume. The pid is in the file.
_STILL_ACTIVE = 259          # Windows: GetExitCodeProcess for a running process
_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_FILETIME_EPOCH_OFFSET = 11644473600   # 1601-01-01 -> 1970-01-01, in seconds
_CLOCK_SLACK_S = 5           # a process starts, THEN writes its lock; never after


class IndexAlreadyExists(Exception):
    pass


class LockBusy(Exception):
    pass


def _windows_owner(pid):
    """(alive, started_at). kernel32 through ctypes: stdlib, no new package.

    OpenProcess is the Windows answer to `os.kill(pid, 0)`, with one wrinkle --
    while anybody still holds a handle to a dead process (a parent that has not
    let go, for instance) OpenProcess keeps succeeding on it. So the exit code
    has to be read as well: only STILL_ACTIVE means it is really running.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    # HANDLE is pointer-sized: without argtypes ctypes would default to C int and
    # could truncate it on 64-bit.
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, wintypes.LPDWORD)
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (
        ctypes.POINTER(wintypes.FILETIME),) * 4

    handle = kernel32.OpenProcess(_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means it exists and belongs to somebody else; anything
        # else (invalid parameter, above all) means there is no such process.
        return (ctypes.get_last_error() == _ERROR_ACCESS_DENIED), None
    try:
        code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            if code.value != _STILL_ACTIVE:
                return False, None
        creation, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if kernel32.GetProcessTimes(handle, ctypes.byref(creation),
                                    ctypes.byref(exited), ctypes.byref(kernel),
                                    ctypes.byref(user)):
            ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return True, ticks / 1e7 - _FILETIME_EPOCH_OFFSET
        return True, None
    finally:
        kernel32.CloseHandle(handle)


def _linux_started_at(pid):
    """Boot time plus the process's own start offset, both read out of /proc.
    Linux only; on any other POSIX this returns None and the caller does without.
    """
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text()
        # The comm field is parenthesised and may itself contain spaces, so
        # everything countable lives after the last ')'. starttime is field 22.
        after = raw[raw.rindex(")") + 2:].split()
        ticks = float(after[19])
        boot = 0.0
        for line in (Path("/proc") / "stat").read_text().splitlines():
            if line.startswith("btime "):
                boot = float(line.split()[1])
                break
        if not boot:
            return None
        return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, AttributeError):
        return None


def _posix_owner(pid):
    """(alive, started_at). Signal 0 runs every check the kernel would run for a
    real signal and then delivers nothing."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False, None
    except PermissionError:
        return True, _linux_started_at(pid)   # alive, just not ours to signal
    except OSError:
        return True, None                     # unclear: assume alive, never steal
    return True, _linux_started_at(pid)


def _owner(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        # 0 and negatives address process GROUPS on POSIX, not processes: a lock
        # naming one of those is a lock nobody can vouch for.
        return False, None
    try:
        if sys.platform == "win32":
            return _windows_owner(pid)
        return _posix_owner(pid)
    except Exception:
        # Whatever went wrong while inspecting, the safe answer is "alive": a
        # wrong "dead" hands a running index to a second writer, while a wrong
        # "alive" only costs a wait that MAX_LOCK_AGE_S already puts a lid on.
        return True, None


def owner_is_alive(pid, started=None):
    """True when this pid belongs to a running process that could plausibly be
    the one that wrote the lock at `started`.

    pid reuse is the trap here: the number outlives the process, and the next
    process to get it would look like the owner. Where the creation time is
    readable (always on Windows, through /proc on Linux) it settles the
    question -- a process that started AFTER the lock was written cannot be the
    one that wrote it. Where it is not readable the pid stands on its own and
    the answer leans toward alive.
    """
    alive, born = _owner(pid)
    if not alive:
        return False
    if started and born and born > started + _CLOCK_SLACK_S:
        return False                          # same number, different process
    return True


def process_started_at(pid):
    """Epoch seconds, or None on a platform that will not say."""
    return _owner(pid)[1]


def check_before_indexing(index_dir, collection, rebuild=False, confirm=None):
    """Raises IndexAlreadyExists unless the collection is untouched, or the user
    typed the exact name alongside --rebuild."""
    manifest = Path(index_dir) / "MANIFEST.json"
    if not manifest.exists():
        return

    if rebuild and confirm == collection:
        return

    try:
        data = json.loads(manifest.read_text())
    except (json.JSONDecodeError, OSError):
        data = {}
    total = data.get("total", "?")
    runs = data.get("runs", "?")

    if not rebuild:
        raise IndexAlreadyExists(
            f"This collection is already indexed: {total} images, {runs} runs.\n"
            f"  You probably want:   lupa update {collection}\n"
            f'  To rebuild from scratch: lupa index {collection} --rebuild --confirm "{collection}"'
        )
    raise IndexAlreadyExists(
        f'Rebuilding discards {runs} runs of history for "{collection}".\n'
        f'  Confirm by typing the collection name:  --confirm "{collection}"'
    )


def needs_cost_confirmation(count, ceiling):
    """True when the run would describe more images than the ceiling allows
    without asking. A ceiling of 0 disables the check."""
    return bool(ceiling) and count > ceiling


class Lock:
    """Keeps two runs from scrambling the manifest. A stale lock is reclaimed.

    Stale means either of two things, and they are not the same thing:
      * the process that took the lock does not exist any more, whatever the
        clock says -- the case of a run killed in the middle of a batch; or
      * the lock is older than MAX_LOCK_AGE_S -- the safety net for an owner
        that is still breathing but has stopped making progress.

    A lock taken away from a dead owner is announced, never taken in silence.
    """

    def __init__(self, index_dir, on_notice=None):
        self.path = Path(index_dir) / ".lock"
        self.stamp = None
        self.on_notice = on_notice or (lambda line: print(line, file=sys.stderr))

    def __enter__(self):
        if self.path.exists():
            reason = self._stale()
            if reason is None:
                raise LockBusy(
                    f"Another run is using this index ({self.path}). "
                    "Wait for it to finish, or delete the file if you are sure."
                )
            self.on_notice(reason)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stamp = {"pid": os.getpid(), "started": time.time()}
        self.path.write_text(json.dumps(self.stamp))
        return self

    def __exit__(self, *_):
        """Releases the lock only while it is still ours. A run that outlives
        MAX_LOCK_AGE_S has its lock reclaimed out from under it, and deleting the
        file on the way out would then be deleting somebody else's lock -- which
        leaves a third run free to walk into an index two others are writing."""
        try:
            held = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError, AttributeError):
            held = None                    # unreadable or already gone: ours to clear
        if held is not None and held != self.stamp:
            self.on_notice(
                f"Not releasing the lock at {self.path}: it was taken over by "
                f"pid {held.get('pid')} while this run was still working."
            )
            return False
        self.path.unlink(missing_ok=True)
        return False

    def _stale(self):
        """None while the lock still holds. Otherwise the line saying why it does
        not, which the caller is expected to show: a lock that changes hands in
        silence is how a run ends up unprotected without anyone noticing."""
        try:
            record = json.loads(self.path.read_text())
            started = record.get("started", 0)
            pid = record.get("pid")
        except (json.JSONDecodeError, OSError, AttributeError):
            return (f"Reclaiming the lock at {self.path}: the file cannot be read, "
                    "so there is nobody left to wait for.")

        if pid is not None and not owner_is_alive(pid, started):
            return (f"Reclaiming the lock at {self.path}: the process that owned it "
                    f"(pid {pid}) no longer exists.")

        age = time.time() - started
        if age > MAX_LOCK_AGE_S:
            return (f"Reclaiming the lock at {self.path}: it has been held for "
                    f"{int(age / 60)} min, past the {int(MAX_LOCK_AGE_S / 60)} min "
                    "limit.")
        return None
