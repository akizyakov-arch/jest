"""Offline frozen-bundle smoke check; never captures camera or injects OS input."""
import hashlib
import json
from time import monotonic, sleep
import traceback

from .windows_input import FakeInputBackend


class CheckBackend(FakeInputBackend):
    def anchor(self):
        from .cursor import Screen
        return Screen(1920,1080),(.5,.5)


def run(report):
    checks=[]
    result={'ok':False,'checks':checks}
    try:
        import cv2
        import numpy as np
        import cv2_enumerate_cameras
        from .model_assets import DEFAULT_MODEL, MODEL_SHA256
        assert hashlib.sha256(DEFAULT_MODEL.read_bytes()).hexdigest()==MODEL_SHA256
        checks.append('model_sha256')
        from .profiles import load_profiles
        assert len(load_profiles())>=1
        from .svg_rune import ASSET
        assert ASSET.is_file()
        checks.append('profiles_and_rune')
        from .camera import CameraFrame
        from .hand_tracking import MediaPipeHandTracker
        tracker=MediaPipeHandTracker(DEFAULT_MODEL)
        try:
            pixels=cv2.cvtColor(np.zeros((64,64,3),dtype=np.uint8),cv2.COLOR_BGR2RGB).tobytes()
            assert not tracker.process(CameraFrame(1,monotonic(),64,64,pixels)).hands
        finally:
            tracker.close()
        checks.append('opencv_mediapipe_inference')
        from .input_guard import GuardedInputBackend
        from .events import CommandEvent,CommandType
        guard=GuardedInputBackend(CheckBackend)
        try:
            guard.begin_session(1)
            assert guard.anchor()[1]==(.5,.5)
            guard.send(CommandEvent(CommandType.POINTER_DOWN,1,'bundle-check',monotonic()+1,button='left'))
            guard.end_session()
        finally:
            guard.close()
        checks.append('spawn_watchdog_fake_input')
        import tkinter as tk
        from .desktop_controller import DesktopController
        from .desktop_ui import DesktopApp
        from .settings import Settings
        root=tk.Tk()
        root.withdraw()
        controller=DesktopController(Settings(),report.parent/'check-settings.json')
        app=None
        tray_ready=[]
        try:
            app=DesktopApp(root,controller)
            def finish():
                tray_ready.append(app.tray.available)
                app.close()
            root.after(1500,finish)
            root.mainloop()
            assert tray_ready==[True], 'Tray did not start in the desktop application'
            assert not controller.snapshot.running, 'Self-test must never start the camera'
        finally:
            controller.close()
            if app is not None:
                app.tray.close()
            controller.worker.thread.join(6)
            try:
                root.destroy()
            except tk.TclError:
                pass
        checks.append('desktop_gui_and_native_tray')
        result['ok']=True
    except Exception:
        result['error']=traceback.format_exc()
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['ok'] else 2
