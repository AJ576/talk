"""Crash-safe, append-only text logs."""

import os
from datetime import datetime


def stamp():
    return datetime.now().isoformat(timespec="seconds")


class AppendLog:
    """Append-only text file. Every write is flushed and fsynced immediately, so
    a crash or power loss can lose at most the message currently being generated.
    Files are never truncated or rewritten, including across runs."""

    def __init__(self, path):
        self.path = path
        self._f = open(path, "a", encoding="utf-8")

    def write(self, text):
        self._f.write(text)
        self._f.flush()
        os.fsync(self._f.fileno())

    def close(self):
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
