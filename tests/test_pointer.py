import math
import unittest
from dataclasses import replace

from gesture_control.hand_tracking import TrackedHand, TrackingSnapshot
from gesture_control.pointer import VirtualPointer, WorkArea
from gesture_control.settings import Settings
from gesture_control.smoothing import OneEuroFilter


def hand(name="a", side="Right", x=0.4, tip=(0.5, 0.5)):
    points = [(x, 0.5, 0.0)] * 21
    points[0] = (x, 0.65, 0.0)
    points[8] = (*tip, 0.0)
    return TrackedHand(name, side, tuple(points), handedness_score=0.99)


def snapshot(timestamp, *hands):
    return TrackingSnapshot(round(timestamp * 1000), timestamp, timestamp + 0.01, hands)


class SmoothingTests(unittest.TestCase):
    def test_stationary_noise_is_reduced(self):
        smoothing = OneEuroFilter(beta=0)
        smoothing.update(0.5, 0)
        raw, filtered = [], []
        for index in range(1, 121):
            value = 0.5 + 0.01 * (-1) ** index
            raw.append(value - 0.5)
            filtered.append(smoothing.update(value, index / 30) - 0.5)
        self.assertLess(sum(x*x for x in filtered), sum(x*x for x in raw) * 0.1)

    def test_adaptation_reduces_fast_motion_lag(self):
        fixed, adaptive = OneEuroFilter(beta=0), OneEuroFilter(beta=4)
        for smoothing in (fixed, adaptive):
            smoothing.update(0, 0)
        for i in range(1, 10):
            fixed_value = fixed.update(i / 10, i / 30)
            adaptive_value = adaptive.update(i / 10, i / 30)
        self.assertGreater(adaptive_value, fixed_value)
        self.assertLessEqual(adaptive_value, 0.9)

    def test_duplicate_timestamps_and_reset(self):
        smoothing = OneEuroFilter()
        self.assertEqual(smoothing.update(0.2, 1), 0.2)
        self.assertEqual(smoothing.update(0.9, 1), 0.2)
        self.assertEqual(smoothing.update(0.9, 0), 0.2)
        smoothing.reset()
        self.assertEqual(smoothing.update(0.9, 2), 0.9)

    def test_nonfinite_values_rejected(self):
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                OneEuroFilter().update(value, 1)


