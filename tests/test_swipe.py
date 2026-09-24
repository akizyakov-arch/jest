from dataclasses import replace
import math
import ctypes as ct
from types import SimpleNamespace
import unittest
from gesture_control.settings import Settings
from gesture_control.swipe import SwipeGesture, wrist_direction, WristFlick
from gesture_control.events import CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.native_cursor import WindowsCursorBackend, Input
from gesture_control.profiles import load_profiles
from test_interaction import pose_hand
from test_palm_navigation import Desktop, shifted
from test_pinch import pinched_hand


def turned(hand, angle):
    # Rotate around a fixed wrist in physical image coordinates.
    wx,wy,_=hand.landmarks[0]
    c,s=math.cos(angle),math.sin(angle)
    points=[]
    for x,y,z in hand.landmarks:
        dx,dy=(x-wx)*640,(y-wy)*480
        points.append((wx+(dx*c-dy*s)/640,wy+(dx*s+dy*c)/480,z))
    return replace(hand,landmarks=tuple(points))


def turned_in_depth(hand, angle):
    wx,_,wz=hand.landmarks[0]
    c,s=math.cos(angle),math.sin(angle)
    return replace(hand,landmarks=tuple(
        (wx+(x-wx)*c+(z-wz)*s,y,wz-(x-wx)*s+(z-wz)*c)
        for x,y,z in hand.landmarks))


class SwipeTests(unittest.TestCase):
    def test_depth_turn_and_return_fire_only_once(self):
        for mirror in (False,True):
            for direction in (-1,1):
                gate=WristFlick(replace(Settings(),preview_mirrored=mirror))
                angles=[direction*math.radians(45)*i/15 for i in range(16)]
                angles += list(reversed(angles))
                events=[gate.update(turned_in_depth(pose_hand('OPEN_PALM'),a),640,480,1+i/30)
                        for i,a in enumerate(angles)]
                expected='RIGHT' if direction*(-1 if mirror else 1)>0 else 'LEFT'
                self.assertEqual([e for e in events if e],[expected])

    def test_slow_depth_turn_and_depth_jitter_do_not_fire(self):
        for angles in ([math.radians(45)*i/90 for i in range(91)],
                       [math.radians(4)*(-1)**i for i in range(60)]):
            gate=WristFlick(Settings())
            self.assertFalse(any(gate.update(turned_in_depth(pose_hand('OPEN_PALM'),a),640,480,1+i/30)
                                 for i,a in enumerate(angles)))

    def test_wrist_direction_ignores_translation_and_scale(self):
        hand=pose_hand('OPEN_PALM')
        expected=wrist_direction(hand,640,480)
        moved=replace(hand,landmarks=tuple((x*.7+.1,y*.7+.1,z) for x,y,z in hand.landmarks))
        for a,b in zip(expected,wrist_direction(moved,640,480)):
            self.assertAlmostEqual(a,b)

    def test_one_event_per_stroke_and_stop_rearms(self):
        swipe=SwipeGesture(replace(Settings(),swipe_min_distance=.16,swipe_min_speed=.65))
        results=[swipe.update(True,(.1+i*.025,.5),1+i/30) for i in range(22)]
        self.assertEqual([r for r in results if r], ['RIGHT'])
        for i in range(15):
            swipe.update(True,(.625,.5),1+(22+i)/30)
        results=[swipe.update(True,(.625-i*.03,.5),1+(37+i)/30) for i in range(10)]
        self.assertEqual([r for r in results if r], ['LEFT'])

    def test_slow_vertical_diagonal_and_short_movements_are_rejected(self):
        for dx,dy,count in ((.004,0,90),(0,.04,12),(.03,.03,12),(.01,0,10)):
            swipe=SwipeGesture(replace(Settings(),swipe_min_distance=.16,swipe_min_speed=.65))
            self.assertFalse(any(swipe.update(True,(.2+i*dx,.2+i*dy),1+i/30) for i in range(count)))

    def test_long_idle_before_swipe_does_not_dilute_speed(self):
        swipe=SwipeGesture(replace(Settings(),swipe_min_distance=.16,swipe_min_speed=.65))
        for i in range(60):
            swipe.update(True,(.2,.5),1+i/30)
        results=[swipe.update(True,(.2+i*.03,.5),3+i/30) for i in range(9)]
        self.assertIn('RIGHT',results)

    def test_frame_gap_cannot_complete_stroke(self):
        swipe=SwipeGesture(replace(Settings(),swipe_min_distance=.16,swipe_min_speed=.65))
        swipe.update(True,(.2,.5),1)
        swipe.update(True,(.3,.5),1.05)
        self.assertIsNone(swipe.update(True,(.5,.5),1.5))


