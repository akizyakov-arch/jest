from dataclasses import replace
from unittest import TestCase

from gesture_control.settings import Settings
from gesture_control.workspace_gesture import WorkspaceGesture
from test_two_hand import hand
from test_right_pinch import right_hand

def triple_hand():
    return right_hand(ambiguous=True)


class WorkspaceComfortTests(TestCase):
    def test_pause_does_not_rearm_without_opening_hand(self):
        gesture,h,events=self.stroke(-1,1.4)
        self.assertEqual(events,['TASK_VIEW'])
        for i in range(1,61):
            self.assertIsNone(gesture.update(h,(.5,.38),2.4+i/60,640,480))
        for i in range(1,61):
            self.assertIsNone(gesture.update(h,(.5,.38+i*.002),3.4+i/60,640,480))
        gesture.update(hand(),(.5,.5),4.5,640,480)
        for i in range(26):
            gesture.update(h,(.5,.5),4.6+i/60,640,480)
        events=[gesture.update(h,(.5,.5+i*.002),5.1+i/60,640,480) for i in range(61)]
        self.assertEqual([e for e in events if e],['SHOW_DESKTOP'])

    def stroke(self, direction, duration, dx=0, relaxed=False):
        gesture = WorkspaceGesture(Settings())
        h = triple_hand()
        for i in range(26):
            gesture.update(h, (.5,.5), .5+i/60, 640,480)
        events = []
        count = round(duration*60)
        for i in range(count+1):
            event = gesture.update(h, (.5+dx*i/count, .5+direction*.12*i/count),
                                   1+i/60, 640, 480)
            if event:
                events.append(event)
        return gesture, h, events

    def test_slow_short_triple_strokes_both_directions(self):
        for direction, expected in ((-1, 'TASK_VIEW'), (1, 'SHOW_DESKTOP')):
            with self.subTest(direction=direction):
                _, _, events = self.stroke(direction, 1.4, dx=.04, relaxed=True)
                self.assertEqual(events, [expected])

    def test_fast_strokes_still_work(self):
        self.assertEqual(self.stroke(-1, .2)[2], ['TASK_VIEW'])

    def test_stationary_jitter_does_not_fire(self):
        gesture = WorkspaceGesture(Settings())
        for i in range(180):
            self.assertIsNone(gesture.update(triple_hand(),
                (.5+.002*(-1)**i, .5+.003*(-1)**i), 1+i/60, 640, 480))

    def test_ready_gesture_requires_small_motion_before_action(self):
        gesture = WorkspaceGesture(Settings())
        h = triple_hand()
        for i in range(26):
            gesture.update(h, (.5, .5), .5+i/60, 640, 480)
        self.assertTrue(gesture.ready)
        self.assertIsNone(gesture.update(h, (.5, .5), 1.0, 640, 480))
        self.assertIsNotNone(gesture.update(h, (.5, .42), 1.1, 640, 480))

    def test_open_thumb_navigation_does_not_fire(self):
        gesture = WorkspaceGesture(Settings())
        for i in range(90):
            self.assertIsNone(gesture.update(hand(), (.5, .5-i*.002), 1+i/60, 640, 480))

    def test_immediate_return_does_not_fire_opposite_command(self):
        gesture, h, events = self.stroke(-1, 1.4)
        self.assertEqual(events, ['TASK_VIEW'])
        for i in range(1, 61):
            self.assertIsNone(gesture.update(h, (.5, .38+i*.002), 2.4+i/60, 640, 480))
