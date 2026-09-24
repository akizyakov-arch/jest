from queue import SimpleQueue, Empty
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from gesture_control.desktop_ui import DesktopApp
from gesture_control.settings import Settings
from gesture_control.tray import TrayService


class TrayTests(TestCase):
    def test_callbacks_only_enqueue_and_stop_disables_them(self):
        queue=SimpleQueue()
        tray=TrayService(queue.put)
        tray._action('fx','OFF')(None,None)
        self.assertEqual(queue.get_nowait(),('fx','OFF'))
        tray.close()
        tray._action('exit')(None,None)
        with self.assertRaises(Empty):
            queue.get_nowait()

    def app(self):
        app=DesktopApp.__new__(DesktopApp)
        app.root=Mock()
        app.controller=Mock()
        app.controller.snapshot=SimpleNamespace(running=True,view=SimpleNamespace(state='ACTIVE'))
        app.tray=Mock(available=True)
        app.tray_actions=SimpleQueue()
        app.settings=Settings()
        app.closing=app.hidden=False
        app.calibration_points=None
        app.notify=Mock()
        return app

    def test_hiding_preserves_controller_and_restore_repaints(self):
        app=self.app()
        app.hide_to_tray()
        self.assertTrue(app.hidden)
        app.root.withdraw.assert_called_once()
        app.controller.close.assert_not_called()
        app.controller.emergency_stop.assert_not_called()
        app.tray_actions.put(('show',None))
        app.poll_tray()
        self.assertFalse(app.hidden)
        app.root.deiconify.assert_called_once()
        self.assertIsNone(app.last_frame_id)

    def test_unavailable_tray_does_not_hide_window(self):
        app=self.app()
        app.tray.available=False
        app.hide_to_tray()
        app.root.withdraw.assert_not_called()
        app.controller.close.assert_called_once()

    def test_tray_failure_restores_hidden_window(self):
        app=self.app()
        app.hidden=True
        app.tray.available=False
        app.poll_tray()
        self.assertFalse(app.hidden)
        app.root.deiconify.assert_called_once()

    def test_commands_use_existing_controller_and_exit_cleanup(self):
        app=self.app()
        app.build=Mock()
        app.navigate=Mock()
        for action,value in [('pause',None),('start',None),('stop',None),('fx','OFF'),('settings',None)]:
            app.tray_actions.put((action,value))
        app.poll_tray()
        app.controller.emergency_stop.assert_called_once()
        for call in [('pause',),('start',),('stop',),('fx','OFF')]:
            app.controller.submit.assert_any_call(*call)
        self.assertEqual(app.settings.visual_fx,'OFF')
        app.navigate.assert_called_once_with(3)
        app.tray_actions.put(('exit',None))
        app.poll_tray()
        self.assertTrue(app.closing)
        app.controller.close.assert_called_once()
        app.tray.close.assert_called_once()

    def test_minimize_hides_only_top_level(self):
        app=self.app()
        app.root.state.return_value='iconic'
        app._minimized(SimpleNamespace(widget=object()))
        app.root.withdraw.assert_not_called()
        app._minimized(SimpleNamespace(widget=app.root))
        app.root.withdraw.assert_called_once()
