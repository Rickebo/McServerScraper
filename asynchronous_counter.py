import itertools


class AsynchronousCounter:
    def __init__(self):
        self._counter = itertools.count()
        self._value: int = 0

    def increment(self) -> int:
        val = self._value = next(self._counter)
        return val

    @property
    def value(self) -> int:
        return self._value
