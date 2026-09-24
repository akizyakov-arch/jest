from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
import unittest

from gesture_control.calibration import calibrated_settings
from gesture_control.desktop_controller import DesktopController
from gesture_control.events import CommandEvent, CommandType
from gesture_control.settings import Settings, load_settings
from gesture_control.tracking_runtime import TrackingRuntime
from test_tracking import FakeCamera, FakeTracker
from test_palm_navigation import Desktop


class Hotkey:
    def __init__(self, combination, callback):
        self.registered = False
    def start(self):
        self.registered = True
        return True
    def close(self):
        self.registered = False


class Overlay:
    def __init__(self, mode, delay):
        self.mode, self.loss_delay = mode, delay/1000
    def start(self): pass
    def update(self, *args): pass
    def update_secondary(self, *args): pass
    def close(self): pass


def wait_for(predicate):
    deadline = monotonic()+3
    while monotonic() < deadline:
        if predicate():
            return
        Event().wait(.01)
    raise AssertionError('Desktop operation timed out')


class CalibrationTests(unittest.TestCase):
    def test_five_points_set_asymmetric_reachable_area(self):
        result = calibrated_settings(Settings(), [(.4,.5),(.15,.5),(.7,.5),(.4,.2),(.4,.85)])
        self.assertEqual((result.work_area_left,result.work_area_top,result.work_area_right,result.work_area_bottom),
                         (.15,.2,.7,.85))

    def test_crossed_missing_and_tiny_calibration_is_rejected(self):
        for points in ([], [(.5,.5),(.7,.5),(.3,.5),(.5,.2),(.5,.8)],
                       [(.5,.5),(.49,.5),(.51,.5),(.5,.49),(.5,.51)]):
            with self.assertRaises(ValueError):
                calibrated_settings(Settings(), points)


class DesktopControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name)/'settings.json'
        self.cameras, self.backends = [], []
        def runtime(index):
            camera = FakeCamera()
            self.cameras.append((index,camera))
            return TrackingRuntime(camera, FakeTracker())
        def backend():
            instance = Desktop()
            self.backends.append(instance)
            return instance
        self.controller = DesktopController(Settings(), self.path, runtime_factory=runtime,
            backend_factory=backend, hotkey_factory=Hotkey, overlay_factory=Overlay)

    def tearDown(self):
        self.controller.close()
        self.controller.worker.thread.join(4)
        self.assertFalse(self.controller.worker.thread.is_alive())
        self.temp.cleanup()

    def start(self):
        self.controller.submit('start')
        wait_for(lambda: self.controller.snapshot.frame is not None)

    def test_open_app_does_not_open_camera_or_enable_input(self):
        self.assertEqual(self.controller.snapshot.view.state, 'OFF')
        self.assertFalse(self.cameras)
        self.assertFalse(self.backends)

    def test_start_switch_and_stop_release_old_camera(self):
        self.start()
        old = self.cameras[0][1]
        self.controller.submit('apply', replace(self.controller.settings,camera_index=1))
        wait_for(lambda: len(self.cameras)==2 and self.controller.snapshot.frame is not None)
        self.assertTrue(old.closed.is_set())
        self.assertEqual(self.controller.snapshot.camera_index,1)
        self.controller.submit('stop')
        wait_for(lambda: not self.controller.snapshot.running)
        self.assertTrue(self.cameras[-1][1].closed.is_set())

    def test_apply_during_owned_button_releases_and_requires_activation(self):
        self.start()
        with self.controller.worker.lock:
            interaction = self.controller.interaction
            interaction.machine.palm_confirmed()
            interaction.machine.submit(CommandEvent(CommandType.POINTER_DOWN, interaction.machine.commands.session_id,
                'test',monotonic()+1,button='left'))
            self.controller.submit('apply',replace(self.controller.settings,gesture_pinch=False))
        wait_for(lambda: not self.controller.settings.gesture_pinch)
        self.assertTrue(self.backends[0].releases)
        self.assertNotEqual(self.controller.snapshot.view.state,'ACTIVE')
        self.assertFalse(self.controller.interaction.machine.commands.buttons)

    def test_save_fx_and_gesture_changes_round_trip(self):
        settings = replace(self.controller.settings,visual_fx='OFF',gesture_scroll=False,cursor_response_ms=90)
        self.controller.submit('save',settings)
        wait_for(self.path.exists)
        self.assertEqual(load_settings(self.path).settings,settings)
        self.assertFalse(self.controller.snapshot.running)

    def test_unavailable_camera_reports_error_and_can_stop(self):
        def fail(index):
            raise RuntimeError('camera unavailable')
        self.controller.runtime_factory = fail
        self.controller.submit('start')
        wait_for(lambda: bool(self.controller.snapshot.error))
        self.assertIn('camera unavailable',self.controller.snapshot.error)
        self.assertNotEqual(self.controller.snapshot.view.state,'ACTIVE')
        self.controller.submit('stop')
        wait_for(lambda: not self.controller.snapshot.running)

    def test_ui_navigation_sliders_and_save_use_controller(self):
        import tkinter as tk
        from gesture_control.desktop_ui import DesktopApp, Slider
        root=tk.Tk()
        root.withdraw()
        app=DesktopApp(root,self.controller)
        try:
            root.update()
            for page in range(4):
                app.navigate(page)
                root.update_idletasks()
                self.assertIn('state',app.status_items)
                self.assertIn('message',app.status_items)
                self.assertTrue(any(isinstance(w,tk.Button) and w.cget('text')=='Остановить' for w in app.widgets))
            app.navigate(0)
            self.assertIn('camera_empty', app.status_items)
            self.assertEqual(app.preview_size, (1200, 328))
            labels = [w.cget('text') for w in app.widgets if isinstance(w, tk.Button)]
            self.assertIn('Камера', labels)
            self.assertIn('Опции', labels)
            self.assertIn('Калибровка', labels)
            slider=next(w for w in app.widgets if isinstance(w,Slider))
            slider.set_value(2.)
            slider.commit()
            wait_for(lambda:self.controller.settings.cursor_max_speed==2.)
            app.toggle('gesture_scroll')
            wait_for(lambda:not self.controller.settings.gesture_scroll)
            app.save()
            wait_for(self.path.exists)
            self.assertFalse(load_settings(self.path).settings.gesture_scroll)
            from gesture_control.camera_devices import CameraDevice, read_default
            app.devices = (CameraDevice(1, 'External camera', 'external-id', 'msmf'),)
            app.camera_selected('External camera (1)')
            wait_for(lambda: self.controller.settings.camera_index == 1)
            app.default_var.set(True)
            app.set_default_camera()
            self.assertEqual(read_default(app.default_path)['path'], 'external-id')
            app.default_var.set(False)
            app.set_default_camera()
            self.assertEqual(read_default(app.default_path), {})
        finally:
            app.closing=True
            for job in root.tk.call('after','info'):
                root.after_cancel(job)
            root.destroy()
