"""Atomic, locked JSON resource records; always read current disk state."""
import copy
import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path


class ResourceStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def read(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text('utf-8'))
        if not isinstance(data, dict):
            raise ValueError(f'资源存储损坏: {self.path.name}')
        return data

    @contextmanager
    def writing(self):
        with self._lock, self.path.with_suffix('.lock').open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                data = self.read()
                yield data
                fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.pending-')
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as output:
                        json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, self.path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def get(self, key):
        return copy.deepcopy(self.read().get(key))

    def list_all(self):
        return list(self.read().values())


class ResourceConflictError(ValueError):
    """An editor attempted to overwrite a newer persisted resource revision."""
