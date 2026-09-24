from functools import partial
import multiprocessing as mp
from time import monotonic, sleep
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from threading import Lock
from queue import Empty

from gesture_control.cursor import Screen
from gesture_control.events import CommandEvent, CommandType
from gesture_control.input_guard import GuardedInputBackend, InputLease, input_worker
from gesture_control.windows_input import FakeInputBackend


class RecordingDesktop(FakeInputBackend):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def anchor(self):
        return Screen(1920, 1080), (.5, .5)

    def send(self, command):
        self.events.put(('send', command.type.value))

    def release(self, buttons, keys):
        self.events.put(('release', buttons, keys))


class DelayedDesktop(RecordingDesktop):
    def anchor(self):
        sleep(.12)
        return super().anchor()


class BlockedDesktop(RecordingDesktop):
    def __init__(self, events, unblock):
        super().__init__(events)
        self.unblock = unblock

    def send(self, command):
        self.events.put(('blocked',))
        self.unblock.wait(3)
        super().send(command)


def parent_to_crash(events, ready):
    backend = GuardedInputBackend(partial(RecordingDesktop, events))
    backend.begin_session(7)
    backend.send(CommandEvent(CommandType.POINTER_DOWN, 7, 'test', monotonic()+.2, button='left'))
    ready.set()
    # This helper intentionally never sends another heartbeat.
    mp.Event().wait(10)
    backend.close()


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.time = 1.
        self.backend = FakeInputBackend()
        self.lease = InputLease(self.backend, clock=lambda: self.time)
        self.lease.request('arm', 7)

    def down(self):
        return CommandEvent(CommandType.POINTER_DOWN, 7, 'test', self.time+.1, button='left')

    def test_timeout_releases_and_latches_until_explicit_arm(self):
        self.lease.request('send', self.down())
        self.time += .41
        self.lease.check()
        self.assertEqual(self.backend.releases, [(frozenset({'left'}), frozenset())])
        with self.assertRaises(OSError):
            self.lease.request('pulse')
        with self.assertRaises(OSError):
            self.lease.request('send', self.down())
        self.lease.request('arm', 9)
        with self.assertRaises(OSError):
            self.lease.request('send', self.down())

    def test_heartbeat_keeps_lease_but_stop_releases(self):
        self.lease.request('send', self.down())
        for _ in range(10):
            self.time += .1
            self.lease.request('pulse')
        self.assertEqual(self.backend.releases, [])
        self.lease.request('stop')
        self.assertEqual(len(self.backend.releases), 1)
        self.lease.request('stop')
        self.assertEqual(len(self.backend.releases), 1)

    def test_failed_release_retains_ownership_for_retry(self):
        self.lease.request('send', self.down())
        release = self.backend.release
        self.backend.release = lambda *_: (_ for _ in ()).throw(OSError('blocked'))
        self.time += .41
        with self.assertRaises(OSError):
            self.lease.check()
        self.assertFalse(self.lease.engine.enabled)
        self.assertEqual(self.lease.engine.buttons, {'left'})
        self.backend.release = release
        self.lease.check()
        self.assertFalse(self.lease.engine.buttons)

    def test_worker_cannot_report_clean_exit_when_release_fails(self):
        connection=Mock()
        connection.poll.return_value=True
        connection.recv.side_effect=[('arm',7),('send',CommandEvent(
            CommandType.KEY_DOWN,7,'cleanup',monotonic()+1,key='ALT')),('close',None)]
        backend=FakeInputBackend()
        backend.release=Mock(side_effect=OSError('release blocked'))
        with self.assertRaisesRegex(RuntimeError,'unreleased input'):
            input_worker(connection,lambda:backend)
        self.assertGreaterEqual(backend.release.call_count,3)
        connection.close.assert_called_once()

    def test_invalid_hotkey_closes_started_guard(self):
        from gesture_control.preview import run_preview
        from gesture_control.settings import Settings
        backend = Mock()
        with patch('gesture_control.input_guard.GuardedInputBackend', return_value=backend):
            with self.assertRaises(ValueError):
                run_preview(replace(Settings(), emergency_hotkey='invalid'), Path('unused.task'),
                            control_cursor=True)
        backend.close.assert_called_once()


