"""Composition root and an explicit fake-backend demonstration."""

import argparse
import logging
from dataclasses import replace
from pathlib import Path
from time import monotonic

from .command_engine import CommandEngine
from .debug import configure_logging
from .events import CommandEvent, CommandType
from .settings import load_settings, user_data_dir
from .state_machine import ControlMachine
from .windows_input import FakeInputBackend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gesture Control — Windows cursor and tracking preview")
    parser.add_argument("--config", type=Path, help="Settings JSON path")
    parser.add_argument("--log-dir", type=Path, help="Rotating log directory (control mode default: logs)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="Simulate activation, press and emergency stop")
    modes.add_argument("--preview", action="store_true", help="Open live hand tracking preview")
    modes.add_argument("--control", action="store_true", help="Control the Windows cursor with your hand")
    modes.add_argument("--gui", action="store_true", help="Open the desktop application")
    modes.add_argument("--download-model", action="store_true", help="Download official model once")
    parser.add_argument("--model", type=Path, help="Local Hand Landmarker .task file")
    parser.add_argument("--camera", type=int, help="Camera index, starting at 0")
    parser.add_argument("--camera-backend", choices=("auto", "dshow", "msmf"))
    parser.add_argument("--headless", action="store_true", help="Run tracking without a preview window")
    parser.add_argument("--max-frames", type=int, default=0, help="Stop after N processed frames")
    args = parser.parse_args(argv)
    if args.max_frames < 0 or (args.headless and not args.preview):
        parser.error("--max-frames must be nonnegative; --headless requires --preview")
    config_path = args.config or user_data_dir() / 'settings.json'
    initial_path = config_path
    if args.gui and not config_path.exists():
        example = Path(__file__).resolve().parents[1] / 'settings.example.json'
        if example.exists():
            initial_path = example
    result = load_settings(initial_path)
    try:
        configure_logging(result.settings.debug, args.log_dir or (Path('logs') if args.control or args.gui else None))
    except OSError as exc:
        parser.exit(2, f"Cannot initialize log directory: {exc}\n")
    logger = logging.getLogger(__name__)
    if result.warning:
        logger.warning(result.warning)
        return 2
    if args.gui:
        try:
            from .desktop_ui import run_desktop
            overrides = {}
            if args.camera is not None:
                overrides['camera_index'] = args.camera
            if args.camera_backend is not None:
                overrides['camera_backend'] = args.camera_backend
            return run_desktop(replace(result.settings, **overrides), config_path, args.model)
        except Exception as exc:
            logger.exception('desktop_failed: %s', exc)
            return 2
    if args.preview or args.control or args.download_model:
        from .model_assets import DEFAULT_MODEL, download_model
        model = args.model or DEFAULT_MODEL
        try:
            if args.download_model:
                logger.info("model_ready path=%s", download_model(model))
                return 0
            from .preview import run_preview
            overrides = {}
            if args.camera is not None:
                overrides["camera_index"] = args.camera
            if args.camera_backend is not None:
                overrides["camera_backend"] = args.camera_backend
            settings = replace(result.settings, **overrides)
            return run_preview(settings, model, headless=args.headless, max_frames=args.max_frames,
                               control_cursor=args.control)
        except ImportError as exc:
            logger.error("Missing/incompatible CV dependencies (%s). Run: .\\.venv\\Scripts\\python.exe -m pip install -r requirements-cv.txt", exc)
            return 2
        except KeyboardInterrupt:
            logger.info("tracking_interrupted")
            return 0
        except Exception as exc:
            logger.error("tracking_failed: %s", exc, exc_info=result.settings.debug)
            return 2
    backend = FakeInputBackend()
    engine = CommandEngine(backend)
    control = ControlMachine(engine)
    logger.info("started state=%s backend=fake camera=disabled", control.state.value)
    if result.warning:
        return 2
    try:
        if args.demo:
            # Readiness is simulated, not a claim that real devices/hotkeys exist.
            control.enable(camera_ready=True, hotkey_ready=True)
            control.palm_confirmed()
            control.submit(CommandEvent(CommandType.POINTER_DOWN, engine.session_id,
                                        "demo", monotonic() + 1, button="left"))
            control.emergency_stop()
            logger.info("demo complete state=%s commands=%d releases=%d",
                        control.state.value, len(backend.commands), len(backend.releases))
    finally:
        control.disable()
    return 0
