"""Application maintenance gates. Stable flock files are never unlinked.

Normal operations share a gate; recovery holds exclusive access then sorted entity
 gates before SQLite writer reservations. Nested shared opens are safe on Unix.
"""
import fcntl
import os
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from accounting_harness.persistence import PersistenceBusy


def workspace_lock(root):
    return Path(root) / '.maintenance.lock'


def access_lock(path):
    return Path(str(path) + '.maintenance.lock')


@contextmanager
def maintenance_lock(path, *, exclusive=False):
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PersistenceBusy('Workspace maintenance busy; retry later') from error
        yield
    finally:
        os.close(descriptor)


def workspace_operation(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with maintenance_lock(workspace_lock(self.root)):
            return method(self, *args, **kwargs)
    return guarded
