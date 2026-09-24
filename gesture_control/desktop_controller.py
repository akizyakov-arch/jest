"""Desktop UI boundary: a single worker owns tracking and interaction.

UI reads immutable snapshots and queues commands. It never drives the heartbeat.
"""

from dataclasses import dataclass, replace
import logging
from pathlib import Path
from queue import SimpleQueue, Empty
from time import monotonic

from .camera import OpenCVCamera
from .camera_session import CameraSession
from .control_loop import ControlLoop
from .hand_tracking import MediaPipeHandTracker
from .interaction import InteractionSession, InteractionSnapshot
from .model_assets import DEFAULT_MODEL
from .profiles import load_profiles
from .settings import Settings, save_settings
from .tracking_runtime import TrackingRuntime

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DesktopSnapshot:
    view: InteractionSnapshot
    frame: object = None
    camera_status: str = 'Камера выключена'
    error: str = ''
    notice: str = ''
    running: bool = False
    hotkey_ready: bool = False
    keyboard_request: int = 0
    camera_index: int = -1
    recovering: bool = False
    secondary_detected: bool = False


class DesktopController:
    def __init__(self, settings: Settings, path: Path, *, model_path=DEFAULT_MODEL,
                 runtime_factory=None, backend_factory=None, hotkey_factory=None, overlay_factory=None):
        self.settings, self.path, self.model_path = settings, path, model_path
        self.runtime_factory = runtime_factory or self._runtime
        self.backend_factory, self.hotkey_factory, self.overlay_factory = backend_factory, hotkey_factory, overlay_factory
        self.profiles = load_profiles()
        self.interaction = self.backend = self.hotkey = self.overlay = self.camera = None
        self.result = None
        self.retired = []
        self.notice = self.error = ''
        self.notice_at = 0.
        self.keyboard_request = 0
        self.commands = SimpleQueue()
        self.closing = False
        self.snapshot = DesktopSnapshot(InteractionSnapshot('OFF', 'UNKNOWN', 0., 'Desktop', '-',
                                                           'Включите камеру, затем покажите открытую ладонь.'))
        self.worker = ControlLoop(self._update, self._failed)
        self.worker.start()

    def _runtime(self, index):
        s = self.settings
        return TrackingRuntime(OpenCVCamera(index, s.camera_width, s.camera_height, s.camera_fps, s.camera_backend),
            tracker_factory=lambda: MediaPipeHandTracker(self.model_path, s.max_hands, s.detection_confidence,
                                                         s.presence_confidence, s.tracking_confidence))

    def submit(self, action, value=None):
        if not self.closing:
            self.commands.put((action, value))

    def emergency_stop(self):
        if self.interaction is not None:
            self.interaction.emergency_stop()

    def _start(self):
        self.retired = [runtime for runtime in self.retired if runtime.is_alive]
        if self.retired:
            raise RuntimeError('Предыдущая камера ещё освобождается. Повторите запуск через несколько секунд.')
        if self.camera is not None:
            if self.camera.error:
                self.camera.select(self.camera.index, retry=True)
            else:
                self.interaction.resume()
            return
        from .input_guard import GuardedInputBackend
        from .hotkeys import EmergencyHotkey
        from .cursor_overlay import CursorOverlay
        try:
            self.backend = (self.backend_factory or GuardedInputBackend)()
            self.interaction = InteractionSession(self.settings, self.profiles, cursor_backend=self.backend)
            self.hotkey = (self.hotkey_factory or EmergencyHotkey)(self.settings.emergency_hotkey, self.emergency_stop)
            self.interaction.hotkey_ready = self.hotkey.start()
            if not self.interaction.hotkey_ready:
                self.error = 'Аварийная клавиша занята. Закройте другой экземпляр приложения или измените сочетание.'
            self.overlay = (self.overlay_factory or CursorOverlay)(self.settings.visual_fx, self.settings.rune_loss_delay_ms)
            self.overlay.start()
            self.camera = CameraSession(self.runtime_factory, self.settings.camera_index,
                                        self.settings.camera_start_timeout_ms, self.settings.camera_frame_timeout_ms)
            self.notice = 'Камера запускается. Для активации удерживайте открытую ладонь.'
        except Exception:
            self._stop()
            raise

    def _stop(self):
        # Always close every owner even if one driver reports an error.
        errors = []
        for resource in (self.interaction, self.hotkey, self.backend, self.camera, self.overlay):
            if resource is not None:
                try:
                    close = getattr(resource, 'close', None)
                    if close:
                        close()
                except Exception as exc:
                    errors.append(str(exc))
        if self.camera and self.camera.runtime and self.camera.runtime.is_alive:
            self.retired.append(self.camera.runtime)
        self.interaction = self.hotkey = self.backend = self.camera = self.overlay = None
        self.result = None
        if errors:
            raise RuntimeError('; '.join(errors))

    def _failed(self):
        try:
            self._stop()
        except Exception:
            log.exception('desktop_cleanup_failed')
        self.error = str(self.worker.error or 'Рабочий поток остановлен')
        self._publish()

    def _apply(self, settings):
        settings.__post_init__()
        from .hotkeys import parse_hotkey
        parse_hotkey(settings.emergency_hotkey)
        if not any(profile.id == settings.profile_id for profile in self.profiles):
            raise ValueError('Неизвестный профиль жестов')
        self.emergency_stop()
        old = self.settings
        running = self.camera is not None
        restart = any(getattr(old, k) != getattr(settings, k) for k in (
            'camera_width', 'camera_height', 'camera_fps', 'camera_backend', 'max_hands',
            'detection_confidence', 'presence_confidence', 'tracking_confidence', 'emergency_hotkey'))
        if running and restart:
            self._stop()
        self.settings = settings
        if running and restart:
            self._start()
        elif running:
            self.interaction.close()
            self.interaction = InteractionSession(settings, self.profiles, cursor_backend=self.backend)
            self.interaction.hotkey_ready = self.hotkey.registered
            self.overlay.mode = settings.visual_fx
            self.overlay.loss_delay = settings.rune_loss_delay_ms/1000
            if old.camera_index != settings.camera_index:
                self.camera.select(settings.camera_index)
                self.result = None
            self.camera.start_timeout_ms = settings.camera_start_timeout_ms
            self.camera.frame_timeout_ms = settings.camera_frame_timeout_ms
        self.notice = 'Параметры применены. Для управления снова покажите открытую ладонь.'

    def _command(self, action, value):
        self.error = ''
        if action == 'start':
            self._start()
        elif action == 'stop':
            self._stop()
            self.notice = 'Камера и управление выключены.'
        elif action == 'pause':
            self.emergency_stop()
        elif action == 'resume':
            if self.interaction:
                self.interaction.resume()
            else:
                self._start()
        elif action == 'apply':
            self._apply(value)
        elif action == 'save':
            self._apply(value)
            save_settings(self.path, value)
            self.notice = 'Настройки сохранены.'
        elif action == 'fx':
            self.settings = replace(self.settings, visual_fx=value)
            if self.overlay:
                self.overlay.mode = value
        elif action == 'retry' and self.camera:
            self.emergency_stop()
            self.camera.select(self.camera.index, retry=True)
            self.result = None
        self.notice_at = monotonic()

    def _publish(self):
        view = self.interaction.view() if self.interaction else InteractionSnapshot(
            'OFF', 'UNKNOWN', 0., next((p.name for p in self.profiles if p.id == self.settings.profile_id), 'Desktop'),
            '-', 'Включите камеру для начала работы.')
        self.snapshot = DesktopSnapshot(view, self.result,
            self.camera.status if self.camera else 'Камера выключена', self.error,
            self.notice if monotonic()-self.notice_at < 5 else '', self.camera is not None,
            bool(self.hotkey and self.hotkey.registered), self.keyboard_request,
            self.camera.index if self.camera else -1, bool(self.interaction and self.interaction.recover_tracking),
            bool(self.interaction and self.interaction.secondary_position is not None))

    def _update(self):
        if self.closing:
            try:
                self._stop()
            except Exception as exc:
                self.error = str(exc)
                log.exception('desktop_shutdown_failed')
            self._publish()
            return True
        for _ in range(8):
            try:
                action, value = self.commands.get_nowait()
            except Empty:
                break
            try:
                self._command(action, value)
            except Exception as exc:
                self.error = str(exc)
                self.emergency_stop()
                log.exception('desktop_command_failed action=%s', action)
        if self.camera:
            self.interaction.hotkey_ready = self.hotkey.registered
            result = self.camera.poll()
            if self.camera.error:
                if self.interaction.camera_ready:
                    self.interaction.camera_changed()
                self.result = None
                self.error = self.camera.error
            if result is not None:
                if self.result and (result.frame.width, result.frame.height) != (self.result.frame.width, self.result.frame.height):
                    self.interaction.camera_changed()
                self.result = result
                self.interaction.process(result.tracking, monotonic(), result.frame.width, result.frame.height)
            self.interaction.tick(monotonic())
            view = self.interaction.view()
            self.overlay.position=self.interaction.blue_overlay_position
            self.overlay.update(view.state,
                'WORKSPACE_READY' if self.interaction.primary_workspace.ready and not self.interaction.primary_workspace.used else view.action,
                self.interaction.recover_tracking)
            self.overlay.update_secondary(view.state,
                'WORKSPACE_READY' if self.interaction.workspace.ready and not self.interaction.workspace.used else view.action,
                self.interaction.secondary_position)
            if self.interaction.take_keyboard_request():
                self.keyboard_request += 1
            self.interaction.sync_cursor_visibility(self.overlay)
        self._publish()
        return False

    def close(self):
        try:
            self.emergency_stop()
        finally:
            self.closing = True
