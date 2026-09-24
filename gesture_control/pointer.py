"""Virtual pointer geometry and conservative primary-hand continuity.

This module consumes perception snapshots and never sends OS input. MediaPipe
IDs are frame-local, so the owner is matched by palm geometry, not result order.
"""

from dataclasses import dataclass, replace
from math import dist, isfinite
from time import perf_counter

from .hand_tracking import TrackedHand, TrackingSnapshot
from .settings import Settings
from .smoothing import OneEuroFilter


@dataclass(frozen=True)
class WorkArea:
    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self):
        if not (0 <= self.left < self.right <= 1 and 0 <= self.top < self.bottom <= 1):
            raise ValueError("Work area must be ordered within 0..1")

    def map(self, point: tuple[float, float], mirrored: bool) -> tuple[float, float]:
        x, y = point
        if not isfinite(x) or not isfinite(y):
            raise ValueError("Coordinates must be finite")
        x = 1 - x if mirrored else x
        return (max(0.0, min(1.0, (x - self.left) / (self.right - self.left))),
                max(0.0, min(1.0, (y - self.top) / (self.bottom - self.top))))


@dataclass(frozen=True)
class PointerSnapshot:
    status: str = "WAITING"
    position: tuple[float, float] | None = None
    raw_position: tuple[float, float] | None = None
    source_hand_id: str | None = None
    handedness: str | None = None
    processing_ms: float = 0.0
    reason: str = ''


def palm_geometry(hand: TrackedHand) -> tuple[tuple[float, float], float] | None:
    if len(hand.landmarks) != 21 or not all(isfinite(v) for p in hand.landmarks for v in p):
        return None
    points = [hand.landmarks[i][:2] for i in (0, 5, 9, 13, 17)]
    center = (sum(p[0] for p in points) / 5, sum(p[1] for p in points) / 5)
    size = dist(hand.landmarks[0][:2], hand.landmarks[9][:2])
    return center, size


