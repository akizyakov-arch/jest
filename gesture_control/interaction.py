"""Serialized interaction state shared with the independent emergency callback."""

from dataclasses import dataclass, replace
from collections import deque
from threading import RLock
from time import monotonic
from math import isfinite, dist
import logging

from .activation import HoldGate, StablePalmHold, classify_pose, closed_fist, open_hand_for_activation
from .smoothing import OneEuroFilter
from .command_engine import CommandEngine
from .events import ControlState, CommandEvent, CommandType
from .cursor import CursorMotion
from .pinch import PinchGate, pinch_ratio
from .pinch_aim import PinchAim
from .double_click import DoubleClick
from .scroll import ScrollGesture
from .swipe import WristFlick
from .two_hand import TwoHandZoom
from .workspace_gesture import WorkspaceGesture
from .secondary_clicks import SecondaryClicks
from .hand_tracking import TrackingSnapshot
from .pointer import VirtualPointer, palm_geometry
from .profiles import GestureProfile
from .settings import Settings
from .state_machine import ControlMachine
from .windows_input import FakeInputBackend


@dataclass(frozen=True)
class InteractionSnapshot:
    state: str
    pose: str
    progress: float
    profile: str
    action: str
    note: str


class InteractionSession:
    def __init__(self, settings: Settings, profiles: tuple[GestureProfile, ...], clock=monotonic,
                 cursor_backend=None):
        self.settings, self.profiles, self.clock = settings, profiles, clock
        self.profile_index = next((i for i, p in enumerate(profiles) if p.id == settings.profile_id), -1)
        if self.profile_index < 0:
            raise ValueError(f"Unknown profile_id: {settings.profile_id}")
        self.pointer = VirtualPointer(settings)
        self.cursor_backend = cursor_backend
        jitter = settings.jitter_radius_px if settings.suppress_jitter else 0
        self.motion = CursorMotion(settings.cursor_max_speed, settings.cursor_response_ms, settings.precision_mode, jitter)
        self.secondary_motion = CursorMotion(settings.cursor_max_speed, settings.cursor_response_ms, settings.precision_mode, jitter)
        self._secondary_input_sample = None
        self._secondary_motion_side = None
        self._pinch_history = deque(maxlen=16)
        self._after_scroll = False
        self._scroll_click_block = False
        self._scroll_open_since = None
        self.screen = None
        self.recover_tracking = False
        self.pinch = PinchGate(settings.pinch_on_ratio, settings.pinch_off_ratio,
                               min(settings.pinch_confirm_ms, 40), min(settings.pinch_release_ms, 40))
        self.aim = PinchAim(settings.pinch_aim_ratio, settings.pinch_aim_timeout_ms,
                            release_ms=60, stall_ms=settings.pinch_aim_stall_ms)
        self.right_pinch = PinchGate(settings.pinch_on_ratio, settings.pinch_off_ratio,
                                     min(settings.pinch_confirm_ms, 40), min(settings.pinch_release_ms, 40))
        self.middle = PinchGate(.25, .4, settings.middle_confirm_ms, settings.middle_release_ms)
        self.right_aim = PinchAim(settings.pinch_aim_ratio, settings.pinch_aim_timeout_ms,
                                  release_ms=60, stall_ms=settings.pinch_aim_stall_ms)
        self._grab_center = self._grab_cursor = None
        self.dragging = False
        self.machine = ControlMachine(CommandEngine(cursor_backend or FakeInputBackend(), clock))
        self._lock = RLock()
        self.palm = HoldGate(settings.activation_hold_ms, settings.gesture_rearm_ms, settings.hold_max_speed)
        self.fist = HoldGate(settings.fist_hold_ms, settings.gesture_rearm_ms, settings.hold_max_speed)
        self.activation = StablePalmHold(settings.activation_hold_ms)
        self._drag_filters = [OneEuroFilter(settings.smoothing_min_cutoff, settings.smoothing_beta,
                                            settings.smoothing_derivative_cutoff) for _ in range(2)]
        self.hotkey_ready = False
        self.camera_ready = False
        self._ever_started = False
        self._camera_time = float("-inf")
        self._processed_time = float("-inf")
        self._cursor = None
        self._navigation_at = float('-inf')
        self._pinch_geometry = None
        self.double_click = DoubleClick(settings.double_click_stabilize_ms,
                                       settings.double_click_escape_distance)
        self.scroll = ScrollGesture(settings)
        self.swipe = WristFlick(settings)
        self.secondary_swipe = WristFlick(settings)
        self._last_app_switch = float('-inf')
        self.two_hand = TwoHandZoom(settings)
        self.workspace = WorkspaceGesture(settings, require_hold=True)
        self.primary_workspace = WorkspaceGesture(settings, require_hold=True)
        self.secondary_clicks = SecondaryClicks(settings)
        self.secondary_position = None
        self.secondary_drag_origin = None
        self.secondary_drag_blocked = False
        self.secondary_scroll_origin = None
        self.secondary_context_origin = None
        self.secondary_context_until = 0.0
        self.secondary_context_action = 'SECONDARY_RIGHT_CLICK'
        self.primary_scroll_active = False
        self.scroll_stop = SecondaryClicks(settings)
        self.scroll_fist = StablePalmHold(250, radius=.06)
        self.scroll_owner_seen = float('-inf')
        self.scroll_owner_center = None
        self.scroll_owner_side = None
        self._keyboard_session: int | None = None
        self.pose, self.progress, self.action = "UNKNOWN", 0.0, "-"
        self.note = "Waiting for camera / hotkey"

    @property
    def profile(self):
        return self.profiles[self.profile_index]

    def sync_cursor_visibility(self, overlay):
        with self._lock:
            setter=getattr(self.cursor_backend,'set_cursor_hidden',None)
            if setter is None: return
            hidden=(self.settings.hide_windows_cursor and self.machine.state==ControlState.ACTIVE
                    and self.pointer.snapshot.status=='TRACKING' and overlay.mode!='OFF'
                    and getattr(overlay,'rendered',False) and not overlay.error)
            try:
                setter(bool(hidden))
            except OSError as exc:
                self._input_failed(exc)

    def view(self) -> InteractionSnapshot:
        with self._lock:
            return InteractionSnapshot(self.machine.state.value, self.pose, self.progress,
                                       self.profile.name, self.action, self.note)

    def display_pointer(self):
        with self._lock:
            status = self.pointer.snapshot.status
            if self.machine.state != ControlState.ACTIVE or not self._navigation_pose():
                status = self.machine.state.value
            return replace(self.pointer.snapshot, position=self._cursor, status=status)

    def _navigation_pose(self):
        return (self._after_scroll and self.settings.pointer_mode == 'PALM' and
                self.settings.pointer_anchor == 'PALM' and self.pose == 'UNKNOWN') or self.pose == 'POINT' or (self.settings.pointer_mode == 'PALM' and
                                        self.pose in ('OPEN_PALM', 'RELAXED_PALM'))

    @property
    def blue_overlay_position(self):
        if self.secondary_drag_origin is not None:
            return self.secondary_drag_origin
        return (self.secondary_context_origin if self.secondary_context_origin is not None
                else self.secondary_scroll_origin)

    def _cancel(self):
        self._secondary_input_sample = None
        self.secondary_motion.reset()
        self._secondary_motion_side = None
        if self.secondary_drag_origin is not None:
            self.secondary_drag_blocked = True
        self.secondary_drag_origin = None
        self.secondary_swipe.reset()
        self.secondary_context_origin = None
        self.secondary_context_until = 0.0
        self.secondary_scroll_origin = None
        self.primary_scroll_active = False
        self.scroll_stop.reset()
        self.scroll_fist.reset()
        self.secondary_clicks.reset()
        self.two_hand.reset()
        self.workspace.reset()
        self.primary_workspace.reset()
        self.secondary_position = None
        self.swipe.reset()
        self.middle.reset()
        self._after_scroll = False
        self._scroll_click_block = False
        self._scroll_open_since = None
        self._pinch_geometry = None
        self._pinch_history.clear()
        self.scroll.reset()
        self.double_click.reset()
        self._navigation_at = float('-inf')
        self.pinch.reset()
        self.aim.reset()
        self.right_pinch.reset()
        self.right_aim.reset()
        self._grab_center = self._grab_cursor = None
        self.dragging = False
        self.motion.reset()
        self.palm.cancel()
        self.fist.cancel()
        self._keyboard_session = None
        self.progress = 0.0
        self.action = "-"

    def emergency_stop(self):
        # The hotkey message thread can enter here without waiting for UI/inference.
        with self._lock:
            self.recover_tracking = False
            try:
                self._finish_secondary_scroll(self.clock(), 'pause')
                self.machine.emergency_stop()
            finally:
                self._cancel()
            self.note = "Paused. Click Resume, then hold palm."

    def resume(self) -> bool:
        with self._lock:
            fresh = self.camera_ready and (self.clock()-self._camera_time)*1000 <= self.settings.max_result_age_ms
            if fresh and self.hotkey_ready and self.machine.state == ControlState.PAUSED:
                recover = getattr(self.cursor_backend, 'recover', None)
                if recover is not None:
                    try:
                        recover()
                    except (OSError, ValueError, RuntimeError) as exc:
                        self._input_failed(exc)
                        return False
            if not self.machine.resume(camera_ready=fresh, hotkey_ready=self.hotkey_ready):
                self.note = "Resume needs fresh camera frames and emergency hotkey."
                return False
            self.pointer.reset()
            self.recover_tracking = False
            self.palm.reset()
            self.activation.reset()
            self._processed_time = float("-inf")
            self.note = "Hold open palm to activate."
            return True

    def camera_changed(self):
        with self._lock:
            self._finish_secondary_scroll(self.clock(), 'camera')
            self.recover_tracking = False
            self.machine.pause()
            self.camera_ready = False
            self.pointer.reset()
            self._processed_time = float("-inf")
            self._cancel()
            self.note = "Camera changed. Wait for frames, then Resume."

    def cycle_profile(self):
        with self._lock:
            self._finish_secondary_scroll(self.clock(), 'profile')
            self.recover_tracking = False
            self.machine.pause()
            self._cancel()
            self.profile_index = (self.profile_index+1) % len(self.profiles)
            self.note = "Profile changed. Click Resume."

    def reselect(self, cycle_hand=False):
        with self._lock:
            self._finish_secondary_scroll(self.clock(), 'reselect')
            self.recover_tracking = False
            self.machine.pause()
            self._cancel()
            if cycle_hand:
                self.pointer.cycle_hand()
            else:
                self.pointer.reset()
            self.note = "Hand changed. Click Resume."

    def resize_area(self, delta, *, near=False):
        with self._lock:
            self._finish_secondary_scroll(self.clock(), 'area')
            if self.cursor_backend is not None:
                self.recover_tracking = False
                self.machine.pause()
                self._cancel()
                self.note = "Work area changed. Click Resume."
            if near:
                self.pointer.near_area()
            else:
                self.pointer.resize_area(delta)

    def _move_cursor(self, position, timestamp, frame_id):
        if self.cursor_backend is None:
            self._cursor = position
            return
        try:
            origin = None
            if self.motion.position is None:
                self.screen, origin = self.cursor_backend.anchor()
                self._cursor = origin
            target = self.motion.step(position, timestamp, origin, (self.screen.width,self.screen.height))
            if target is not None:
                command = CommandEvent(CommandType.POINTER_MOVE, self.machine.commands.session_id,
                                       f"frame-{frame_id}", timestamp+self.settings.max_result_age_ms/1000,
                                       position=self.screen.pixels(target))
                if self.machine.submit(command):
                    self._cursor = target
        except (OSError, ValueError, RuntimeError) as exc:
            self._input_failed(exc)

    def _input_failed(self, exc):
        logging.getLogger(__name__).error('input_control_failed: %s', exc)
        self.recover_tracking = False
        try:
            self.machine.pause()
        except OSError:
            logging.getLogger(__name__).exception('input_cleanup_failed')
        self._cancel()
        self.note = f"{exc}. Check input, then Resume."

    def _tracking_lost(self):
        self._finish_secondary_scroll(self.clock(), 'lost')
        self.machine.pause()
        self._cancel()
        self.recover_tracking = True
        self.pointer.reset()
        self.palm.reset()
        self.activation.reset()
        self.note = 'Hand lost. Show one open palm and hold to resume.'

    def _release_grab(self):
        if self.secondary_drag_origin is not None:
            self.secondary_drag_blocked = True
            self.secondary_drag_origin = None
            self.secondary_clicks.reset()
        self._finish_secondary_scroll(self.clock(), 'gap')
        # A short tracking gap also ends a capture; it can never resume a drag.
        for button in tuple(self.machine.commands.buttons):
            command = CommandEvent(CommandType.POINTER_UP, self.machine.commands.session_id,
                                   'tracking-gap', self.clock()+.1, button=button)
            try:
                self.machine.submit(command)
            except (OSError, ValueError, RuntimeError) as exc:
                self._input_failed(exc)
        self.middle.reset()
        self.pinch.reset()
        self.aim.reset()
        self.right_pinch.reset()
        self.right_aim.reset()
        self.dragging = False

    def _select_pinch(self, hand, timestamp, width, height):
        left = pinch_ratio(hand, width, height)
        center, size = palm_geometry(hand)
        reach = dist(hand.landmarks[8][:2], center)/size
        previous = self._pinch_geometry
        tip_closing = (left is not None and previous is not None and previous[1] is not None
                       and 0 < timestamp-previous[0] <= .1
                       and previous[1]-left >= self.settings.pinch_tip_approach_delta
                       and previous[2]-reach >= self.settings.pinch_tip_approach_delta)
        while self._pinch_history and timestamp-self._pinch_history[0][0] > .2:
            self._pinch_history.popleft()
        # Slow deliberate closure must lock too: per-frame thresholds alone
        # only catch abrupt pinches and let the cursor drift during gentle ones.
        if left is not None and self._pinch_history:
            _, old_ratio, old_reach = self._pinch_history[0]
            tip_closing |= (old_ratio-left >= self.settings.pinch_tip_approach_delta
                            and old_reach-reach >= self.settings.pinch_tip_approach_delta)
        if left is not None:
            self._pinch_history.append((timestamp, left, reach))
        self._pinch_geometry = (timestamp, left, reach)
        right_enabled = self.profile.resolve('PINCH_RIGHT') == 'CONTEXT_MENU'
        right = (pinch_ratio(hand, width, height, 12 if self.settings.right_pinch_finger == 'MIDDLE' else 16)
                 if right_enabled else None)
        choices = [('left', self.pinch, self.aim, left)]
        if right_enabled:
            choices.append(('right', self.right_pinch, self.right_aim, right))
        owner = next((c for c in choices if c[1].held), None)
        if owner is None and left is not None and right is not None and max(left, right) <= self.settings.pinch_on_ratio:
            for _, gate, aim, _ in choices:
                gate.reset()
                aim.reset()
            self.action = 'PINCH_AMBIGUOUS'
            logging.getLogger(__name__).debug('pinch_rejected reason=ambiguous')
            return None
        results = []
        for button, gate, aim, ratio in choices:
            if owner is not None and button != owner[0]:
                gate.reset()
                aim.inhibit()
                continue
            # Folding middle/ring while entering POINT is not right-click intent.
            # Right pre-aim starts only inside the proximity zone; left keeps its
            # existing early-closing detector for precise index-finger clicks.
            aim_armed = gate.armed and (button == 'left' or aim.locked or
                                        (ratio is not None and ratio <= self.settings.pinch_aim_ratio))
            # An extended palm changing orientation is not a pinch approach.
            # Keep early capture for POINT; palm clicks still lock in proximity.
            if self.pose in ('OPEN_PALM', 'RELAXED_PALM') and ratio is not None and ratio > self.settings.pinch_aim_ratio:
                aim_armed = gate.armed and (aim.locked or (button == 'left' and tip_closing))
            aiming = aim.update(ratio, timestamp, aim_armed, gate.held,
                                approaching=button == 'left' and tip_closing)
            event = gate.update(ratio, timestamp)
            results.append((button, gate, aim, event, aiming))
        selected = next((r for r in results if r[3] is not None or r[1].held), None)
        if selected is not None:
            for candidate in results:
                if candidate[0] != selected[0]:
                    candidate[1].reset()
                    candidate[2].inhibit()
            return selected
        return next((r for r in results if r[1].pending),
                    next((r for r in results if r[4]), results[0]))

    def _middle_pose(self, hand, width, height):
        return self.pose == 'TWO_FINGERS' and (self.middle.held or all(
            (ratio := pinch_ratio(hand, width, height, tip)) is not None and
            ratio >= self.settings.pinch_off_ratio for tip in
            (8, 12 if self.settings.right_pinch_finger == 'MIDDLE' else 16)))

    def _middle_update(self, hand, center, timestamp, frame_id, width, height):
        if (self.settings.two_finger_action != 'MIDDLE' or not self.settings.gesture_middle
                or self.profile.template or self.profile.resolve('TWO_FINGERS') != 'MIDDLE_SELECT'):
            self.middle.reset()
            return False
        if self.machine.commands.buttons - {'middle'} or self.pinch.held or self.right_pinch.held:
            self.middle.reset()
            return False
        matched = self._middle_pose(hand, width, height)
        # Rearm requires exiting the pose; missing tracking never rearms.
        event = self.middle.update(0. if matched else 1., timestamp)
        if not matched and not self.middle.held and event is None:
            return False
        self.scroll.reset()
        self.double_click.reset()
        self.pinch.reset()
        self.right_pinch.reset()
        self.aim.inhibit()
        self.right_aim.inhibit()
        self._pinch_history.clear()
        self._scroll_click_block = True
        self._scroll_open_since = None
        try:
            if event == 'down':
                # The pose gate stays latched, but OS ownership lasts only for
                # this click pair. Holding/moving the pose cannot drag or repeat.
                for kind in (CommandType.POINTER_DOWN, CommandType.POINTER_UP):
                    if not self.machine.submit(CommandEvent(kind, self.machine.commands.session_id,
                            f'middle-{frame_id}', timestamp+self.settings.max_result_age_ms/1000, button='middle')):
                        raise OSError('Middle mouse command expired')
                self.action = 'MIDDLE_CLICK'
                self.primary_scroll_active=True
                self.scroll_stop.reset()
                self.scroll_fist.reset()
            else:
                self.action = 'MIDDLE_WAIT_RELEASE' if self.middle.held else 'MIDDLE_HOLD'
            self.motion.reset()
            return True
        except (OSError, ValueError, RuntimeError) as exc:
            self._input_failed(exc)
            return True

    def _scroll_update(self, hand, center, timestamp, frame_id, width, height):
        if self.settings.two_finger_action != 'SCROLL' or not self.settings.gesture_scroll or self.profile.template or self.profile.resolve('SCROLL') != 'SCROLL':
            self.scroll.reset()
            return False
        if self.machine.commands.buttons or self.pinch.held or self.right_pinch.held:
            self.scroll.reset()
            return False
        # A recognized two-finger pose owns scrolling, even if the thumb
        # brushes a fingertip. Never reinterpret that contact as mouse-down.
        matched = self.pose == 'TWO_FINGERS'
        was_candidate = self.scroll.started is not None
        if was_candidate and not matched:
            self._after_scroll = True
        if not matched and not was_candidate:
            return False
        self._scroll_click_block = True
        self._scroll_open_since = None
        # A deliberate return to navigation brakes momentum. One misclassified
        # frame still cannot steal ownership, but the cursor need not wait for
        # the complete (up to 900 ms) inertial tail.
        if not matched and self._navigation_pose():
            if self.scroll.navigation_since is None:
                self.scroll.navigation_since = timestamp
            elif timestamp-self.scroll.navigation_since >= .08:
                self.scroll.reset(keep_burst=True)
                return False
        else:
            self.scroll.navigation_since = None
        self.pinch.reset()
        self.right_pinch.reset()
        self._pinch_history.clear()
        self.aim.inhibit()
        self.right_aim.inhibit()
        self.double_click.reset()
        self.motion.reset()
        self._navigation_at = float('-inf')
        # Scrolling follows the two fingertips, independently of the cursor's
        # palm anchor. Finger-only swipes must not require moving the wrist.
        scroll_point = tuple((hand.landmarks[8][axis]+hand.landmarks[12][axis])/2 for axis in (0, 1))
        position = (scroll_point[0]/(self.pointer.area.right-self.pointer.area.left),
                    scroll_point[1]/(self.pointer.area.bottom-self.pointer.area.top))
        if matched:
            units = self.scroll.update(position, timestamp)
            self.action = 'SCROLL' if self.scroll.active else 'SCROLL_HOLD'
        else:
            units = self.scroll.release(timestamp)
            self.action = 'SCROLL_INERTIA' if units else 'SCROLL_END'
        if units:
            try:
                accepted = self.machine.submit(CommandEvent(CommandType.SCROLL, self.machine.commands.session_id,
                    f'scroll-{frame_id}', timestamp+self.settings.max_result_age_ms/1000, wheel_units=units))
                if not accepted:
                    raise OSError('Scroll command expired')
            except (OSError, ValueError, RuntimeError) as exc:
                self._input_failed(exc)
        return True

    def _secondary_input_hand(self, primary, hands, timestamp):
        candidate = self.two_hand.choose(primary, hands)
        previous = self._secondary_input_sample
        visible = self.two_hand.visible_hand(primary, hands)
        if previous is not None and timestamp-previous[0] <= .15:
            if (visible is not None and visible.handedness == previous[1]
                    and visible.handedness != primary.handedness
                    and dist(palm_geometry(visible)[0], previous[2]) <= self.settings.hand_match_distance):
                candidate = visible
            else:
                candidate = None
        self._secondary_input_sample = ((timestamp, candidate.handedness, palm_geometry(candidate)[0])
                                        if candidate is not None else None)
        return candidate

    def _secondary_target(self, hand, timestamp):
        if hand.handedness != self._secondary_motion_side:
            self.secondary_motion.reset()
            self._secondary_motion_side = hand.handedness
        target = self.pointer.area.map(palm_geometry(hand)[0], self.settings.pointer_mirrored)
        size = (self.screen.width, self.screen.height) if self.screen else (1920,1080)
        return self.secondary_motion.step(target, timestamp, origin=target, screen_size=size) or target

    def _extended_gestures(self, hand, tracking, center, timestamp, width, height):
        if self.secondary_drag_origin is not None:
            self._secondary_drag_update(hand, tracking, timestamp, width, height)
            return True
        # Context menus can query GetCursorPos asynchronously after button-up.
        # Keep the real pointer at red while the target consumes the click;
        # do not let primary navigation overwrite it on intervening frames.
        if self.secondary_context_origin is not None:
            self.secondary_swipe.reset()
            self.action = self.secondary_context_action
            if timestamp >= self.secondary_context_until:
                origin = self.secondary_context_origin
                try:
                    if not self.machine.submit(CommandEvent(CommandType.POINTER_MOVE,
                            self.machine.commands.session_id, f'secondary-{tracking.frame_id}-context-restore',
                            timestamp+self.settings.max_result_age_ms/1000,
                            position=self.screen.pixels(origin))):
                        raise OSError('Secondary context positioning expired')
                    self.secondary_context_origin = None
                except (OSError, ValueError, RuntimeError) as exc:
                    self._input_failed(exc)
            self.motion.reset()
            return True
        self.secondary_position = None
        if self.secondary_scroll_origin is not None or self.primary_scroll_active:
            self.secondary_swipe.reset()
            visible=self.two_hand.visible_hand(hand,tracking.hands) if self.settings.second_hand_enabled else None
            if visible is not None:
                self.secondary_position=self._secondary_target(visible, timestamp)
            owner=hand
            if not self.primary_scroll_active:
                owner=self.two_hand.choose(hand,tracking.hands) if self.settings.second_hand_enabled else None
                if owner is not None:
                    self.scroll_owner_seen=timestamp
                    self.scroll_owner_center=palm_geometry(owner)[0]
                elif (visible is not None and visible.handedness==self.scroll_owner_side and
                        self.scroll_owner_center is not None and
                        dist(palm_geometry(visible)[0],self.scroll_owner_center)<=self.settings.hand_match_distance and
                        timestamp-self.scroll_owner_seen<=.15):
                    owner=visible
                    # The already selected hand remains geometrically continuous;
                    # low side confidence alone must not cancel its scroll.
                    self.scroll_owner_seen=timestamp
                    self.scroll_owner_center=palm_geometry(visible)[0]
                elif self.settings.second_hand_enabled and timestamp-self.scroll_owner_seen<=.15:
                    return True
            if owner is None:
                self._finish_secondary_scroll(timestamp,tracking.frame_id)
                return True
            owner_center=palm_geometry(owner)[0]
            button,_=self.scroll_stop.update(owner,timestamp,width,height)
            fist=self.scroll_fist.update(closed_fist(owner,width,height),timestamp,owner_center)
            if button or fist.fired:
                self._finish_secondary_scroll(timestamp,tracking.frame_id)
                return True
            target=self.pointer.snapshot.position if self.primary_scroll_active else self.secondary_position
            self._move_cursor(target,timestamp,tracking.frame_id)
            self.action='PRIMARY_SCROLL' if self.primary_scroll_active else 'SECONDARY_SCROLL'
            return True
        primary_allowed = (self.settings.gesture_workspace and not self.profile.template
                           and not self.machine.commands.buttons and self.two_hand.phase not in ('ZOOM','EXIT'))
        primary_claim = primary_allowed and (self.primary_workspace.matches(hand,width,height)
                                             or self.primary_workspace.used)
        if primary_claim:
            self.secondary_swipe.reset()
            if self.settings.second_hand_enabled:
                visible=self.two_hand.visible_hand(hand,tracking.hands)
                if visible is not None:
                    self.secondary_position=self._secondary_target(visible, timestamp)
            action=self.primary_workspace.update(hand,center,timestamp,width,height)
            self.workspace.reset()
            self.two_hand.reset()
            self.secondary_clicks.reset()
            self.pinch.reset()
            self.right_pinch.reset()
            self.aim.inhibit()
            self.right_aim.inhibit()
            self.swipe.reset()
            if self.primary_workspace.ready or self.primary_workspace.used:
                self.motion.reset()
            else:
                self._move_cursor(self.pointer.snapshot.position,timestamp,tracking.frame_id)
            self.action='WORKSPACE_HOLD'
            if action:
                binding='FOUR_SWIPE_UP' if action=='TASK_VIEW' else 'FOUR_SWIPE_DOWN'
                action=self.profile.resolve(binding)
                if action in ('TASK_VIEW','SHOW_DESKTOP'):
                    self.action=action
                    key='TAB' if action=='TASK_VIEW' else 'D'
                    self._key_sequence([('WIN',True),(key,True),(key,False),('WIN',False)],timestamp,tracking.frame_id)
            return True
        self.primary_workspace.reset()
        secondary = None
        secondary_workspace = False
        if self.settings.second_hand_enabled and not self.profile.template:
            secondary = self._secondary_input_hand(hand, tracking.hands, timestamp)
            secondary_workspace = (secondary is not None and self.settings.gesture_workspace
                              and (self.workspace.matches(secondary, width, height) or self.workspace.used))
            visible = self.two_hand.visible_hand(hand, tracking.hands)
            if visible is not None:
                self.secondary_position = self._secondary_target(visible, timestamp)
            else:
                self.secondary_motion.reset()
            # An open-thumb two-finger pose owns middle click. A contacting
            # thumb is a pinch on either hand and may participate in Zoom.
            if (self.profile.resolve('TWO_HAND_ZOOM') != 'ZOOM' or
                    (self._middle_pose(hand, width, height) and self.two_hand.phase not in ('ZOOM','EXIT'))):
                self.two_hand.phase = 'IDLE'
                self.two_hand.since = None
                exclusive, units = False, 0
            else:
                exclusive, units = self.two_hand.update(hand, None if secondary_workspace else secondary, timestamp, width, height,
                                                     bool(self.machine.commands.buttons))
            if exclusive:
                self.secondary_swipe.reset()
                self.secondary_clicks.reset()
                self.action = 'ZOOM' if self.two_hand.phase == 'ZOOM' else 'ZOOM_'+self.two_hand.phase
                self.motion.reset()
                self.pinch.reset()
                self.right_pinch.reset()
                self.aim.inhibit()
                self.right_aim.inhibit()
                self.swipe.reset()
                self.workspace.reset()
                if units:
                    self._key_sequence([('CTRL', True), ('WHEEL', units), ('CTRL', False)], timestamp, tracking.frame_id)
                return True
        if (secondary is not None and self.settings.gesture_workspace
                and not self.machine.commands.buttons):
            action = self.workspace.update(secondary, palm_geometry(secondary)[0], timestamp, width, height)
            if action:
                self.secondary_clicks.reset()
                binding = 'FOUR_SWIPE_UP' if action == 'TASK_VIEW' else 'FOUR_SWIPE_DOWN'
                action = self.profile.resolve(binding)
                if action not in ('TASK_VIEW','SHOW_DESKTOP'):
                    return False
                self.action = action
                key = 'TAB' if action == 'TASK_VIEW' else 'D'
                self._key_sequence([('WIN', True), (key, True), (key, False), ('WIN', False)], timestamp, tracking.frame_id)
                self.motion.reset()
                self.swipe.reset()
                return True
        else:
            self.workspace.reset()
        if secondary_workspace or self.machine.commands.buttons or self._middle_pose(hand, width, height):
            self.secondary_swipe.reset()
            self.secondary_clicks.reset()
            return False
        if secondary is not None and self.secondary_drag_blocked:
            ratio = pinch_ratio(secondary, width, height)
            if ratio is not None and ratio >= self.settings.pinch_off_ratio:
                self.secondary_drag_blocked = False
        button, busy = self.secondary_clicks.update(secondary, timestamp, width, height,
            pinch=not self.secondary_drag_blocked and self.settings.gesture_pinch and self.profile.resolve('PINCH') == 'SELECT',
            right=self.profile.resolve('PINCH_RIGHT') == 'CONTEXT_MENU',
            middle=self.settings.gesture_middle and self.profile.resolve('TWO_FINGERS') == 'MIDDLE_SELECT')
        if (self.secondary_clicks.owner == 'left' and self.secondary_clicks.gates['left'].held
                and self.profile.resolve('DRAG') == 'DRAG'):
            try:
                screen, origin = self.cursor_backend.anchor()
                self.screen = screen
                target = screen.pixels(self.secondary_position)
                if not self.machine.submit(CommandEvent(CommandType.POINTER_MOVE,
                        self.machine.commands.session_id, f'secondary-{tracking.frame_id}-target',
                        timestamp+self.settings.max_result_age_ms/1000, position=target)):
                    raise OSError('Secondary grab positioning expired')
                self.secondary_drag_origin = origin
                # Give frame-driven targets time to consume the pointer move
                # before button-down. No sleeping or blocking the camera loop.
                self._secondary_down_at = None
                self._secondary_ready_at = timestamp + .04
                self._secondary_release_pending = False
                self._secondary_grab_center = palm_geometry(secondary)[0]
                self._secondary_grab_position = self.secondary_position
                self._secondary_drag_side = secondary.handedness
                self._secondary_dragging = False
                self.secondary_motion.reset()
                for smoothing, value in zip(self._drag_filters, self._secondary_grab_center):
                    smoothing.reset()
                    smoothing.update(value, timestamp)
                self.action = 'SECONDARY_AIM'
            except (OSError, ValueError, RuntimeError) as exc:
                self._input_failed(exc)
        if button:
            try:
                if self.cursor_backend is None or self.secondary_position is None:
                    raise OSError('Secondary click requires a screen position')
                screen, origin = self.cursor_backend.anchor()
                def move_to(position, phase):
                    if not self.machine.submit(CommandEvent(CommandType.POINTER_MOVE,
                            self.machine.commands.session_id, f'secondary-{tracking.frame_id}-{phase}',
                            timestamp+self.settings.max_result_age_ms/1000,
                            position=screen.pixels(position))):
                        raise OSError('Secondary cursor positioning expired')
                # Windows has one pointer: move to red and click there.
                # Never send the buttons if positioning was rejected.
                move_to(self.secondary_position, 'target')
                target_pixels=screen.pixels(self.secondary_position)
                for kind in (CommandType.POINTER_DOWN, CommandType.POINTER_UP):
                    if not self.machine.submit(CommandEvent(kind, self.machine.commands.session_id,
                            f'secondary-{tracking.frame_id}-{kind.name}',
                            timestamp+self.settings.max_result_age_ms/1000, button=button,
                            position=target_pixels)):
                        raise OSError('Secondary click expired')
                if button == 'middle':
                    self.secondary_scroll_origin=origin
                    self.scroll_stop.reset()
                    self.scroll_fist.reset()
                    self.scroll_owner_seen=timestamp
                    self.scroll_owner_center=palm_geometry(secondary)[0]
                    self.scroll_owner_side=secondary.handedness
                    self.screen=screen
                    self._cursor=self.secondary_position
                elif button == 'right':
                    self.screen = screen
                    self.secondary_context_origin = origin
                    self.secondary_context_until = timestamp + .25
                    self.secondary_context_action = 'SECONDARY_RIGHT_CLICK'
                else:
                    move_to(origin, 'restore')
                self.action = 'SECONDARY_'+button.upper()+'_CLICK'
            except (OSError, ValueError, RuntimeError) as exc:
                self._input_failed(exc)
        if busy:
            self.secondary_swipe.reset()
            self.motion.reset()
            self.swipe.reset()
            self.pinch.reset()
            self.right_pinch.reset()
            self.aim.inhibit()
            self.right_aim.inhibit()
            return True
        if secondary is not None:
            if self._swipe_update(secondary, timestamp, tracking.frame_id, width, height, secondary=True):
                self.swipe.reset()
                return True
        else:
            self.secondary_swipe.reset()
        return False

    def _secondary_drag_update(self, primary, tracking, timestamp, width, height):
        owner = self._secondary_input_hand(primary, tracking.hands, timestamp) if self.settings.second_hand_enabled else None
        if owner is not None and owner.handedness != self._secondary_drag_side:
            owner = None
        released = owner is None
        if owner is not None:
            button, _ = self.secondary_clicks.update(owner, timestamp, width, height)
            self._secondary_release_pending |= button == 'left'
            released = self._secondary_release_pending
        try:
            if self._secondary_down_at is None and owner is not None:
                self.action = 'SECONDARY_AIM'
                if timestamp >= self._secondary_ready_at:
                    if not self.machine.submit(CommandEvent(CommandType.POINTER_DOWN,
                            self.machine.commands.session_id, f'secondary-{tracking.frame_id}-grab',
                            timestamp+self.settings.max_result_age_ms/1000,
                            position=self.screen.pixels(self.secondary_position), button='left')):
                        raise OSError('Secondary grab expired')
                    self._secondary_down_at = timestamp
                    self.action = 'SECONDARY_PINCH_HELD'
                return
            if (released and owner is not None and self._secondary_down_at is not None
                    and timestamp-self._secondary_down_at < .04):
                self.action = 'SECONDARY_PINCH_HELD'
                return
            if released:
                origin = self.secondary_drag_origin
                if self._secondary_down_at is not None and not self.machine.submit(CommandEvent(CommandType.POINTER_UP,
                        self.machine.commands.session_id, f'secondary-{tracking.frame_id}-release',
                        timestamp+self.settings.max_result_age_ms/1000,
                        position=self.screen.pixels(self.secondary_position), button='left')):
                    raise OSError('Secondary release expired')
                self.secondary_drag_origin = None
                self.secondary_drag_blocked = owner is None
                self.secondary_clicks.reset()
                self.secondary_motion.reset()
                self.action = ('SECONDARY_DRAG_END' if self._secondary_dragging else 'SECONDARY_LEFT_CLICK') if self._secondary_down_at is not None else '-'
                self.secondary_context_origin = origin
                self.secondary_context_until = timestamp + .12
                self.secondary_context_action = self.action
            else:
                center = tuple(f.update(v, timestamp) for f,v in zip(self._drag_filters, palm_geometry(owner)[0]))
                area = self.pointer.area
                delta = ((center[0]-self._secondary_grab_center[0])/(area.right-area.left),
                         (center[1]-self._secondary_grab_center[1])/(area.bottom-area.top))
                if self.settings.pointer_mirrored:
                    delta = (-delta[0], delta[1])
                self._secondary_dragging |= dist((0,0), delta) >= self.settings.drag_start_distance
                if self._secondary_dragging:
                    target = tuple(max(0,min(1,v+d)) for v,d in zip(self._secondary_grab_position,delta))
                    target = self.secondary_motion.step(target, timestamp, origin=self.secondary_position,
                        screen_size=(self.screen.width,self.screen.height)) or self.secondary_position
                    if not self.machine.submit(CommandEvent(CommandType.POINTER_MOVE,
                            self.machine.commands.session_id, f'secondary-{tracking.frame_id}-drag',
                            timestamp+self.settings.max_result_age_ms/1000, position=self.screen.pixels(target))):
                        raise OSError('Secondary drag expired')
                    self.secondary_position = target
                self.action = 'SECONDARY_DRAG' if self._secondary_dragging else 'SECONDARY_PINCH_HELD'
            self.motion.reset()
            self.secondary_swipe.reset()
            self.swipe.reset()
        except (OSError, ValueError, RuntimeError) as exc:
            self._input_failed(exc)

    def _finish_secondary_scroll(self, timestamp, frame_id):
        origin=self.secondary_scroll_origin
        was_primary=self.primary_scroll_active
        if origin is None and not self.primary_scroll_active:
            return
        self.secondary_scroll_origin=None
        self.primary_scroll_active=False
        self.scroll_stop.reset()
        self.scroll_fist.reset()
        self.secondary_clicks.reset()
        self.motion.reset()
        self._key_sequence([('ESC',True),('ESC',False)],timestamp,frame_id)
        if origin is not None and self.machine.state == ControlState.ACTIVE:
            try:
                if not self.machine.submit(CommandEvent(CommandType.POINTER_MOVE,
                        self.machine.commands.session_id,f'scroll-return-{frame_id}',
                        timestamp+self.settings.max_result_age_ms/1000,position=self.screen.pixels(origin))):
                    raise OSError('Scroll cursor restore expired')
                self._cursor=origin
            except (OSError,ValueError,RuntimeError) as exc:
                self._input_failed(exc)
        self.action='PRIMARY_SCROLL_END' if was_primary else 'SECONDARY_SCROLL_END'

    def _key_sequence(self, sequence, timestamp, frame_id):
        try:
            for key,value in sequence:
                command = (CommandEvent(CommandType.SCROLL, self.machine.commands.session_id,
                    f'extended-{frame_id}',timestamp+self.settings.max_result_age_ms/1000,wheel_units=value)
                    if key == 'WHEEL' else CommandEvent(CommandType.KEY_DOWN if value else CommandType.KEY_UP,
                    self.machine.commands.session_id, f'extended-{frame_id}',
                    timestamp+self.settings.max_result_age_ms/1000,key=key))
                if not self.machine.submit(command):
                    raise OSError('Gesture command expired')
        except (OSError, ValueError, RuntimeError) as exc:
            self._input_failed(exc)

    def _swipe_update(self, hand, timestamp, frame_id, width, height, secondary=False):
        detector = self.secondary_swipe if secondary else self.swipe
        if not self.settings.gesture_swipe or self.profile.template or self.machine.commands.buttons:
            detector.reset()
            return False
        direction = detector.update(hand, width, height, timestamp)
        if direction is None:
            return False
        action = self.profile.resolve('THREE_SWIPE_'+('LEFT' if hand.handedness == 'Left' else direction))
        if timestamp-self._last_app_switch < self.settings.swipe_rearm_ms/1000:
            return False
        if action not in ('NEXT_APP', 'PREVIOUS_APP'):
            return False
        self.motion.reset()
        keys = ('ALT', 'SHIFT', 'TAB') if action == 'PREVIOUS_APP' else ('ALT', 'TAB')
        sequence = [(CommandType.KEY_DOWN, key) for key in keys]
        sequence += [(CommandType.KEY_UP, key) for key in reversed(keys)]
        try:
            for kind, key in sequence:
                if not self.machine.submit(CommandEvent(kind, self.machine.commands.session_id,
                        f'swipe-{frame_id}', timestamp+self.settings.max_result_age_ms/1000, key=key)):
                    raise OSError('Window-switch command expired')
            self.action = action
            self._last_app_switch = timestamp
            logging.getLogger(__name__).info('wrist_flick_confirmed direction=%s action=%s mode=%s', direction, action, detector.last_mode)
        except (OSError, ValueError, RuntimeError) as exc:
            self._input_failed(exc)
        return True

    def _fist_update(self, hand, center, timestamp, frame_id, width, height):
        if not self.settings.gesture_cancel or self.profile.template or self.profile.resolve('FIST') != 'CANCEL':
            self.fist.cancel()
            return False
        matched = closed_fist(hand, width, height, self.settings.fist_fold_ratio)
        if not matched:
            # Rearm only through an explicit navigation pose, not missing data.
            if self._navigation_pose():
                self.fist.update(False, timestamp, center)
            else:
                self.fist.cancel()
            return False
        if self.machine.commands.buttons or self.pinch.held or self.right_pinch.held:
            self.fist.cancel()
            self.fist.armed = False
            return False
        self.pinch.reset()
        self.right_pinch.reset()
        self.aim.inhibit()
        self.right_aim.inhibit()
        self._pinch_history.clear()
        self.double_click.reset()
        self.motion.reset()
        hold = self.fist.update(True, timestamp, center)
        self.pose = 'FIST'
        self.action = 'ESC' if hold.fired else 'FIST_HOLD'
        self.progress = hold.progress
        if hold.fired:
            try:
                for kind in (CommandType.KEY_DOWN, CommandType.KEY_UP):
                    if not self.machine.submit(CommandEvent(kind, self.machine.commands.session_id,
                            f'fist-{frame_id}', timestamp+self.settings.max_result_age_ms/1000, key='ESC')):
                        raise OSError('Esc command expired')
            except (OSError, ValueError, RuntimeError) as exc:
                self._input_failed(exc)
        return True

    def _pinch_update(self, hand, center, timestamp, frame_id, width, height):
        if self._scroll_click_block:
            ratios = [pinch_ratio(hand, width, height, tip) for tip in
                      (8, 12 if self.settings.right_pinch_finger == 'MIDDLE' else 16)]
            opened = self.pose in ('OPEN_PALM', 'RELAXED_PALM') and all(
                ratio is not None and ratio >= self.settings.pinch_off_ratio for ratio in ratios)
            if not opened:
                self._scroll_open_since = None
            elif self._scroll_open_since is None:
                self._scroll_open_since = timestamp
            elif timestamp-self._scroll_open_since >= self.settings.gesture_rearm_ms/1000:
                self._scroll_click_block = False
                self.pinch.reset()
                self.right_pinch.reset()
            return False
        # Only the Desktop meaning is implemented; future adapters own other meanings.
        if (not self.settings.gesture_pinch or self.profile.template or self.profile.resolve('PINCH') != 'SELECT'
                or self.profile.resolve('DRAG') != 'DRAG'):
            return False
        selected = self._select_pinch(hand, timestamp, width, height)
        if selected is None:
            # Ambiguity rejects button input, not palm navigation. Do not wait
            # indefinitely for a relaxed hand to become a named finger pose.
            if self.settings.pointer_mode == 'PALM' and self.settings.gesture_pointer:
                self._move_cursor(self.pointer.snapshot.position, timestamp, frame_id)
            return True
        button, gate, aim, event, aiming = selected
        try:
            if event == 'down':
                if self.cursor_backend is not None:
                    self.screen, self._cursor = self.cursor_backend.anchor()
                if self._cursor is None:
                    self._cursor = self.pointer.snapshot.position
                self._grab_center, self._grab_cursor = center, self._cursor
                for smoothing, value in zip(self._drag_filters, center):
                    smoothing.reset()
                    smoothing.update(value, timestamp)
                self.dragging = False
                self.motion.reset()
                if button == 'left':
                    limits = getattr(self.cursor_backend, 'double_click_limits', lambda: (500, 4, 4))()
                    pixels = self.screen.pixels(self._cursor) if self.screen else self._cursor
                    self.double_click.down(self.clock(), pixels, limits)
                else:
                    self.double_click.reset()
                accepted = self.machine.submit(CommandEvent(CommandType.POINTER_DOWN,
                                    self.machine.commands.session_id, f'pinch-{frame_id}',
                                    timestamp+self.settings.max_result_age_ms/1000, button=button))
                if not accepted:
                    raise OSError('Pinch command expired')
            elif event == 'up':
                accepted = self.machine.submit(CommandEvent(CommandType.POINTER_UP,
                                    self.machine.commands.session_id, f'pinch-{frame_id}',
                                    timestamp+self.settings.max_result_age_ms/1000, button=button))
                if not accepted:
                    raise OSError('Release command expired')
                self.action = 'RIGHT_CLICK' if button == 'right' else ('DRAG_END' if self.dragging else 'LEFT_CLICK')
                if button == 'left':
                    if self.double_click.up(self.clock(), self.pointer.area.map(center, self.settings.pointer_mirrored),
                                            self.dragging):
                        self.action = 'DOUBLE_CLICK'
                aim.released(timestamp, dragged=self.dragging)
                self.dragging = False
                self.motion.reset()
                return True
            if gate.held and button == 'right':
                self.action = 'RIGHT_PINCH_HELD'
                return True
            if gate.held:
                center = tuple(f.update(v, timestamp) for f, v in zip(self._drag_filters, center))
                area = self.pointer.area
                dx = (center[0]-self._grab_center[0])/(area.right-area.left)
                dy = (center[1]-self._grab_center[1])/(area.bottom-area.top)
                if self.settings.pointer_mirrored:
                    dx = -dx
                self.dragging |= dist((0, 0), (dx, dy)) >= self.settings.drag_start_distance
                self.action = 'DRAG' if self.dragging else 'PINCH_HELD'
                if self.dragging:
                    target = tuple(max(0, min(1, v+d)) for v, d in zip(self._grab_cursor, (dx, dy)))
                    self._move_cursor(target, timestamp, frame_id)
                return True
            if aiming or gate.pending:
                self.action = 'RIGHT_AIM_LOCK' if button == 'right' else 'AIM_LOCK'
                if self.settings.pointer_mode == 'INDEX' and self.pose != 'POINT':
                    self.motion.reset()
                elif self.motion.position is not None:
                    self.motion.timestamp = timestamp
                return True
            return False
        except (OSError, ValueError, RuntimeError) as exc:
            self._input_failed(exc)
            return True

    def tick(self, now: float):
        with self._lock:
            self.pointer.tick(now)
            if not self.hotkey_ready and self.machine.state == ControlState.ACTIVE:
                self.emergency_stop()
            # Tracking loss wins over an expired input lease. Stop is valid even
            # after watchdog expiry; probing pulse first would turn an ordinary
            # tracking pause into a manual-only input fault.
            if (self.pointer.snapshot.status.startswith("LOST")
                    and self.machine.state in (ControlState.STANDBY, ControlState.ACTIVE)):
                try:
                    self._tracking_lost()
                except OSError as exc:
                    self._input_failed(exc)
            if self.machine.state == ControlState.ACTIVE:
                heartbeat = getattr(self.cursor_backend, 'heartbeat', None)
                if heartbeat is not None:
                    try:
                        heartbeat()
                    except OSError as exc:
                        self._input_failed(exc)
            if (now-self._camera_time)*1000 > self.settings.max_result_age_ms:
                self._release_grab()
                self._cancel()

    def process(self, tracking: TrackingSnapshot, now: float, width: int, height: int):
        with self._lock:
            timestamp = tracking.source_timestamp
            if not isfinite(timestamp) or not isfinite(now):
                self._release_grab()
                self._cancel()
                return
            if timestamp <= self._processed_time or timestamp > now or (now-timestamp)*1000 > self.settings.max_result_age_ms:
                self.tick(now)
                return
            self._processed_time = timestamp
            self.camera_ready = True
            self._camera_time = timestamp
            if self.recover_tracking and (len(tracking.hands) != 1 or not self.hotkey_ready):
                self.pointer.reset()
                self.palm.reset()
                self.activation.update(False, timestamp, (0, 0))
                self.progress = 0
                return
            if self.recover_tracking and self.pointer.snapshot.status.startswith('LOST'):
                self.pointer.reset()
                self.palm.reset()
                self.activation.reset()
            if not self._ever_started and self.hotkey_ready:
                self.machine.enable(camera_ready=True, hotkey_ready=True)
                self._ever_started = True
                self.note = "Hold open palm to activate."
            pointer = self.pointer.process(tracking, now)
            self.tick(now)
            hand = next((h for h in tracking.hands if h.hand_id == pointer.source_hand_id), None)
            if hand is None or pointer.status != "TRACKING":
                self.pose = "UNKNOWN"
                self.activation.update(False, timestamp, (0, 0))
                self._release_grab()
                self._cancel()
                return
            self.pose = classify_pose(hand, width, height, self.settings.finger_straight_cosine,
                                      self.settings.finger_extension_ratio,
                                      0 if self.settings.pointer_mode == 'PALM' else self.settings.thumb_spread_ratio)
            center, _ = palm_geometry(hand)
            open_hand = open_hand_for_activation(hand, width, height, self.settings.pinch_off_ratio)
            if self.recover_tracking:
                self.activation.duration = self.settings.recovery_hold_ms/1000
                palm = self.activation.update(open_hand, timestamp, center)
                self.progress = palm.progress
                if palm.fired:
                    try:
                        if self.machine.resume(camera_ready=True, hotkey_ready=self.hotkey_ready):
                            self.machine.palm_confirmed()
                            self.recover_tracking = False
                            self.palm.armed = False
                            self.note = 'Control restored. Move your palm; pinch to click.'
                    except (OSError, ValueError, RuntimeError) as exc:
                        self._input_failed(exc)
                return
            if self.machine.state not in (ControlState.STANDBY, ControlState.ACTIVE):
                self._cancel()
                return
            if self.settings.pointer_mode == 'PALM':
                self.activation.duration = self.settings.activation_hold_ms/1000
                palm = (self.activation.update(open_hand, timestamp, center)
                        if self.machine.state == ControlState.STANDBY else None)
            else:
                palm = self.palm.update(open_hand, timestamp, center)
            self.progress = palm.progress if palm else 0
            if palm and palm.fired:
                try:
                    self.machine.palm_confirmed()
                except (OSError, ValueError, RuntimeError) as exc:
                    self._input_failed(exc)
                    return
                self._keyboard_session = None
                self.note = "Move your palm. Pinch to click. Ctrl+Alt+G: pause." if self.machine.state == ControlState.ACTIVE else "Hold palm to activate."
                if self.settings.pointer_mode == 'PALM':
                    return  # Activation frame never moves the cursor.
            self.action = "-"
            if self.machine.state == ControlState.ACTIVE:
                if self._extended_gestures(hand, tracking, center, timestamp, width, height):
                    return
                if self._middle_update(hand, center, timestamp, tracking.frame_id, width, height):
                    self.swipe.reset()
                    self.fist.cancel()
                    self.fist.armed = False
                    return
                if self._scroll_update(hand, center, timestamp, tracking.frame_id, width, height):
                    self.swipe.reset()
                    self.fist.cancel()
                    self.fist.armed = False
                    return
                if self._fist_update(hand, center, timestamp, tracking.frame_id, width, height):
                    self.swipe.reset()
                    return
                if self._pinch_update(hand, center, timestamp, tracking.frame_id, width, height):
                    self.swipe.reset()
                    self.fist.cancel()
                    return
                if self.double_click.hold(self.clock(), self.pointer.area.map(center, self.settings.pointer_mirrored)):
                    self.swipe.reset()
                    self.action = 'DOUBLE_CLICK_WAIT'
                    self.motion.reset()
                    return
                if self._swipe_update(hand, timestamp, tracking.frame_id, width, height):
                    return
                navigation = self._navigation_pose()
                brief_unknown = (self.settings.pointer_mode == 'PALM' and self.pose == 'UNKNOWN'
                                 and timestamp-self._navigation_at <= .1)
                if not navigation and not brief_unknown:
                    if self.settings.pointer_mode == 'INDEX' or timestamp-self._navigation_at > .18:
                        self.motion.reset()
                if navigation or brief_unknown:
                    if navigation:
                        self._navigation_at = timestamp
                    self.action = (self.profile.resolve("POINT") or "-") if self.settings.gesture_pointer else "-"
                    if self.action == "POINTER":
                        self._move_cursor(pointer.position, timestamp, tracking.frame_id)
                    else:
                        self.motion.reset()
            else:
                self.pinch.reset()
                self.aim.reset()
                self.right_pinch.reset()
                self.right_aim.reset()

    def take_keyboard_request(self) -> bool:
        with self._lock:
            valid = (self._keyboard_session is not None and self.machine.state == ControlState.ACTIVE
                     and self._keyboard_session == self.machine.commands.session_id)
            self._keyboard_session = None
            return valid

    def close(self):
        with self._lock:
            self._finish_secondary_scroll(self.clock(), 'close')
            self.machine.disable()
            self._cancel()
