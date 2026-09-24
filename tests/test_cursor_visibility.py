from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from gesture_control.cursor_visibility import CursorVisibility
from gesture_control.input_guard import InputLease
from gesture_control.windows_input import FakeInputBackend


class VisibilityTests(TestCase):
    def test_hiding_is_idempotent_and_restore_uses_saved_cursors(self):
        user=Mock()
        user.CreateCursor.return_value=123
        user.SetSystemCursor.return_value=1
        user.SystemParametersInfoW.return_value=1
        visibility=CursorVisibility(user)
        visibility.set_hidden(True)
        visibility.set_hidden(True)
        self.assertEqual(user.SetSystemCursor.call_count,len(visibility.IDS))
        visibility.set_hidden(False)
        visibility.set_hidden(False)
        self.assertEqual(user.SetSystemCursor.call_count,2*len(visibility.IDS))
        self.assertEqual(user.DestroyCursor.call_count,len(visibility.IDS))
        self.assertFalse(visibility.hidden)

    def test_partial_failure_restores_cursor_scheme(self):
        user=Mock()
        user.CreateCursor.return_value=123
        user.SetSystemCursor.side_effect=[1,0]+[1]*13
        user.SystemParametersInfoW.return_value=1
        visibility=CursorVisibility(user)
        with self.assertRaises(OSError): visibility.set_hidden(True)
        self.assertFalse(visibility.hidden)
        self.assertEqual(user.SetSystemCursor.call_count,15)

    def test_failed_restore_retains_state_for_retry(self):
        user=Mock()
        visibility=CursorVisibility(user)
        visibility.hidden=True
        visibility.originals={32512:123}
        user.SetSystemCursor.return_value=0
        with self.assertRaises(OSError):visibility.set_hidden(False)
        self.assertTrue(visibility.hidden)
        user.SetSystemCursor.return_value=1
        visibility.set_hidden(False)
        self.assertFalse(visibility.hidden)

    def test_watchdog_restores_on_stop_and_heartbeat_expiry(self):
        backend=FakeInputBackend()
        backend.cursor_hidden=False
        def setter(hidden):backend.cursor_hidden=hidden
        backend.set_cursor_hidden=setter
        now=[1.]
        lease=InputLease(backend,clock=lambda:now[0])
        lease.request('arm',1)
        lease.request('cursor_visibility',True)
        self.assertTrue(backend.cursor_hidden)
        now[0]+=1
        lease.check()
        self.assertFalse(backend.cursor_hidden)
        self.assertTrue(lease.fault)
        lease.request('arm',3)
        lease.request('cursor_visibility',True)
        lease.stop()
        self.assertFalse(backend.cursor_hidden)

    def test_hiding_requires_active_tracking_and_a_rendered_rune(self):
        from threading import RLock
        from gesture_control.interaction import InteractionSession
        from gesture_control.events import ControlState
        session=InteractionSession.__new__(InteractionSession)
        session._lock=RLock()
        session.settings=SimpleNamespace(hide_windows_cursor=True)
        session.machine=SimpleNamespace(state=ControlState.ACTIVE)
        session.pointer=SimpleNamespace(snapshot=SimpleNamespace(status='TRACKING'))
        session.cursor_backend=Mock()
        overlay=SimpleNamespace(mode='FULL',rendered=False,error=None)
        session.sync_cursor_visibility(overlay)
        session.cursor_backend.set_cursor_hidden.assert_called_with(False)
        overlay.rendered=True
        session.sync_cursor_visibility(overlay)
        session.cursor_backend.set_cursor_hidden.assert_called_with(True)
        for field,value in (('mode','OFF'),('error','render failed'),('rendered',False)):
            old=getattr(overlay,field)
            setattr(overlay,field,value)
            session.sync_cursor_visibility(overlay)
            session.cursor_backend.set_cursor_hidden.assert_called_with(False)
            setattr(overlay,field,old)
        session.machine.state=ControlState.PAUSED
        session.sync_cursor_visibility(overlay)
        session.cursor_backend.set_cursor_hidden.assert_called_with(False)
