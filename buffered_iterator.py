import queue
from queue import Queue
from threading import Lock
from typing import Iterable, Iterator


class BufferedIterator:
    def __init__(self, iterator: Iterator, buffer_size: int):
        self._iterator = iterator
        self._queue = Queue()
        self._buffer_size: int = buffer_size
        self._buffer_lock = Lock()

    def __iter__(self):
        return self

    def _buffer(self):
        try:
            for i in range(self._buffer_size):
                self._queue.put(next(self._iterator))

            return True
        except StopIteration:
            return False

    def _get(self):
        if self._queue.empty():
            if not self._buffer_lock.acquire(blocking=False):
                # Someone else is already buffering, no need to do it twice
                # Wait for lock to be free, and then recursively call self
                self._buffer_lock.acquire()
                self._buffer_lock.release()

                return self._get()
            else:
                try:
                    if not self._buffer():
                        raise StopIteration
                finally:
                    self._buffer_lock.release()

        try:
            return self._queue.get()
        except queue.Empty:
            return self._get()

    def __next__(self):
        return self._get()
