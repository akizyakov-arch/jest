"""Relative two-finger strokes with bounded momentum and release hysteresis."""

from math import exp, trunc


class ScrollGesture:
    def __init__(self, settings):
        self.settings = settings
        self.reset()

    def reset(self, keep_burst=False):
        if not keep_burst:
            self.burst_at = None
            self.burst_direction = 0
            self.gain = 1.
        self.new_stroke = True
        self.active = False
        self.started = self.anchor = self.time = None
        self.remainder = 0.
        self.velocity = 0.
        self.released_at = None
        self.navigation_since = None
        self.stroke_direction = 0
        self.reverse_since = None

    def release(self, timestamp):
        """Consume uncertain poses before returning ownership to the cursor.

        Called only for fresh, valid tracking. Actual tracking loss resets us.
        Re-presenting two fingers brakes momentum and reanchors the next stroke.
        """
        if self.time is None or timestamp <= self.time:
            return 0
        dt = min(.05, timestamp-self.time)
        self.time = timestamp
        if self.released_at is None:
            self.released_at = timestamp
        elapsed = timestamp-self.released_at
        units = 0
        if self.active and abs(self.velocity) >= 30 and elapsed < .9:
            decay = exp(-dt/.22)
            units = self._emit(self.velocity*.22*(1-decay))
            self.velocity *= decay
        if elapsed >= .18 and (abs(self.velocity) < 30 or elapsed >= .9):
            self.reset(keep_burst=True)
        return units

    def _stroke_units(self, motion, dt, timestamp):
        direction = 1 if motion > 0 else -1
        self.stroke_direction = direction
        if self.new_stroke or direction != self.burst_direction:
            interval = timestamp-self.burst_at if self.burst_at is not None else float('inf')
            window = self.settings.scroll_burst_window_ms/1000
            if direction == self.burst_direction and 0 < interval < window:
                self.gain = min(self.settings.scroll_burst_max,
                                self.gain+self.settings.scroll_burst_step*(1-interval/window))
            else:
                self.gain = 1.
            self.new_stroke = False
        self.burst_at, self.burst_direction = timestamp, direction
        units = -motion*self.settings.scroll_sensitivity*self.gain
        if self.settings.scroll_invert:
            units = -units
        limit = min(10000., self.settings.scroll_max_rate*self.gain)*dt
        units = max(-limit, min(limit, units))
        self.velocity = units/dt if dt else 0.
        return self._emit(units)

    def _emit(self, units):
        self.remainder += units
        whole = trunc(self.remainder)
        self.remainder -= whole
        return whole

    def update(self, position, timestamp):
        if self.time is not None and timestamp <= self.time:
            return 0
        dt = min(.05, timestamp-self.time) if self.time is not None else 0.
        self.time = timestamp
        if self.released_at is not None:
            self.released_at = None
            self.anchor = position
            self.velocity = self.remainder = 0.
            self.navigation_since = None
            self.new_stroke = True
            self.stroke_direction = 0
            self.reverse_since = None
            return 0
        if not self.active:
            if self.anchor is None:
                self.anchor, self.started = position, timestamp
            elapsed = timestamp-self.started
            stroke = position[1]-self.anchor[1]
            fast_stroke = (elapsed >= self.settings.scroll_swipe_confirm_ms/1000 and abs(stroke) >= max(.025, 2*self.settings.scroll_dead_zone)
                           and abs(stroke)/elapsed >= .25)
            if elapsed >= self.settings.scroll_enter_ms/1000 or fast_stroke:
                self.active = True
                self.anchor = position
                # Preserve the initiating flick, but never replay an accumulated
                # backlog: the first event has the same per-frame rate cap.
                if fast_stroke:
                    return self._stroke_units(stroke, dt, timestamp)
            return 0
        delta = position[1]-self.anchor[1]
        if abs(delta) <= self.settings.scroll_dead_zone:
            # Keeping the two-finger pose still acts like touching the pad:
            # brake, rather than repeatedly scrolling at a fixed hand height.
            self.velocity *= exp(-dt/.04)
            self.reverse_since = None
            return 0
        motion = delta-self.settings.scroll_dead_zone*(1 if delta > 0 else -1)
        self.anchor = (position[0], position[1]-(delta-motion))
        direction = 1 if motion > 0 else -1
        if self.stroke_direction and direction != self.stroke_direction:
            if self.reverse_since is None:
                self.reverse_since = timestamp
            self.velocity = self.remainder = 0.
            if timestamp-self.reverse_since < self.settings.scroll_reverse_confirm_ms/1000:
                return 0
        else:
            self.reverse_since = None
        return self._stroke_units(motion, dt, timestamp)
