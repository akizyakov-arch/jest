"""Camera UI with explicit preview and Windows cursor modes."""

import logging
from pathlib import Path
from time import monotonic, sleep
from collections import deque
from textwrap import wrap

from .control_loop import ControlLoop
from .camera import OpenCVCamera
from .hand_tracking import MediaPipeHandTracker
from .settings import Settings
from .tracking_runtime import PreviewFrame, TrackingRuntime
from .pointer import PointerSnapshot, WorkArea
from .camera_session import CameraSession
from .preview_controls import click_action, draw_controls, keyboard_action
from .interaction import InteractionSession, InteractionSnapshot
from .profiles import load_profiles
from .hotkeys import EmergencyHotkey
from .screen_keyboard import open_screen_keyboard

log = logging.getLogger(__name__)
WINDOW = "Gesture Control - Hand Tracking"
CONNECTIONS = ((0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
               (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15),
               (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20))


def render_preview(result: PreviewFrame, mirrored: bool, show_image: bool = True,
                   pointer: PointerSnapshot | None = None, area: WorkArea | None = None,
                   pointer_mirrored: bool = True, preference: str = "FIRST",
                   interaction: InteractionSnapshot | None = None, control_cursor: bool = False,
                   pointer_mode: str = 'PALM', pointer_anchor: str = 'INDEX'):
    import cv2
    import numpy as np

    frame = result.frame
    if show_image:
        rgb = np.frombuffer(frame.pixels, np.uint8).reshape(frame.height, frame.width, 3)
        canvas = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        if mirrored:
            canvas = cv2.flip(canvas, 1)
    else:
        canvas = np.zeros((frame.height, frame.width, 3), np.uint8)
    if area is not None:
        left, right = area.left, area.right
        if mirrored != pointer_mirrored:
            left, right = 1 - right, 1 - left
        cv2.rectangle(canvas, (round(left * (frame.width - 1)), round(area.top * (frame.height - 1))),
                      (round(right * (frame.width - 1)), round(area.bottom * (frame.height - 1))),
                      (170, 180, 90), 2)
    for hand in result.tracking.hands:
        points = [(round((1 - x if mirrored else x) * (frame.width - 1)),
                   round(y * (frame.height - 1))) for x, y, _ in hand.landmarks]
        if len(points) != 21:
            continue
        for first, second in CONNECTIONS:
            cv2.line(canvas, points[first], points[second], (255, 190, 0), 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(canvas, point, 4, (0, 240, 255), -1, cv2.LINE_AA)
        if pointer is not None and pointer.source_hand_id == hand.hand_id:
            marker = (tuple(round(sum(points[i][axis] for i in (0, 5, 9, 13, 17))/5)
                            for axis in (0, 1)) if pointer_anchor == 'PALM' else points[8])
            cv2.circle(canvas, marker, 12, (80, 255, 80), 2, cv2.LINE_AA)
        score = f"{hand.handedness_score:.2f}" if hand.handedness_score is not None else "n/a"
        x, y = points[0]
        cv2.putText(canvas, f"{hand.handedness} side score {score}",
                    (max(0, min(x, frame.width - 270)), max(90, min(y, frame.height - 35))),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 200), 1, cv2.LINE_AA)
    age_ms = (monotonic() - frame.captured_at) * 1000
    anchor_label = 'Index tip' if pointer_anchor == 'INDEX' else 'Palm center'
    mode = (f"WINDOWS CURSOR | {interaction.state if interaction else 'OFF'} | {anchor_label}"
            if control_cursor else f"VIRTUAL POINTER | Windows input OFF | {pointer_mode}")
    lines = [mode,
             f"Capture {result.capture_fps:.1f} FPS | Tracking {result.inference_fps:.1f} FPS | Hands {len(result.tracking.hands)}",
             f"Inference {result.inference_ms:.1f} ms | Frame age {age_ms:.0f} ms | Skipped {result.skipped_frames}"]
    for i, line in enumerate(lines):
        cv2.putText(canvas, line, (8, 20 + i * 23), cv2.FONT_HERSHEY_SIMPLEX,
                    0.46, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas, "Q/Esc: close | M: mirror | P: image on/off", (8, frame.height - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
    if pointer is not None:
        panel = np.full((frame.height, 400, 3), (27, 23, 20), np.uint8)
        def label(text, y, color=(220, 220, 220)):
            cv2.putText(panel, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
        label("PRIMARY DISPLAY" if control_cursor else "VIRTUAL DESKTOP", 25)
        label(f"Hand: {preference} | Owner: {pointer.handedness or '-'}", 50)
        status = pointer.status + (f" | {interaction.action}" if interaction else "")
        label(status, 75, (80, 255, 80) if pointer.status == "TRACKING" else (0, 190, 255))
        if interaction is not None:
            label(f"{interaction.pose} | Hold: {interaction.progress*100:.0f}%", 98)
        # This panel represents the entire target desktop in normalized space.
        x0, y0, x1, y1 = 20, 115, 380, max(135, frame.height - 115)
        cv2.rectangle(panel, (x0, y0), (x1, y1), (120, 120, 120), 1)
        def desktop_point(position):
            return (round(x0 + position[0] * (x1 - x0)), round(y0 + position[1] * (y1 - y0)))
        if pointer.raw_position is not None:
            cv2.drawMarker(panel, desktop_point(pointer.raw_position), (150, 150, 150),
                           cv2.MARKER_CROSS, 10, 1)
        if pointer.position is not None:
            color = (80, 255, 80) if pointer.status == "TRACKING" else (0, 190, 255)
            cv2.circle(panel, desktop_point(pointer.position), 7, color, 2, cv2.LINE_AA)
        label("Green: filtered | Gray: raw", frame.height - 88)
        label(f"Pointer processing: {pointer.processing_ms:.3f} ms", frame.height - 65)
        label("R: reselect | H: FIRST/LEFT/RIGHT", frame.height - 42)
        label("- / +: resize | 0 / 1: camera", frame.height - 19)
        canvas = np.concatenate((canvas, panel), axis=1)
    return canvas


def run_preview(settings: Settings, model_path: Path, *, headless: bool = False,
                max_frames: int = 0, control_cursor: bool = False) -> int:
    import cv2
    import numpy as np

    def create_runtime(index: int) -> TrackingRuntime:
        def create_tracker():
            return MediaPipeHandTracker(model_path, settings.max_hands,
                                       settings.detection_confidence, settings.presence_confidence,
                                       settings.tracking_confidence)
        camera = OpenCVCamera(index, settings.camera_width, settings.camera_height,
                              settings.camera_fps, settings.camera_backend)
        return TrackingRuntime(camera, tracker_factory=create_tracker)

    session = CameraSession(create_runtime, settings.camera_index,
                            settings.camera_start_timeout_ms, settings.camera_frame_timeout_ms)
    profiles = load_profiles()
    if not any(profile.id == settings.profile_id for profile in profiles):
        raise ValueError(f'Unknown profile_id: {settings.profile_id}')
    backend = None
    if control_cursor:
        if headless:
            raise ValueError("Cursor control requires the control window")
        from .input_guard import GuardedInputBackend
        backend = GuardedInputBackend()
    try:
        interaction = InteractionSession(settings, profiles, cursor_backend=backend)
        pointer = interaction.pointer
        hotkey = EmergencyHotkey(settings.emergency_hotkey, interaction.emergency_stop)
    except Exception:
        if backend is not None:
            backend.close()
        raise
    notice = ""
    last_result = None
    last_status = "WAITING"
    last_dimensions = None
    last_log = 0.0
    mirrored = settings.preview_mirrored
    show_image = True
    keyboard_requested = False
    overlay = None
    if control_cursor:
        from .cursor_overlay import CursorOverlay
        overlay = CursorOverlay(settings.visual_fx, settings.rune_loss_delay_ms)
    actions = deque(maxlen=32)
    mouse_size = (settings.camera_width + 400, max(480, settings.camera_height))

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            action = click_action(x, y, *mouse_size)
            if action is not None:
                actions.append(action)

    def display():
        nonlocal mouse_size
        current_result = last_result
        if current_result is not None and session.error is None and not session.pending:
            canvas = render_preview(current_result, mirrored, show_image, interaction.display_pointer(),
                                    pointer.area, settings.pointer_mirrored, pointer.preference,
                                    interaction.view(), control_cursor, settings.pointer_mode,
                                    settings.pointer_anchor)
        else:
            canvas = np.zeros((max(480, settings.camera_height), settings.camera_width + 400, 3), np.uint8)
            lines = [session.status, "Choose Camera 0 / Camera 1 below, or press 0 / 1.",
                     "Other cameras: digits 2-9. Q/Esc: close."]
            if session.error:
                lines += wrap(session.error, width=95)
                lines.append("Check camera access/other apps, then Retry or select another camera.")
            for i, line in enumerate(lines):
                cv2.putText(canvas, line, (20, 50+i*30), cv2.FONT_HERSHEY_SIMPLEX,
                            0.55, (230, 230, 230), 1, cv2.LINE_AA)
        mouse_size = (canvas.shape[1], canvas.shape[0])
        cv2.imshow(WINDOW, draw_controls(canvas, pointer.area, session.index, interaction.view(), notice))

    def update_control():
        nonlocal last_result, last_dimensions, last_log, last_status
        interaction.hotkey_ready = hotkey.registered
        result = session.poll()
        if session.error:
            if headless:
                raise RuntimeError(session.error)
            last_result = None
            pointer.suspend()
            if interaction.camera_ready:
                interaction.camera_changed()
        if result is not None:
            now = monotonic()
            dimensions = (result.frame.width, result.frame.height)
            if last_dimensions is not None and dimensions != last_dimensions:
                interaction.camera_changed()
            last_dimensions = dimensions
            last_result = result
            interaction.process(result.tracking, now, result.frame.width, result.frame.height)
            if now - last_log >= 2 or session.frames_received == max_frames:
                log.info("camera_index=%d camera=%dx%d capture_fps=%.1f tracking_fps=%.1f inference_ms=%.1f hands=%d skipped=%d",
                         session.index, result.frame.width, result.frame.height, result.capture_fps,
                         result.inference_fps, result.inference_ms, len(result.tracking.hands),
                         result.skipped_frames)
                view = interaction.view()
                log.info("control state=%s pose=%s action=%s note=%s",
                         view.state, view.pose, view.action, view.note)
                last_log = now
            if max_frames and session.frames_received >= max_frames:
                return True
        interaction.hotkey_ready = hotkey.registered
        interaction.tick(monotonic())
        if overlay is not None:
            view = interaction.view()
            overlay.position=interaction.blue_overlay_position
            interaction.sync_cursor_visibility(overlay)
            overlay.update(view.state,
                'WORKSPACE_READY' if interaction.primary_workspace.ready and not interaction.primary_workspace.used else view.action,
                interaction.recover_tracking)
            overlay.update_secondary(view.state,
                'WORKSPACE_READY' if interaction.workspace.ready and not interaction.workspace.used else view.action,
                interaction.secondary_position)
        if pointer.snapshot.status != last_status:
            last_status = pointer.snapshot.status
            log.info("pointer_status=%s owner=%s reason=%s", last_status, pointer.snapshot.handedness,
                     pointer.snapshot.reason)
        return False

    worker = ControlLoop(update_control, interaction.emergency_stop)

    try:
        if overlay is not None:
            overlay.start()
        if not headless:
            interaction.hotkey_ready = hotkey.start()
            if not interaction.hotkey_ready:
                notice = "Emergency hotkey unavailable. Close other preview or change emergency_hotkey in config."
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(WINDOW, settings.camera_width + 400, max(480, settings.camera_height) + 142)
            cv2.setMouseCallback(WINDOW, on_mouse)
            display()
        log.info("tracking_started camera=%d input=%s pointer_mode=%s pointer_anchor=%s", session.index,
                 "windows_cursor" if control_cursor else "disabled", settings.pointer_mode, settings.pointer_anchor)
        worker.start()
        while not worker.stopped.is_set():
            if (interaction.take_keyboard_request() or keyboard_requested) and not headless:
                keyboard_requested = False
                try:
                    open_screen_keyboard()
                    notice = "Keyboard opened. Close it with its own X button."
                except OSError as exc:
                    notice = str(exc)
                    log.error("keyboard_failed: %s", exc)
            if headless:
                sleep(0.01)
                continue
            display()
            action = keyboard_action(cv2.waitKeyEx(10))
            if action is not None:
                actions.append(action)
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            with worker.lock:
                while actions:
                    action = actions.popleft()
                    if action.kind == "quit":
                        return 0
                    if action.kind == "mirror":
                        mirrored = not mirrored
                    elif action.kind == "image":
                        show_image = not show_image
                    elif action.kind == "reset":
                        interaction.reselect()
                    elif action.kind == "hand":
                        interaction.reselect(cycle_hand=True)
                    elif action.kind == "pause":
                        interaction.emergency_stop()
                        notice = ""
                    elif action.kind == "resume":
                        interaction.resume()
                        notice = ""
                    elif action.kind == "profile":
                        interaction.cycle_profile()
                        notice = ""
                    elif action.kind == "keyboard":
                        keyboard_requested = True
                    elif action.kind == "visual_fx":
                        if overlay is not None:
                            notice = (f"Cursor FX unavailable: {overlay.error}" if overlay.error
                                      else f"Cursor FX: {overlay.cycle()} | V: FULL / MINIMAL / OFF")
                        else:
                            notice = "Cursor FX is available in Windows control mode."
                    elif action.kind in ("resize", "full_area", "near_area"):
                        interaction.resize_area(1. if action.kind == 'full_area' else action.value * 0.05,
                                                near=action.kind == 'near_area')
                        notice = ""
                        log.info("work_area width=%.0f%% height=%.0f%%", (pointer.area.right-pointer.area.left)*100,
                                 (pointer.area.bottom-pointer.area.top)*100)
                    elif action.kind in ("camera", "next_camera", "retry"):
                        index = action.value if action.kind == "camera" else (1-session.index if session.index in (0, 1) else 0)
                        if action.kind == "retry":
                            index = session.index
                        if session.select(index, retry=action.kind == "retry"):
                            interaction.camera_changed()
                            last_result = None
                            last_dimensions = None
                            last_log = 0.0
        if worker.error is not None:
            raise worker.error
        return 0
    finally:
        try:
            worker.close()
        finally:
            try:
                try:
                    interaction.close()
                finally:
                    hotkey.close()
            finally:
                try:
                    try:
                        if backend is not None:
                            backend.close()
                    finally:
                        session.close()
                finally:
                    try:
                        if overlay is not None:
                            overlay.close()
                    finally:
                        if not headless:
                            cv2.destroyAllWindows()
                        log.info("tracking_stopped")
