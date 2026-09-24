from dataclasses import replace
from unittest import TestCase
from gesture_control.secondary_clicks import SecondaryClicks
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_scroll import two_fingers


class SecondaryClickTests(TestCase):
    def setUp(self):
        self.clicks=SecondaryClicks(Settings())
        self.time=1.
        self.feed(pose_hand('OPEN_PALM'),5)

    def feed(self, hand, count):
        events=[]
        for _ in range(count):
            self.time+=1/30
            button,_=self.clicks.update(hand,self.time,640,480)
            if button: events.append(button)
        return events

    def pinched_pair(self, tip):
        hand=two_fingers()
        points=list(hand.landmarks)
        points[4]=points[tip]
        return replace(hand,landmarks=tuple(points))

    def test_short_pinch_with_two_raised_fingers_is_not_middle_click(self):
        for tip,expected in ((8,'left'),(12,'right')):
            self.setUp()
            self.assertEqual(self.feed(self.pinched_pair(tip),3),[])
            self.assertEqual(self.feed(pose_hand('OPEN_PALM'),3),[expected])

    def test_one_frame_contact_is_not_a_click(self):
        self.feed(self.pinched_pair(8),1)
        self.assertEqual(self.feed(pose_hand('OPEN_PALM'),5),[])

    def test_loss_cancels_short_pinch(self):
        self.feed(self.pinched_pair(8),3)
        self.feed(None,1)
        self.assertEqual(self.feed(pose_hand('OPEN_PALM'),5),[])

    def test_middle_requires_open_thumb_and_does_not_repeat(self):
        self.assertEqual(self.feed(two_fingers(),15),['middle'])
        self.assertEqual(self.feed(self.pinched_pair(8),15),[])
        self.assertEqual(self.feed(pose_hand('OPEN_PALM'),5),[])