class SwipeInteractionTests(unittest.TestCase):
    def setUp(self):
        self.now=1.
        self.backend=Desktop()
        self.session=InteractionSession(Settings(),load_profiles(),clock=lambda:self.now,cursor_backend=self.backend)
        self.session.hotkey_ready=True
        self.feed(pose_hand('OPEN_PALM'),30)
        self.backend.commands.clear()

    def tearDown(self):
        self.session.close()

    def feed(self,hand,count=1):
        for _ in range(count):
            self.now+=1/30
            self.session.process(TrackingSnapshot(round(self.now*1000),self.now,self.now,
                () if hand is None else (hand,)),self.now,640,480)

    def stroke(self,sign=1,pose='OPEN_PALM'):
        for i in range(6):
            self.feed(turned(pose_hand(pose),sign*i*.1))

    def keys(self):
        return [(c.type,c.key) for c in self.backend.commands if c.key]

    def test_mirrored_directions_release_all_keys(self):
        self.stroke(-1)
        self.assertEqual(self.keys(),[(CommandType.KEY_DOWN,'ALT'),(CommandType.KEY_DOWN,'TAB'),
                                     (CommandType.KEY_UP,'TAB'),(CommandType.KEY_UP,'ALT')])
        self.assertFalse(self.session.machine.commands.keys)
        self.feed(pose_hand('OPEN_PALM'),20)
        self.backend.commands.clear()
        self.stroke(1)
        self.assertEqual([k for t,k in self.keys() if t==CommandType.KEY_DOWN],['ALT','SHIFT','TAB'])
        self.assertEqual([k for t,k in self.keys() if t==CommandType.KEY_UP],['TAB','SHIFT','ALT'])

    def test_left_hand_alone_uses_reverse_switch_with_blue_rune(self):
        self.session.close()
        self.backend = Desktop()
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda:self.now,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True
        left = replace(pose_hand('OPEN_PALM'), hand_id='Left', handedness='Left')
        self.feed(left, 30)
        self.backend.commands.clear()
        for i in range(7):
            self.feed(turned(left, -i*.1))
        self.assertEqual([k for t,k in self.keys() if t==CommandType.KEY_DOWN], ['ALT','SHIFT','TAB'])
        self.assertFalse(self.session.machine.commands.keys)

    def test_moderate_45_degree_depth_turn_sends_shortcut(self):
        for i in range(16):
            self.feed(turned_in_depth(pose_hand('OPEN_PALM'),-math.radians(45)*i/15))
        self.assertEqual([k for t,k in self.keys() if t==CommandType.KEY_DOWN],['ALT','TAB'])
        self.assertFalse(self.session.machine.commands.keys)

    def test_palm_navigation_and_left_capture_cannot_switch_windows(self):
        for i in range(10):
            self.feed(shifted(pose_hand('OPEN_PALM'),-i*.01))
        self.assertFalse(self.keys())
        self.feed(pose_hand('OPEN_PALM'),20)
        self.feed(pinched_hand(),5)
        self.assertTrue(self.session.machine.commands.buttons)
        for i in range(6):
            self.feed(shifted(pinched_hand(),-i*.05))
        self.assertFalse(self.keys())

    def test_keyboard_does_not_open_from_holding_after_swipe(self):
        self.stroke(-1)
        self.feed(turned(pose_hand('OPEN_PALM'),-.5),60)
        self.assertFalse(self.session.take_keyboard_request())
        self.assertEqual(len(self.keys()),4)

    def test_three_fingers_no_longer_switch_windows(self):
        self.feed(pose_hand('THREE_FINGERS'),60)
        self.assertFalse(self.keys())

    def test_fast_translation_without_wrist_turn_does_not_switch(self):
        for i in range(6):
            self.feed(shifted(pose_hand('OPEN_PALM'),-i*.05))
        self.assertFalse(self.keys())

    def test_slow_wrist_turn_does_not_switch(self):
        for i in range(50):
            self.feed(turned(pose_hand('OPEN_PALM'),-i*.01))
        self.assertFalse(self.keys())

    def test_flick_with_bent_fingertips(self):
        hand=pose_hand('OPEN_PALM')
        points=list(hand.landmarks)
        for mcp in (5,9,13,17):
            x,y,z=points[mcp]
            points[mcp+3]=(x,y-.16,z)
        bent=replace(hand,landmarks=tuple(points))
        # Establish the relaxed pose before moving, rather than simulating
        # simultaneous sudden fingertip closure (a potential click).
        self.feed(bent,20)
        self.backend.commands.clear()
        for i in range(6):
            self.feed(turned(bent,-i*.1))
        self.assertEqual([key for kind,key in self.keys() if kind==CommandType.KEY_DOWN],['ALT','TAB'])

    def test_switch_fires_during_motion_and_navigation_continues(self):
        for i in range(5):
            self.feed(turned(pose_hand('OPEN_PALM'),-i*.1))
        self.assertEqual(len(self.keys()),4)
        self.assertFalse(self.session.swipe.armed)
        self.backend.commands.clear()
        for i in range(1,6):
            self.feed(shifted(turned(pose_hand('OPEN_PALM'),-.4),-i*.005))
        self.assertTrue(any(c.type == CommandType.POINTER_MOVE for c in self.backend.commands))
        self.assertFalse(self.keys())

    def test_disabled_swipe_emits_no_shortcuts(self):
        self.session.close()
        self.session=InteractionSession(replace(Settings(),gesture_swipe=False),load_profiles(),
            clock=lambda:self.now,cursor_backend=self.backend)
        self.session.hotkey_ready=True
        self.feed(pose_hand('OPEN_PALM'),30)
        self.backend.commands.clear()
        self.stroke(-1)
        self.assertFalse(self.keys())

    def test_partial_shortcut_failure_releases_owned_modifiers(self):
        send=self.backend.send
        def fail(command):
            if command.key=='TAB':
                raise OSError('simulated failure')
            return send(command)
        self.backend.send=fail
        with self.assertLogs(level='ERROR'):
            self.stroke(1)
        self.assertEqual(self.session.view().state,'PAUSED')
        self.assertTrue(any({'ALT','SHIFT'} <= keys for _,keys in self.backend.releases))

    def test_native_cleanup_attempts_all_keys_even_if_one_release_fails(self):
        sent=[]
        def send(count,pointer,size):
            key=ct.cast(pointer,ct.POINTER(Input)).contents.data.ki.wVk
            sent.append(key)
            return 0 if key==9 else 1
        backend=WindowsCursorBackend.__new__(WindowsCursorBackend)
        backend.user32=SimpleNamespace(SendInput=send)
        with self.assertRaises(OSError):
            backend.release(frozenset(),frozenset({'TAB','SHIFT','ALT'}))
        self.assertEqual(sent,[9,16,18])