class VirtualPointer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.area = WorkArea(settings.work_area_left, settings.work_area_top,
                             settings.work_area_right, settings.work_area_bottom)
        self.preference = settings.primary_hand
        self._filters = [OneEuroFilter(settings.smoothing_min_cutoff, settings.smoothing_beta,
                                       settings.smoothing_derivative_cutoff) for _ in range(2)]
        self.reset()

    def reset(self) -> None:
        """Explicit re-selection; called by R or a deliberate hand preference change."""
        for smoothing in self._filters:
            smoothing.reset()
        self.snapshot = PointerSnapshot()
        self._center: tuple[float, float] | None = None
        self._size = 0.0
        self._seen_at: float | None = None
        self._frame_time = float("-inf")
        self._locked = False

    def resize_area(self, delta: float) -> None:
        """Resize around the center, preserving owner; session-only preview setting."""
        cx, cy = (self.area.left + self.area.right) / 2, (self.area.top + self.area.bottom) / 2
        width = min(max(self.area.right - self.area.left + delta, 0.2), 1.)
        height = min(max(self.area.bottom - self.area.top + delta, 0.2), 1.)
        cx = max(width/2, min(1-width/2, cx))
        cy = max(height/2, min(1-height/2, cy))
        self.area = WorkArea(cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)
        for smoothing in self._filters:
            smoothing.reset()

    def cycle_hand(self) -> None:
        choices = ("FIRST", "LEFT", "RIGHT")
        self.preference = choices[(choices.index(self.preference) + 1) % len(choices)]
        self.reset()

    def near_area(self) -> None:
        self.area = WorkArea(.25, .25, .75, .75)
        for smoothing in self._filters:
            smoothing.reset()

    def suspend(self) -> PointerSnapshot:
        self._locked = True
        self.snapshot = replace(self.snapshot, status="LOST - press R", source_hand_id=None)
        return self.snapshot

    def tick(self, now: float) -> PointerSnapshot:
        """Expire ownership even when capture/inference produces no callbacks."""
        if self._seen_at is not None and (now - self._seen_at) * 1000 > self.settings.tracking_loss_grace_ms:
            return self.suspend()
        if (self._seen_at is not None and not self._locked
                and (now - self._seen_at) * 1000 > self.settings.max_result_age_ms):
            self.snapshot = replace(self.snapshot, status="HOLD", source_hand_id=None)
        return self.snapshot

    def _hold(self, now: float, reason='stale_or_invalid_frame') -> PointerSnapshot:
        self.snapshot = replace(self.snapshot, status="HOLD" if self._center else "WAITING",
                                source_hand_id=None, reason=reason)
        return self.tick(now)

    def process(self, tracking: TrackingSnapshot, now: float) -> PointerSnapshot:
        started = perf_counter()
        self.tick(now)
        if self._locked:
            return self.snapshot
        timestamp = tracking.source_timestamp
        if not isfinite(timestamp) or timestamp <= self._frame_time:
            return self.snapshot
        if timestamp > now or (now - timestamp) * 1000 > self.settings.max_result_age_ms:
            return self._hold(now)
        self._frame_time = timestamp
        candidates = []
        for hand in tracking.hands:
            geometry = palm_geometry(hand)
            if geometry is not None and geometry[1] >= self.settings.hand_min_size:
                candidates.append((hand, *geometry))
        if self._center is None:
            candidates = [c for c in candidates if self.preference == "FIRST" or
                          (c[0].handedness.upper() == self.preference and
                           (c[0].handedness_score or 0) >= self.settings.hand_side_min_score)]
            if not candidates:
                return self._hold(now, 'no_matching_hand')
            # Deterministic initial choice if two hands first appear together.
            selected = min(candidates, key=lambda c: c[1][0])
        else:
            ranked = sorted(candidates, key=lambda c: dist(c[1], self._center))
            if not ranked:
                return self._hold(now, 'no_hand')
            if dist(ranked[0][1], self._center) > self.settings.hand_match_distance:
                return self._hold(now, 'hand_jump')
            if (len(ranked) > 1 and dist(ranked[1][1], self._center) - dist(ranked[0][1], self._center)
                    < self.settings.hand_match_margin):
                # Crossing/ambiguous hands require explicit re-selection.
                return self.suspend()
            selected = ranked[0]
            hand, _, size = selected
            if max(size / self._size, self._size / size) > self.settings.hand_size_ratio_limit:
                return self._hold(now, 'hand_size_changed')
            if (hand.handedness.upper() != (self.snapshot.handedness or "").upper()
                    and (hand.handedness_score or 0) >= self.settings.hand_side_min_score):
                return self._hold(now, 'handedness_changed')
        hand, center, size = selected
        source = center if self.settings.pointer_anchor == 'PALM' else hand.landmarks[8][:2]
        raw = self.area.map(source, self.settings.pointer_mirrored)
        filtered = tuple(f.update(value, timestamp) for f, value in zip(self._filters, raw))
        # Preserve exact reachability at borders after the filter settles.
        filtered = tuple(target if target in (0.0, 1.0) and abs(target - value) <= self.settings.pointer_dead_zone
                         else value for target, value in zip(raw, filtered))
        previous = self.snapshot.position
        if previous is not None and dist(filtered, previous) <= self.settings.pointer_dead_zone:
            filtered = previous
        # Snapped edges must not be swallowed by the dead zone.
        filtered = tuple(target if target in (0.0, 1.0) and abs(target - value) <= self.settings.pointer_dead_zone
                         else value for target, value in zip(raw, filtered))
        owner_label = self.snapshot.handedness or hand.handedness
        self._center, self._size, self._seen_at = center, size, timestamp
        self.snapshot = PointerSnapshot("TRACKING", filtered, raw, hand.hand_id, owner_label,
                                        (perf_counter() - started) * 1000)
        return self.snapshot
