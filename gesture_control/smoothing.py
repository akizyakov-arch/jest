"""Time-based One Euro filtering; frequency parameters are in Hz.

Algorithm reference: https://gery.casiez.net/1euro/
"""

from math import isfinite, pi


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.5, beta: float = 0.4,
                 derivative_cutoff: float = 1.0):
        if not all(isfinite(v) for v in (min_cutoff, beta, derivative_cutoff)):
            raise ValueError("Filter parameters must be finite")
        if min_cutoff <= 0 or derivative_cutoff <= 0 or beta < 0:
            raise ValueError("Cutoffs must be positive and beta nonnegative")
        self.min_cutoff, self.beta, self.derivative_cutoff = min_cutoff, beta, derivative_cutoff
        self.reset()

    def reset(self) -> None:
        self._time: float | None = None
        self._raw = self._filtered = self._derivative = 0.0

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        return 1.0 / (1.0 + 1.0 / (2.0 * pi * cutoff * dt))

    def update(self, value: float, timestamp: float) -> float:
        if not isfinite(value) or not isfinite(timestamp):
            raise ValueError("Filter input and timestamp must be finite")
        if self._time is None:
            self._time, self._raw, self._filtered = timestamp, value, value
            return value
        if timestamp <= self._time:
            return self._filtered
        dt = timestamp - self._time
        derivative = (value - self._raw) / dt
        alpha_d = self._alpha(self.derivative_cutoff, dt)
        self._derivative += alpha_d * (derivative - self._derivative)
        cutoff = self.min_cutoff + self.beta * abs(self._derivative)
        self._filtered += self._alpha(cutoff, dt) * (value - self._filtered)
        self._time, self._raw = timestamp, value
        return self._filtered