class WorkAreaTests(unittest.TestCase):
    def test_edges_clamp_and_mirror(self):
        area = WorkArea(0.2, 0.3, 0.8, 0.7)
        self.assertEqual(area.map((0.2, 0.3), False), (0.0, 0.0))
        self.assertEqual(area.map((1, 1), False), (1.0, 1.0))
        self.assertEqual(area.map((1, 0), True), (0.0, 0.0))
        self.assertAlmostEqual(area.map((0.5, 0.5), False)[0], 0.5)

    def test_invalid_settings_rejected(self):
        for values in ({"work_area_left": 0.9}, {"smoothing_min_cutoff": 0},
                       {"smoothing_beta": float("nan")}, {"primary_hand": "ANY"},
                       {"pointer_mirrored": 1}, {"pointer_dead_zone": -0.1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings(**values)


class PointerTests(unittest.TestCase):
    def setUp(self):
        self.pointer = VirtualPointer(Settings(pointer_mode='INDEX', pointer_anchor='INDEX'))

    def test_second_hand_and_result_order_cannot_steal_pointer(self):
        first = self.pointer.process(snapshot(1, hand()), 1.01)
        second = self.pointer.process(snapshot(1.03, hand("b", "Left", 0.8),
                                                hand("new-frame-id", x=0.41)), 1.04)
        self.assertEqual(second.status, "TRACKING")
        self.assertEqual(second.source_hand_id, "new-frame-id")
        self.assertEqual(second.handedness, first.handedness)

    def test_preferred_hand_is_respected(self):
        pointer = VirtualPointer(Settings(primary_hand="LEFT"))
        self.assertEqual(pointer.process(snapshot(1, hand()), 1.01).status, "WAITING")
        selected = pointer.process(snapshot(1.03, hand(), hand("left", "Left", 0.8)), 1.04)
        self.assertEqual(selected.source_hand_id, "left")

    def test_missing_primary_does_not_switch_to_secondary(self):
        self.pointer.process(snapshot(1, hand()), 1.01)
        result = self.pointer.process(snapshot(1.03, hand("b", "Left", 0.8)), 1.04)
        self.assertEqual(result.status, "HOLD")
        self.assertIsNone(result.source_hand_id)

    def test_short_dropout_keeps_owner_but_long_loss_requires_reset(self):
        self.pointer.process(snapshot(1, hand()), 1.01)
        self.assertEqual(self.pointer.process(snapshot(1.03), 1.04).status, "HOLD")
        self.assertEqual(self.pointer.process(snapshot(1.06, hand()), 1.07).status, "TRACKING")
        self.pointer.tick(1.4)
        result = self.pointer.process(snapshot(1.41, hand()), 1.42)
        self.assertTrue(result.status.startswith("LOST"))
        self.pointer.reset()
        self.assertEqual(self.pointer.process(snapshot(1.44, hand()), 1.45).status, "TRACKING")

    def test_ambiguous_crossing_latches_loss(self):
        self.pointer.process(snapshot(1, hand()), 1.01)
        result = self.pointer.process(snapshot(1.03, hand(x=0.39), hand("b", "Left", 0.41)), 1.04)
        self.assertTrue(result.status.startswith("LOST"))

    def test_handedness_flip_does_not_change_owner(self):
        self.pointer.process(snapshot(1, hand()), 1.01)
        result = self.pointer.process(snapshot(1.03, hand(side="Left")), 1.04)
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.handedness, "Right")
        result = self.pointer.process(snapshot(1.06, hand()), 1.07)
        self.assertEqual(result.status, "TRACKING")

    def test_stale_frame_cannot_move_pointer(self):
        first = self.pointer.process(snapshot(1, hand()), 1.01)
        result = self.pointer.process(snapshot(1.03, hand(tip=(1, 1))), 1.2)
        self.assertEqual(result.position, first.position)
        self.assertEqual(result.status, "HOLD")

    def test_invalid_landmarks_do_not_poison_filter(self):
        invalid = replace(hand(), landmarks=((math.nan, 0, 0),) * 21)
        self.assertEqual(self.pointer.process(snapshot(1, invalid), 1.01).status, "WAITING")
        result = self.pointer.process(snapshot(1.03, hand()), 1.04)
        self.assertTrue(all(math.isfinite(v) for v in result.position))

    def test_future_timestamp_does_not_block_later_valid_frame(self):
        self.assertEqual(self.pointer.process(snapshot(100, hand()), 1).status, "WAITING")
        self.assertEqual(self.pointer.process(snapshot(1.03, hand()), 1.04).status, "TRACKING")

    def test_small_jitter_is_held_but_slow_motion_accumulates(self):
        pointer = VirtualPointer(Settings(pointer_dead_zone=0.01, pointer_mode='INDEX', pointer_anchor='INDEX'))
        initial = pointer.process(snapshot(1, hand()), 1.001).position
        for i in range(1, 20):
            result = pointer.process(snapshot(1+i/30, hand(tip=(0.5+0.001*(-1)**i, 0.5))), 1+i/30+0.001)
            self.assertEqual(result.position, initial)
        for i in range(20, 80):
            result = pointer.process(snapshot(1+i/30, hand(tip=(0.5+(i-20)*0.002, 0.5))), 1+i/30+0.001)
        self.assertLess(result.position[0], initial[0] - 0.1)

    def test_all_desktop_corners_are_reachable(self):
        for tip, expected in (((0, 0), (1, 0)), ((1, 0), (0, 0)),
                              ((0, 1), (1, 1)), ((1, 1), (0, 1))):
            pointer = VirtualPointer(Settings(pointer_mode='INDEX', pointer_anchor='INDEX'))
            pointer.process(snapshot(1, hand()), 1.001)
            for i in range(1, 100):
                result = pointer.process(snapshot(1+i/30, hand(tip=tip)), 1+i/30+0.001)
            self.assertEqual(result.position, expected)

    def test_preview_mirroring_cannot_change_control_mapping(self):
        a = VirtualPointer(Settings(preview_mirrored=True))
        b = VirtualPointer(Settings(preview_mirrored=False))
        frame = snapshot(1, hand(tip=(0.3, 0.5)))
        self.assertEqual(a.process(frame, 1.01).position, b.process(frame, 1.01).position)

    def test_resizing_keeps_owner_and_hand_preference_change_resets(self):
        self.pointer.process(snapshot(1, hand()), 1.01)
        self.pointer.resize_area(-0.05)
        self.assertAlmostEqual(self.pointer.area.right - self.pointer.area.left, 0.55)
        self.assertEqual(self.pointer.snapshot.handedness, "Right")
        self.pointer.cycle_hand()
        self.assertEqual(self.pointer.preference, "LEFT")
        self.assertEqual(self.pointer.snapshot.status, "WAITING")
