from dataclasses import replace
from unittest import TestCase
from gesture_control.settings import Settings
from gesture_control.interaction import InteractionSession
from gesture_control.profiles import load_profiles
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.events import CommandType,CommandEvent
from test_interaction import pose_hand
from test_pinch import pinched_hand
from test_fist import fist_hand
from test_right_pinch import right_hand
from test_palm_navigation import Desktop,shifted


def hand(side='Right',closed=False,dx=0,dy=0,four=False,fist=False,triple=False):
    h=fist_hand() if fist else (pinched_hand() if closed else pose_hand('OPEN_PALM'))
    if triple: h=right_hand(ambiguous=True)
    points=list(h.landmarks)
    if four:
        x,y,z=points[9]
        points[4]=(x,y+.04,z)
    return replace(h,hand_id=side,handedness=side,
        landmarks=tuple((x+dx,y+dy,z) for x,y,z in points))


class ExtendedGestureTests(TestCase):
    def test_primary_triple_pinch_ready_and_workspace_without_second_hand(self):
        self.session.settings=replace(self.session.settings,second_hand_enabled=False)
        for direction,key in ((-1,'TAB'),(1,'D')):
            self.feed(hand(dx=-.2),count=15)
            self.backend.commands.clear()
            self.feed(hand(dx=-.2,triple=True),count=12)
            self.assertTrue(self.session.primary_workspace.ready)
            for i in range(15):
                self.feed(hand(dx=-.2,dy=direction*i*.012,triple=True))
            self.assertEqual(self.keys(),[(CommandType.KEY_DOWN,'WIN'),(CommandType.KEY_DOWN,key),
                                         (CommandType.KEY_UP,key),(CommandType.KEY_UP,'WIN')])
            self.assertFalse([c for c in self.backend.commands if c.button])

    def test_both_triple_pinches_do_not_zoom_or_duplicate_workspace_command(self):
        self.feed(hand(dx=-.2,triple=True),hand('Left',dx=.2,triple=True),count=12)
        self.assertTrue(self.session.primary_workspace.ready)
        self.assertFalse(self.session.workspace.ready)
        for i in range(15):
            self.feed(hand(dx=-.2,dy=-i*.012,triple=True),hand('Left',dx=.2,dy=-i*.012,triple=True))
        self.assertEqual(self.keys(),[(CommandType.KEY_DOWN,'WIN'),(CommandType.KEY_DOWN,'TAB'),
                                     (CommandType.KEY_UP,'TAB'),(CommandType.KEY_UP,'WIN')])
        self.assertNotEqual(self.session.two_hand.phase,'ZOOM')
        self.assertFalse([c for c in self.backend.commands if c.button])

    def test_workspace_disabled_prevents_primary_gold_and_command(self):
        self.session.settings=replace(self.session.settings,gesture_workspace=False)
        self.feed(hand(dx=-.2,triple=True),count=15)
        for i in range(15):self.feed(hand(dx=-.2,dy=-i*.012,triple=True))
        self.assertFalse(self.session.primary_workspace.ready)
        self.assertFalse(self.keys())

    def test_secondary_fist_no_longer_opens_workspace(self):
        self.feed(hand(dx=-.2),hand('Left',dx=.2,fist=True),count=20)
        for i in range(15):
            self.feed(hand(dx=-.2),hand('Left',dx=.2,dy=-i*.012,fist=True))
        self.assertFalse(self.keys())

    def test_triple_pinch_partial_open_does_not_click_or_rearm(self):
        self.pair(count=10)
        self.feed(hand(dx=-.2),hand('Left',dx=.2,triple=True),count=16)
        self.assertTrue(self.session.workspace.ready)
        for i in range(12):
            self.feed(hand(dx=-.2),hand('Left',dx=.2,dy=-i*.012,triple=True))
        self.assertTrue(self.session.workspace.used)
        self.feed(hand(dx=-.2),hand('Left',dx=.2,closed=True),count=10)
        self.assertTrue(self.session.workspace.used)
        self.pair(count=10)
        self.assertFalse(self.session.workspace.used)
        self.assertFalse([c for c in self.backend.commands if c.button])

    def test_remaining_left_hand_becomes_blue_and_returning_right_is_red(self):
        self.pair(count=10)
        self.assertEqual(self.session.pointer.snapshot.handedness,'Right')
        self.feed(hand('Left',dx=.2),count=45)
        self.assertEqual(self.session.view().state,'ACTIVE')
        self.assertEqual(self.session.pointer.snapshot.handedness,'Left')
        self.assertIsNone(self.session.secondary_position)
        self.pair(count=10)
        self.assertEqual(self.session.pointer.snapshot.handedness,'Left')
        self.assertIsNotNone(self.session.secondary_position)
        self.feed(hand(dx=-.2),count=45)
        self.assertEqual(self.session.view().state,'ACTIVE')
        self.assertEqual(self.session.pointer.snapshot.handedness,'Right')
        self.assertIsNone(self.session.secondary_position)

    def setUp(self):
        self.now=1.
        self.backend=Desktop()
        self.session=InteractionSession(Settings(second_hand_enabled=True),load_profiles(),
            clock=lambda:self.now,cursor_backend=self.backend)
        self.session.hotkey_ready=True
        self.addCleanup(self.session.close)
        self.feed(hand(dx=-.2),count=30)
        self.backend.commands.clear()

    def feed(self,*hands,count=1):
        for _ in range(count):
            self.now+=1/30
            self.session.process(TrackingSnapshot(round(self.now*1000),self.now,self.now,tuple(hands)),
                                 self.now,640,480)

    def pair(self,closed=False,extra=0,count=1,reverse=False):
        hands=(hand(closed=closed,dx=-.2-extra),hand('Left',closed,dx=.2+extra))
        self.feed(*(tuple(reversed(hands)) if reverse else hands),count=count)

    def keys(self):
        return [(c.type,c.key) for c in self.backend.commands if c.key]

    def test_zoom_has_no_preliminary_click_and_releases_ctrl_each_packet(self):
        self.pair(count=10)
        self.pair(True,count=12)
        self.assertEqual(self.session.two_hand.phase,'ZOOM')
        for i in range(1,7):self.pair(True,extra=i*.02,reverse=i%2==0)
        self.assertFalse(any(c.type==CommandType.POINTER_DOWN for c in self.backend.commands))
        wheel=[c.wheel_units for c in self.backend.commands if c.type==CommandType.SCROLL]
        self.assertTrue(wheel)
        self.assertTrue(all(v>0 for v in wheel))
        self.assertEqual(self.keys()[0],(CommandType.KEY_DOWN,'CTRL'))
        self.assertEqual(self.keys()[-1],(CommandType.KEY_UP,'CTRL'))
        self.assertFalse(self.session.machine.commands.keys)
        self.assertIsNotNone(self.session.secondary_position)

    def test_lost_secondary_ends_zoom_without_click(self):
        self.pair(count=10);self.pair(True,count=12)
        self.feed(hand(closed=True,dx=-.2),count=10)
        self.assertEqual(self.session.two_hand.phase,'EXIT')
        self.assertIsNone(self.session.secondary_position)
        self.assertFalse(any(c.type==CommandType.POINTER_DOWN for c in self.backend.commands))
        self.feed(hand(dx=-.2),count=12)
        self.assertEqual(self.session.two_hand.phase,'IDLE')

    def test_zoom_inward_emits_negative_wheel(self):
        self.pair(count=10);self.pair(True,count=12)
        for i in range(1,6):self.pair(True,extra=-i*.015)
        wheel=[c.wheel_units for c in self.backend.commands if c.type==CommandType.SCROLL]
        self.assertTrue(wheel)
        self.assertTrue(all(v<0 for v in wheel))
        self.assertFalse(self.session.machine.commands.keys)

    def test_secondary_jump_cancels_zoom(self):
        self.pair(count=10);self.pair(True,count=12)
        self.feed(hand(closed=True,dx=-.2),hand('Left',True,dx=.2,dy=-.25))
        self.assertNotEqual(self.session.two_hand.phase,'ZOOM')
        # Visual feedback can remain even when the stricter Zoom pair is lost.
        self.assertIsNotNone(self.session.secondary_position)

    def test_two_fingers_with_thumb_contact_are_pinch_for_zoom(self):
        from test_scroll import two_fingers
        self.pair(count=10)
        h=two_fingers()
        points=list(h.landmarks)
        points[4]=points[8]
        h=replace(h,hand_id='Right',landmarks=tuple((x-.2,y,z) for x,y,z in points))
        self.feed(h,hand('Left',True,dx=.2),count=20)
        middle=[c.type for c in self.backend.commands if c.button=='middle']
        self.assertEqual(middle,[])
        self.assertEqual(self.session.two_hand.phase,'ZOOM')
        self.assertIsNotNone(self.session.secondary_position)

    def test_short_left_and_right_clicks_work_on_either_hand_with_two_visible(self):
        for secondary in (False,True):
            for button,pose in (('left',pinched_hand()),('right',right_hand())):
                with self.subTest(secondary=secondary,button=button):
                    self.pair(count=15)
                    self.backend.commands.clear()
                    target=replace(shifted(pose,.2 if secondary else -.2),
                                   hand_id='Left' if secondary else 'Right',
                                   handedness='Left' if secondary else 'Right')
                    self.feed(hand(dx=-.2) if secondary else target,
                              target if secondary else hand('Left',dx=.2),count=3)
                    self.pair(count=5)
                    self.assertEqual([(c.type,c.button) for c in self.backend.commands if c.button],
                        [(CommandType.POINTER_DOWN,button),(CommandType.POINTER_UP,button)])

    def test_primary_index_pinch_with_middle_raised_clicks_left(self):
        from test_scroll import two_fingers
        h=two_fingers()
        points=list(h.landmarks)
        points[4]=points[8]
        primary=replace(h,hand_id='Right',handedness='Right',
                        landmarks=tuple((x-.2,y,z) for x,y,z in points))
        self.pair(count=15)
        self.backend.commands.clear()
        self.feed(primary,hand('Left',dx=.2),count=3)
        self.pair(count=3)
        self.assertEqual([(c.type,c.button) for c in self.backend.commands if c.button],
            [(CommandType.POINTER_DOWN,'left'),(CommandType.POINTER_UP,'left')])

    def test_low_side_confidence_shows_rune_but_does_not_zoom(self):
        secondary=replace(hand('Left',True,dx=.2),handedness_score=.5)
        self.feed(hand(closed=True,dx=-.2),secondary,count=20)
        self.assertIsNotNone(self.session.secondary_position)
        self.assertNotEqual(self.session.two_hand.phase,'ZOOM')

    def test_workspace_option_off_and_owned_button_block_shortcuts(self):
        self.session.settings=replace(self.session.settings,gesture_workspace=False)
        for i in range(9):self.feed(hand(dx=-.2,dy=-i*.025,four=True))
        self.assertFalse(self.keys())
        self.feed(hand(dx=-.2),count=20)
        self.session.settings=replace(self.session.settings,gesture_workspace=True)
        self.feed(hand(closed=True,dx=-.2),count=5)
        self.assertTrue(self.session.machine.commands.buttons)
        # Hold the pinch while moving: no Win commands may interrupt a drag.
        for i in range(9):self.feed(hand(closed=True,dx=-.2,dy=-i*.025))
        self.assertFalse(self.keys())

    def test_existing_drag_blocks_zoom(self):
        self.feed(hand(closed=True,dx=-.2),count=5)
        self.assertTrue(self.session.machine.commands.buttons)
        self.pair(True,count=20)
        self.assertNotEqual(self.session.two_hand.phase,'ZOOM')
        self.assertFalse(self.keys())

    def test_primary_click_still_works_with_open_second_hand(self):
        self.pair(count=10)
        self.feed(hand(closed=True,dx=-.2),hand('Left',dx=.2),count=15)
        self.assertIn('left',self.session.machine.commands.buttons)

    def test_option_off_has_no_second_rune_or_zoom(self):
        self.session.settings=replace(self.session.settings,second_hand_enabled=False)
        self.pair(count=10);self.pair(True,count=12)
        self.assertIsNone(self.session.secondary_position)
        self.assertFalse(self.keys())

    def test_secondary_triple_pinch_up_and_down(self):
        for direction,key in ((-1,'TAB'),(1,'D')):
            self.feed(hand(dx=-.2),count=20)
            self.backend.commands.clear()
            self.feed(hand(dx=-.2), hand('Left',dx=.2,triple=True), count=16)
            for i in range(9):self.feed(hand(dx=-.2),hand('Left',dx=.2,dy=direction*i*.025,triple=True))
            self.assertEqual(self.keys(),[(CommandType.KEY_DOWN,'WIN'),(CommandType.KEY_DOWN,key),
                                         (CommandType.KEY_UP,key),(CommandType.KEY_UP,'WIN')])
            self.assertFalse(self.session.machine.commands.keys)

    def test_normal_palm_vertical_navigation_does_not_open_task_view(self):
        for i in range(9):self.feed(hand(dx=-.2,dy=-i*.025))
        self.assertFalse(self.keys())

    def test_slow_triple_pinch_sends_exactly_one_shortcut_per_stroke(self):
        for direction, key in ((-1, 'TAB'), (1, 'D')):
            self.feed(hand(dx=-.2), count=20)
            self.backend.commands.clear()
            self.feed(hand(dx=-.2), hand('Left',dx=.2,triple=True), count=16)
            for i in range(43):
                self.feed(hand(dx=-.2), hand('Left',dx=.2+i*.0008, dy=direction*i*.12/42, triple=True))
            self.assertEqual(self.keys(), [(CommandType.KEY_DOWN, 'WIN'), (CommandType.KEY_DOWN, key),
                                          (CommandType.KEY_UP, key), (CommandType.KEY_UP, 'WIN')])
            self.assertFalse(self.session.machine.commands.keys)

    def test_primary_four_fingers_never_invoke_workspace(self):
        self.feed(hand(dx=-.2,four=True),hand('Left',dx=.2),count=15)
        for i in range(43):
            self.feed(hand(dx=-.2,dy=-i*.003,four=True),hand('Left',dx=.2))
        self.assertFalse(self.keys())

    def test_secondary_workspace_requires_stationary_confirmation(self):
        for i in range(9):
            self.feed(hand(dx=-.2),hand('Left',dx=.2,dy=-i*.025,triple=True))
        self.assertFalse(self.keys())

    def test_secondary_left_right_click_and_loss_cancel(self):
        from test_right_pinch import right_hand
        for button, closed in (('left',hand('Left',True,dx=.2)),
                               ('right',replace(shifted(right_hand(),.2),hand_id='Left',handedness='Left'))):
            self.pair(count=10)
            self.backend.commands.clear()
            self.feed(hand(dx=-.2),closed,count=8)
            self.assertEqual(self.session.machine.commands.buttons, {'left'} if button == 'left' else set())
            self.pair(count=5)
            clicks=[(c.type,c.button) for c in self.backend.commands if c.button]
            self.assertEqual(clicks,[(CommandType.POINTER_DOWN,button),(CommandType.POINTER_UP,button)])
        self.pair(count=10)
        self.backend.commands.clear()
        self.feed(hand(dx=-.2),hand('Left',True,dx=.2),count=8)
        self.feed(hand(dx=-.2),count=3)
        self.pair(count=10)
        self.assertEqual([(c.type,c.button) for c in self.backend.commands if c.button],
                         [(CommandType.POINTER_DOWN,'left'),(CommandType.POINTER_UP,'left')])
        self.assertFalse(self.session.machine.commands.buttons)

    def test_secondary_middle_click_once_without_hold_or_drag(self):
        from test_scroll import two_fingers
        self.pair(count=10)
        secondary=replace(shifted(two_fingers(),.2),hand_id='Left',handedness='Left')
        self.feed(hand(dx=-.2),secondary,count=30)
        clicks=[(c.type,c.button) for c in self.backend.commands if c.button]
        self.assertEqual(clicks,[(CommandType.POINTER_DOWN,'middle'),(CommandType.POINTER_UP,'middle')])
        self.assertFalse(self.session.machine.commands.buttons)

    def test_secondary_clicks_use_red_rune_and_restore_blue(self):
        from test_right_pinch import right_hand
        from test_scroll import two_fingers
        for button, pose in (('left',pinched_hand()), ('right',right_hand()), ('middle',two_fingers())):
            self.pair(count=60)
            hover=self.backend.position
            clicks=[]
            targets=[]
            original=self.backend.send
            def record(command):
                if command.button:
                    self.assertEqual(command.position,self.backend.anchor()[0].pixels(self.session.secondary_position))
                    clicks.append((command.type,command.button,self.backend.position))
                    screen,_=self.backend.anchor()
                    targets.append(screen.normalized(screen.pixels(self.session.secondary_position)))
                return original(command)
            self.backend.send=record
            try:
                secondary=replace(shifted(pose,.2),hand_id='Left',handedness='Left')
                self.feed(hand(dx=-.2),secondary,count=10)
                self.assertNotEqual(self.session.secondary_position,hover)
                self.pair(count=5)
            finally:
                self.backend.send=original
            self.assertEqual(len(clicks),2)
            self.assertEqual(clicks,[(CommandType.POINTER_DOWN,button,targets[0]),
                                     (CommandType.POINTER_UP,button,targets[1])])
            self.assertNotEqual(targets[0],hover)
            if button=='middle':
                self.assertEqual(self.session.secondary_scroll_origin,hover)
                self.session._finish_secondary_scroll(self.now,'test-end')
            if button in ('left','right'):
                self.pair(count=10)
            for actual,expected in zip(self.backend.position,hover):
                self.assertAlmostEqual(actual,expected,places=3)

    def test_red_context_click_keeps_system_pointer_until_menu_can_read_it(self):
        self.pair(count=30)
        blue = self.backend.position
        red_pose = replace(shifted(right_hand(), .2), hand_id='Left', handedness='Left')
        self.feed(hand(dx=-.2), red_pose, count=10)
        for _ in range(10):
            self.pair()
            if self.session.secondary_context_origin is not None:
                break
        self.assertEqual(self.session.secondary_context_origin, blue)
        self.assertEqual(self.session.blue_overlay_position, blue)
        red = self.backend.position
        self.assertNotEqual(red, blue)
        self.backend.commands.clear()
        # Model an application reading cursor position on a later message loop
        # iteration, while the blue hand is still moving.
        self.feed(hand(dx=-.25), hand('Left', dx=.2), count=5)
        self.assertEqual(self.backend.position, red)
        self.assertFalse(self.backend.commands)
        self.pair(count=5)
        self.assertIsNone(self.session.secondary_context_origin)
        self.assertIsNone(self.session.blue_overlay_position)
        self.assertTrue(any('context-restore' in c.source_event_id for c in self.backend.commands))

    def test_red_quick_click_separates_hover_press_release_and_return_across_frames(self):
        self.pair(count=20)
        blue = self.backend.position
        events = []
        original = self.backend.send
        def record(command):
            events.append((self.now, command, self.backend.position))
            return original(command)
        self.backend.send = record
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=3)
        self.pair(count=12)
        target = next(e for e in events if e[1].source_event_id.endswith('-target'))
        down = next(e for e in events if e[1].type==CommandType.POINTER_DOWN)
        up = next(e for e in events if e[1].type==CommandType.POINTER_UP)
        restored = next(e for e in events if 'context-restore' in e[1].source_event_id)
        self.assertGreaterEqual(down[0]-target[0], .04)
        self.assertGreaterEqual(up[0]-down[0], .04)
        self.assertGreaterEqual(restored[0]-up[0], .12)
        self.assertNotEqual(down[2], blue)
        self.assertEqual(down[2], up[2])
        self.assertEqual(up[2], restored[2])
        self.assertFalse(self.session.machine.commands.buttons)

    def test_red_hand_lost_before_delayed_press_sends_no_click(self):
        self.pair(count=20)
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=3)
        self.assertIsNotNone(self.session.secondary_drag_origin)
        self.assertFalse(self.session.machine.commands.buttons)
        self.feed(hand(dx=-.2), count=10)
        self.assertFalse([c for c in self.backend.commands if c.button])
        self.assertIsNone(self.session.secondary_drag_origin)

    def test_pause_cancels_delayed_red_press(self):
        self.pair(count=20)
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=3)
        self.session.emergency_stop()
        self.pair(count=10)
        self.assertFalse([c for c in self.backend.commands if c.button])

    def test_pause_cancels_pending_red_context_restore(self):
        self.pair(count=30)
        red_pose = replace(shifted(right_hand(), .2), hand_id='Left', handedness='Left')
        self.feed(hand(dx=-.2), red_pose, count=10)
        for _ in range(10):
            self.pair()
            if self.session.secondary_context_origin is not None:
                break
        self.assertIsNotNone(self.session.secondary_context_origin)
        self.session.emergency_stop()
        self.assertIsNone(self.session.secondary_context_origin)
        self.backend.commands.clear()
        self.pair(count=15)
        self.assertFalse(self.backend.commands)

    def start_red_scroll(self):
        from test_scroll import two_fingers
        self.pair(count=30)
        origin=self.backend.position
        secondary=replace(shifted(two_fingers(),.2),hand_id='Left',handedness='Left')
        self.feed(hand(dx=-.2),secondary,count=8)
        self.assertEqual(self.session.secondary_scroll_origin,origin)
        self.pair(count=10)
        return origin

    def test_red_drag_holds_left_moves_only_with_owner_and_releases(self):
        self.pair(count=30)
        blue = self.backend.position
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=8)
        self.assertEqual(self.session.machine.commands.buttons, {'left'})
        self.assertEqual(self.session.blue_overlay_position, blue)
        red = self.backend.position
        self.feed(hand(dx=-.25), hand('Left', True, dx=.2), count=5)
        self.assertEqual(self.backend.position, red)
        for i in range(12):
            self.feed(hand(dx=-.25), hand('Left', True, dx=.2, dy=-i*.01))
        self.assertLess(self.backend.position[1], red[1]-.05)
        self.assertEqual(self.session.action, 'SECONDARY_DRAG')
        self.assertFalse(self.keys())
        self.feed(hand(dx=-.25), hand('Left', dx=.2, dy=-.11), count=3)
        self.assertFalse(self.session.machine.commands.buttons)
        self.assertIsNone(self.session.secondary_drag_origin)
        self.assertEqual([(c.type,c.button) for c in self.backend.commands if c.button],
                         [(CommandType.POINTER_DOWN,'left'),(CommandType.POINTER_UP,'left')])

    def test_red_drag_loss_requires_opening_before_regrab(self):
        self.pair(count=20)
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=8)
        self.feed(hand(dx=-.2), count=2)
        self.assertFalse(self.session.machine.commands.buttons)
        self.backend.commands.clear()
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=10)
        self.assertFalse([c for c in self.backend.commands if c.button])
        self.pair(count=8)
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=8)
        self.assertEqual(self.session.machine.commands.buttons, {'left'})

    def test_red_pinch_survives_side_confidence_dip_after_open_hand(self):
        self.pair(count=20)
        weak = replace(hand('Left',True,dx=.2), handedness_score=.4)
        self.feed(hand(dx=-.2), weak, count=15)
        self.assertEqual(self.session.machine.commands.buttons, {'left'})
        self.assertIsNotNone(self.session.secondary_drag_origin)
        self.feed(hand(dx=-.2), replace(hand('Left',dx=.2),handedness_score=.4), count=5)
        self.assertFalse(self.session.machine.commands.buttons)
        self.assertEqual([(c.type,c.button) for c in self.backend.commands if c.button],
                         [(CommandType.POINTER_DOWN,'left'),(CommandType.POINTER_UP,'left')])

    def test_unknown_low_confidence_red_hand_cannot_start_click(self):
        weak_open = replace(hand('Left',dx=.2), handedness_score=.4)
        weak_closed = replace(hand('Left',True,dx=.2), handedness_score=.4)
        self.feed(hand(dx=-.2), weak_open, count=12)
        self.feed(hand(dx=-.2), weak_closed, count=12)
        self.assertFalse([c for c in self.backend.commands if c.button])

    def test_red_rune_uses_optional_stabilization_and_clicks_at_displayed_position(self):
        self.session.close()
        self.backend = Desktop()
        self.session = InteractionSession(Settings(second_hand_enabled=True, suppress_jitter=True),
            load_profiles(), clock=lambda:self.now, cursor_backend=self.backend)
        self.addCleanup(self.session.close)
        self.session.hotkey_ready = True
        self.feed(hand(dx=-.2), count=30)
        self.pair(count=20)
        target = self.session.secondary_position
        for i in range(20):
            self.feed(hand(dx=-.2), hand('Left', dx=.2+(-1)**i*.0003))
            self.assertEqual(self.session.secondary_position, target)
        self.feed(hand(dx=-.2), hand('Left',True,dx=.2),count=8)
        down = [c for c in self.backend.commands if c.type==CommandType.POINTER_DOWN][-1]
        self.assertEqual(down.position, self.session.screen.pixels(self.session.secondary_position))

    def test_right_hand_can_drag_when_it_is_secondary(self):
        self.session.close()
        self.backend = Desktop()
        self.session = InteractionSession(Settings(second_hand_enabled=True), load_profiles(),
            clock=lambda:self.now, cursor_backend=self.backend)
        self.addCleanup(self.session.close)
        self.session.hotkey_ready = True
        self.feed(hand('Left',dx=-.2), count=30)
        self.feed(hand('Left',dx=-.2), hand('Right',dx=.2), count=10)
        self.feed(hand('Left',dx=-.2), hand('Right',True,dx=.2), count=8)
        self.assertEqual(self.session.machine.commands.buttons, {'left'})
        for i in range(10):
            self.feed(hand('Left',dx=-.2), hand('Right',True,dx=.2,dy=-i*.012))
        self.assertEqual(self.session.action, 'SECONDARY_DRAG')
        self.feed(hand('Left',dx=-.2), hand('Right',dx=.2,dy=-.108), count=4)
        self.assertFalse(self.session.machine.commands.buttons)

    def test_red_drag_cannot_be_stolen_by_zoom_and_pause_releases(self):
        self.pair(count=20)
        self.feed(hand(dx=-.2), hand('Left', True, dx=.2), count=8)
        self.pair(closed=True, count=15)
        self.assertEqual(self.session.machine.commands.buttons, {'left'})
        self.assertNotEqual(self.session.two_hand.phase, 'ZOOM')
        self.assertFalse(self.keys())
        self.session.emergency_stop()
        self.assertFalse(self.session.machine.commands.buttons)
        self.assertIsNone(self.session.secondary_drag_origin)

    def test_left_red_flick_switches_back_and_releases_modifiers(self):
        from test_swipe import turned
        self.pair(count=20)
        for i in range(7):
            self.feed(hand(dx=-.2), turned(hand('Left',dx=.2), -i*.1))
        self.assertEqual(self.keys(), [(CommandType.KEY_DOWN,'ALT'),(CommandType.KEY_DOWN,'SHIFT'),
            (CommandType.KEY_DOWN,'TAB'),(CommandType.KEY_UP,'TAB'),
            (CommandType.KEY_UP,'SHIFT'),(CommandType.KEY_UP,'ALT')])
        self.assertFalse(self.session.machine.commands.keys)

    def test_red_flick_disabled_during_primary_capture(self):
        from test_swipe import turned
        self.pair(count=20)
        self.feed(hand(closed=True,dx=-.2), hand('Left',dx=.2), count=8)
        for i in range(7):
            self.feed(hand(closed=True,dx=-.2), turned(hand('Left',dx=.2), -i*.1))
        self.assertFalse(self.keys())

    def test_red_scroll_follows_red_hand_not_blue(self):
        origin=self.start_red_scroll()
        red_position=self.backend.position
        for i in range(10):
            self.feed(hand(dx=-.2,dy=-i*.006),hand('Left',dx=.2))
        self.assertAlmostEqual(self.backend.position[1],red_position[1],places=3)
        for i in range(20):
            self.feed(hand(dx=-.2,dy=-.054),hand('Left',dx=.2,dy=i*.006))
        self.assertGreater(self.backend.position[1],red_position[1]+.05)
        self.assertEqual(self.session.secondary_scroll_origin,origin)
        self.assertEqual(self.session.action,'SECONDARY_SCROLL')

    def test_red_scroll_loss_sends_escape_and_restores_blue(self):
        origin=self.start_red_scroll()
        self.backend.commands.clear()
        self.feed(hand(dx=-.2),count=6)
        self.assertIsNone(self.session.secondary_scroll_origin)
        self.assertEqual(self.keys(),[(CommandType.KEY_DOWN,'ESC'),(CommandType.KEY_UP,'ESC')])
        self.assertEqual(self.backend.position,origin)

    def test_red_scroll_ignores_other_hand_pinch(self):
        self.start_red_scroll()
        self.backend.commands.clear()
        self.feed(hand(dx=-.2,closed=True),hand('Left',dx=.2),count=5)
        self.assertIsNotNone(self.session.secondary_scroll_origin)
        self.assertFalse([c for c in self.backend.commands if c.button])
        self.assertFalse(self.keys())

    def test_red_scroll_survives_brief_side_confidence_drop_and_missing_frame(self):
        self.start_red_scroll()
        self.backend.commands.clear()
        uncertain=replace(hand('Left',dx=.2),handedness_score=.5)
        self.feed(hand(dx=-.2),uncertain,count=30)
        self.feed(hand(dx=-.2))
        self.pair(count=3)
        self.assertIsNotNone(self.session.secondary_scroll_origin)
        self.assertFalse(self.keys())

    def test_blue_scroll_ignores_red_clicks_and_workspace(self):
        from test_scroll import two_fingers
        primary=replace(shifted(two_fingers(),-.2),hand_id='Right',handedness='Right')
        self.pair(count=15)
        self.feed(primary,hand('Left',dx=.2),count=8)
        self.assertTrue(self.session.primary_scroll_active)
        self.backend.commands.clear()
        for pose in (hand('Left',dx=.2,closed=True),hand('Left',dx=.2,triple=True),
                     replace(shifted(two_fingers(),.2),hand_id='Left',handedness='Left')):
            self.feed(hand(dx=-.2),pose,count=15)
        self.assertTrue(self.session.primary_scroll_active)
        self.assertFalse([c for c in self.backend.commands if c.button or c.key])

    def test_red_owner_click_ends_scroll_without_clicking_a_link(self):
        self.start_red_scroll()
        self.backend.commands.clear()
        self.feed(hand(dx=-.2),hand('Left',dx=.2,closed=True),count=4)
        self.pair(count=4)
        self.assertIsNone(self.session.secondary_scroll_origin)
        self.assertEqual(self.keys(),[(CommandType.KEY_DOWN,'ESC'),(CommandType.KEY_UP,'ESC')])
        self.assertFalse([c for c in self.backend.commands if c.button])

    def test_red_scroll_pause_sends_escape(self):
        self.start_red_scroll()
        self.backend.commands.clear()
        self.session.emergency_stop()
        self.assertIsNone(self.session.secondary_scroll_origin)
        self.assertEqual(self.keys(),[(CommandType.KEY_DOWN,'ESC'),(CommandType.KEY_UP,'ESC')])
        self.assertEqual(self.session.view().state,'PAUSED')

    def test_failed_red_positioning_never_sends_click(self):
        self.pair(count=10)
        original=self.backend.send
        def fail(command):
            if command.type==CommandType.POINTER_MOVE:
                raise OSError('test red positioning failure')
            return original(command)
        self.backend.send=fail
        with self.assertLogs(level='ERROR'):
            self.feed(hand(dx=-.2),hand('Left',True,dx=.2),count=8)
            self.pair(count=5)
        self.assertEqual(self.session.view().state,'PAUSED')
        self.assertFalse([c for c in self.backend.commands if c.button])

    def test_secondary_four_fingers_no_longer_invoke_workspace(self):
        self.feed(hand(dx=-.2),hand('Left',dx=.2,four=True),count=20)
        for i in range(15):
            self.feed(hand(dx=-.2),hand('Left',dx=.2,dy=-i*.012,four=True))
        self.assertFalse(self.keys())

    def test_secondary_triple_pinch_does_not_click_or_send_escape(self):
        self.pair(count=10)
        self.feed(hand(dx=-.2),hand('Left',dx=.2,triple=True),count=40)
        self.pair(count=10)
        self.assertFalse([c for c in self.backend.commands if c.button or c.key])

    def test_disabled_second_hand_never_clicks_or_invokes_workspace(self):
        self.session.settings=replace(self.session.settings,second_hand_enabled=False)
        self.pair(count=10)
        self.feed(hand(dx=-.2),hand('Left',True,dx=.2),count=10)
        self.pair(count=10)
        self.feed(hand(dx=-.2),hand('Left',dx=.2,triple=True),count=15)
        for i in range(9):
            self.feed(hand(dx=-.2),hand('Left',dx=.2,dy=-i*.025,triple=True))
        self.assertFalse([c for c in self.backend.commands if c.button or c.key])

    def test_secondary_click_failure_releases_input_and_pauses(self):
        self.pair(count=10)
        self.feed(hand(dx=-.2),hand('Left',True,dx=.2),count=8)
        send=self.backend.send
        def fail(command):
            if command.type==CommandType.POINTER_UP:
                raise OSError('test secondary release failure')
            return send(command)
        self.backend.send=fail
        with self.assertLogs(level='ERROR'):
            self.pair(count=5)
        self.assertEqual(self.session.view().state,'PAUSED')
        self.assertTrue(any('left' in buttons for buttons,keys in self.backend.releases))

    def test_zoom_wheel_error_releases_ctrl(self):
        self.pair(count=10);self.pair(True,count=12)
        send=self.backend.send
        def fail(command):
            if command.type==CommandType.SCROLL:raise OSError('test wheel failure')
            return send(command)
        self.backend.send=fail
        with self.assertLogs(level='ERROR'):
            for i in range(1,7):self.pair(True,extra=i*.02)
        self.assertEqual(self.session.view().state,'PAUSED')
        self.assertTrue(any('CTRL' in keys for buttons,keys in self.backend.releases))
