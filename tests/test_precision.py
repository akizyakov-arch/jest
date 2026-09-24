from unittest import TestCase
from gesture_control.cursor import CursorMotion


class PrecisionTests(TestCase):
    def test_stationary_subpixel_jitter_is_suppressed(self):
        motion=CursorMotion(3,70,True)
        motion.step((.5,.5),1,(.5,.5))
        for i in range(1,60):
            point=motion.step((.5+(-1)**i*.00015,.5),1+i/60)
            self.assertEqual(point,(.5,.5))

    def test_slow_intentional_motion_accumulates_and_edges_remain_reachable(self):
        motion=CursorMotion(3,70,True)
        motion.step((.5,.5),1,(.5,.5))
        for i in range(1,61):
            point=motion.step((.5+i*.0001,.5),1+i/60)
        self.assertGreater(point[0],.504)
        for i in range(1,181):
            point=motion.step((1,0),2+i/60)
        self.assertEqual(point,(1,0))

    def test_fast_movement_has_less_lag_without_overshoot(self):
        normal=CursorMotion(4,70)
        precise=CursorMotion(4,70,True)
        for motion in (normal,precise):motion.step((.5,.5),1,(.5,.5))
        for i in range(1,21):
            target=(.5+i*.008,.5)
            a=normal.step(target,1+i/60)
            b=precise.step(target,1+i/60)
            self.assertLessEqual(b[0],target[0])
        self.assertGreater(b[0],a[0])
