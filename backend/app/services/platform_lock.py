"""Small cross-platform exclusive file lock used by local persistence code."""

from __future__ import annotations

import os
from contextlib import contextmanager


@contextmanager
def exclusive_lock(handle):
    """Hold an exclusive lock on the first byte of an open lock file."""
    if os.name == "nt":
        import msvcrt

        # msvcrt.locking requires an existing byte and a read/write handle.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write("0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