class GuardProcessTests(unittest.TestCase):
    def setUp(self):
        self.context = mp.get_context('spawn')
        self.events = self.context.Queue()
        self.backend = GuardedInputBackend(partial(RecordingDesktop, self.events))
        self.addCleanup(self.events.close)
        self.addCleanup(self.backend.close)

    def grab(self, button='left'):
        self.backend.begin_session(7)
        self.backend.send(CommandEvent(CommandType.POINTER_DOWN, 7, 'test', monotonic()+.2, button=button))
        self.assertEqual(self.events.get(timeout=2), ('send', 'POINTER_DOWN'))

    def test_watchdog_releases_right_button_on_timeout(self):
        self.grab('right')
        self.assertEqual(self.events.get(timeout=2), ('release', frozenset({'right'}), frozenset()))

    def test_delayed_response_keeps_connection_and_reply_order(self):
        backend=GuardedInputBackend(partial(DelayedDesktop,self.events))
        self.addCleanup(backend.close)
        backend.begin_session(7)
        with self.assertLogs('gesture_control.input_guard',level='WARNING'):
            self.assertEqual(backend.anchor()[0],Screen(1920,1080))
        self.assertFalse(backend._broken)
        backend.heartbeat()
        backend.send(CommandEvent(CommandType.KEY_DOWN,7,'delay',monotonic()+.2,key='ALT'))
        backend.end_session()
        self.assertEqual(self.events.get(timeout=2),('send','KEY_DOWN'))
        self.assertEqual(self.events.get(timeout=2),('release',frozenset(),frozenset({'ALT'})))

    def test_timeout_reconnect_waits_for_cleanup_and_does_not_replay(self):
        unblock=self.context.Event()
        backend=GuardedInputBackend(partial(BlockedDesktop,self.events,unblock))
        self.addCleanup(backend.close)
        self.addCleanup(unblock.set)
        backend.begin_session(7)
        old_pid=backend.process.pid
        with self.assertLogs('gesture_control.input_guard',level='ERROR'):
            with self.assertRaisesRegex(OSError,'Resume'):
                backend.send(CommandEvent(CommandType.POINTER_DOWN,7,'blocked',monotonic()+2,button='left'))
        self.assertEqual(self.events.get(timeout=2),('blocked',))
        with self.assertRaisesRegex(OSError,'still releasing'):
            backend.recover()
        self.assertEqual(backend.process.pid,old_pid)
        unblock.set()
        self.assertEqual(self.events.get(timeout=2),('send','POINTER_DOWN'))
        self.assertEqual(self.events.get(timeout=2),('release',frozenset({'left'}),frozenset()))
        backend.process.join(2)
        backend.recover()
        self.assertNotEqual(backend.process.pid,old_pid)
        backend.begin_session(9)
        self.assertEqual(backend.anchor()[0],Screen(1920,1080))
        with self.assertRaises(Empty):
            self.events.get(timeout=.1)

    def test_unconfirmed_cleanup_prevents_restart(self):
        backend=GuardedInputBackend.__new__(GuardedInputBackend)
        backend._lock=Lock()
        backend._closed=False
        backend._broken=True
        backend.process=Mock(exitcode=1)
        backend.process.is_alive.return_value=False
        backend._start_worker=Mock()
        with self.assertRaisesRegex(OSError,'cleanup was not confirmed'):
            backend.recover()
        backend._start_worker.assert_not_called()

    def test_separate_process_expires_without_main_loop(self):
        self.grab()
        started = monotonic()
        self.assertEqual(self.events.get(timeout=2), ('release', frozenset({'left'}), frozenset()))
        self.assertLess(monotonic()-started, 1)
        with self.assertRaises(OSError):
            self.backend.heartbeat()
        self.backend.begin_session(9)
        self.assertEqual(self.backend.anchor()[0], Screen(1920, 1080))

    def test_pipe_eof_releases_and_worker_exits(self):
        self.grab()
        self.backend.connection.close()
        self.backend._broken = True
        self.assertEqual(self.events.get(timeout=2)[0], 'release')
        self.backend.process.join(2)
        self.assertFalse(self.backend.process.is_alive())

    def test_interaction_recovers_after_real_worker_lease_expires(self):
        from gesture_control.hand_tracking import TrackingSnapshot
        from gesture_control.interaction import InteractionSession
        from gesture_control.profiles import load_profiles
        from gesture_control.settings import Settings
        from test_interaction import pose_hand
        session = InteractionSession(Settings(activation_hold_ms=100), load_profiles(),
                                     cursor_backend=self.backend)
        session.hotkey_ready = True
        self.addCleanup(session.close)
        def palm_frames():
            for i in range(16):
                timestamp = monotonic()
                session.process(TrackingSnapshot(i, timestamp, timestamp, (pose_hand('OPEN_PALM'),)),
                                timestamp, 640, 480)
                sleep(.02)
        palm_frames()
        self.assertEqual(session.view().state, 'ACTIVE')
        sleep(.5)  # Let the real worker expire while the UI receives no frames.
        session.tick(monotonic())
        self.assertTrue(session.recover_tracking)
        self.assertEqual(session.view().state, 'PAUSED')
        palm_frames()
        self.assertEqual(session.view().state, 'ACTIVE')
        self.assertEqual(self.backend.anchor()[0], Screen(1920, 1080))
        session.emergency_stop()
        sleep(.3)
        session.tick(monotonic())
        palm_frames()
        self.assertEqual(session.view().state, 'PAUSED')
        self.assertFalse(session.recover_tracking)

    def test_resume_reconnects_worker_but_palm_alone_does_not(self):
        from gesture_control.hand_tracking import TrackingSnapshot
        from gesture_control.interaction import InteractionSession
        from gesture_control.profiles import load_profiles
        from gesture_control.settings import Settings
        from test_interaction import pose_hand
        session=InteractionSession(Settings(activation_hold_ms=100),load_profiles(),cursor_backend=self.backend)
        session.hotkey_ready=True
        self.addCleanup(session.close)
        def frames():
            for i in range(16):
                now=monotonic()
                session.process(TrackingSnapshot(i,now,now,(pose_hand('OPEN_PALM'),)),now,640,480)
                sleep(.02)
        frames()
        self.assertEqual(session.view().state,'ACTIVE')
        old_pid=self.backend.process.pid
        self.backend.connection.close()
        self.backend._broken=True
        self.backend.process.join(2)
        with self.assertLogs('gesture_control.interaction',level='ERROR'):
            frames()
        self.assertEqual(session.view().state,'PAUSED')
        self.assertFalse(session.recover_tracking)
        self.assertTrue(session.resume())
        self.assertNotEqual(self.backend.process.pid,old_pid)
        frames()
        self.assertEqual(session.view().state,'ACTIVE')

    def test_parent_process_termination_releases_input(self):
        events = self.context.Queue()
        ready = self.context.Event()
        parent = self.context.Process(target=parent_to_crash, args=(events, ready))
        parent.start()
        try:
            self.assertTrue(ready.wait(5))
            self.assertEqual(events.get(timeout=2)[0], 'send')
            parent.terminate()
            parent.join(2)
            self.assertEqual(events.get(timeout=2), ('release', frozenset({'left'}), frozenset()))
        finally:
            if parent.is_alive():
                parent.terminate()
                parent.join(2)
            events.close()
