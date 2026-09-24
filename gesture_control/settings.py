"""Versioned, validated settings with atomic writes and safe fallback."""

import json
import os
import tempfile
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    schema_version: int = 1
    camera_index: int = 0
    visual_fx: str = "MINIMAL"
    hide_windows_cursor: bool = False
    rune_loss_delay_ms: int = 2000
    emergency_hotkey: str = "ctrl+alt+g"
    tracking_loss_grace_ms: int = 250
    max_result_age_ms: int = 150
    debug: bool = False
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    camera_backend: str = "auto"
    camera_start_timeout_ms: int = 30000
    camera_frame_timeout_ms: int = 5000
    preview_mirrored: bool = True
    max_hands: int = 2
    detection_confidence: float = 0.5
    presence_confidence: float = 0.5
    tracking_confidence: float = 0.5
    primary_hand: str = "FIRST"
    pointer_mode: str = "PALM"
    pointer_anchor: str = "PALM"
    pointer_mirrored: bool = True
    work_area_left: float = 0.2
    work_area_top: float = 0.2
    work_area_right: float = 0.8
    work_area_bottom: float = 0.8
    smoothing_min_cutoff: float = 1.0
    smoothing_beta: float = 4.0
    smoothing_derivative_cutoff: float = 1.0
    pointer_dead_zone: float = 0.001
    cursor_max_speed: float = 1.5
    cursor_response_ms: int = 60
    precision_mode: bool = True
    suppress_jitter: bool = False
    jitter_radius_px: float = 3.0
    double_click_stabilize_ms: int = 300
    double_click_escape_distance: float = .025
    scroll_enter_ms: int = 250
    scroll_swipe_confirm_ms: int = 50
    scroll_reverse_confirm_ms: int = 120
    scroll_dead_zone: float = .015
    scroll_sensitivity: float = 2400.
    scroll_max_rate: float = 1200.
    scroll_invert: bool = False
    scroll_burst_window_ms: int = 900
    scroll_burst_step: float = .75
    scroll_burst_max: float = 4.
    gesture_pointer: bool = True
    gesture_pinch: bool = True
    gesture_scroll: bool = True
    two_finger_action: str = 'MIDDLE'
    gesture_middle: bool = True
    middle_confirm_ms: int = 120
    middle_release_ms: int = 80
    gesture_keyboard: bool = True
    gesture_cancel: bool = True
    gesture_swipe: bool = True
    second_hand_enabled: bool = False
    gesture_workspace: bool = True
    zoom_enter_ms: int = 250
    zoom_pair_wait_ms: int = 200
    zoom_wheel_gain: float = 720.
    zoom_min_separation: float = .12
    workspace_min_distance: float = .10
    workspace_min_speed: float = .08
    workspace_thumb_ratio: float = .80
    swipe_min_distance: float = .14
    swipe_min_speed: float = .65
    swipe_vertical_tolerance: float = .06
    swipe_max_duration_ms: int = 450
    swipe_rearm_ms: int = 300
    swipe_rearm_speed: float = .15
    wrist_turn_min_degrees: float = 25
    wrist_turn_speed_degrees: float = 60
    fist_hold_ms: int = 500
    fist_fold_ratio: float = .8
    pinch_on_ratio: float = 0.25
    pinch_off_ratio: float = 0.40
    pinch_confirm_ms: int = 70
    pinch_release_ms: int = 60
    pinch_aim_ratio: float = 0.75
    pinch_aim_timeout_ms: int = 900
    pinch_aim_stall_ms: int = 150
    pinch_tip_approach_delta: float = .02
    right_pinch_finger: str = 'MIDDLE'
    drag_start_distance: float = 0.025
    hand_min_size: float = 0.025
    hand_match_distance: float = 0.15
    hand_match_margin: float = 0.04
    hand_size_ratio_limit: float = 1.8
    hand_side_min_score: float = 0.8
    profile_id: str = "desktop"
    activation_hold_ms: int = 250
    recovery_hold_ms: int = 150
    gesture_rearm_ms: int = 250
    keyboard_hold_ms: int = 1000
    hold_max_speed: float = 0.35
    finger_straight_cosine: float = 0.8
    finger_extension_ratio: float = 1.1
    thumb_spread_ratio: float = 0.8

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported settings schema_version")
        if type(self.camera_index) is not int or self.camera_index < 0:
            raise ValueError("camera_index must be a nonnegative integer")
        if self.visual_fx not in ("FULL", "MINIMAL", "OFF"):
            raise ValueError("visual_fx must be FULL, MINIMAL or OFF")
        if type(self.rune_loss_delay_ms) is not int or not 0 <= self.rune_loss_delay_ms <= 10000:
            raise ValueError('rune_loss_delay_ms must be an integer in 0..10000')
        if not isinstance(self.emergency_hotkey, str) or not self.emergency_hotkey.strip():
            raise ValueError("emergency_hotkey must not be empty")
        for name in ("tracking_loss_grace_ms", "max_result_age_ms"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 2000:
                raise ValueError(f"{name} must be an integer in 1..2000 ms")
        if type(self.debug) is not bool:
            raise ValueError("debug must be boolean")
        if type(self.scroll_invert) is not bool:
            raise ValueError('scroll_invert must be boolean')
        for name in ('suppress_jitter', 'hide_windows_cursor', 'gesture_pointer', 'gesture_pinch', 'gesture_scroll', 'gesture_keyboard', 'gesture_cancel', 'gesture_middle', 'gesture_swipe', 'second_hand_enabled', 'gesture_workspace', 'precision_mode'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be boolean')
        for name, low, high in (('zoom_min_separation', .05, .4), ('workspace_min_distance', .08, .4),
                               ('workspace_min_speed', .04, 3), ('workspace_thumb_ratio', .3, 1),
                               ('zoom_wheel_gain', 120, 2400), ('swipe_min_distance', .05, .6), ('swipe_min_speed', .1, 5),
                               ('wrist_turn_min_degrees', 10, 60), ('wrist_turn_speed_degrees', 20, 240),
                               ('swipe_vertical_tolerance', .01, .3), ('swipe_rearm_speed', .01, 1)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f'{name} must be in {low}..{high}')
        for name in ('swipe_max_duration_ms', 'swipe_rearm_ms', 'zoom_enter_ms', 'zoom_pair_wait_ms'):
            if type(getattr(self, name)) is not int or not 100 <= getattr(self, name) <= 2000:
                raise ValueError(f'{name} must be in 100..2000')
        if self.two_finger_action not in ('MIDDLE', 'SCROLL'):
            raise ValueError('two_finger_action must be MIDDLE or SCROLL')
        for name in ('middle_confirm_ms', 'middle_release_ms'):
            if type(getattr(self, name)) is not int or not 30 <= getattr(self, name) <= 1000:
                raise ValueError(f'{name} must be in 30..1000')
        if type(self.fist_hold_ms) is not int or not 200 <= self.fist_hold_ms <= 2000:
            raise ValueError('fist_hold_ms must be an integer in 200..2000')
        if isinstance(self.fist_fold_ratio, bool) or not isinstance(self.fist_fold_ratio, (int, float)) or not .2 <= self.fist_fold_ratio <= 1:
            raise ValueError('fist_fold_ratio must be in .2..1')
        if type(self.scroll_enter_ms) is not int or not 100 <= self.scroll_enter_ms <= 2000:
            raise ValueError('scroll_enter_ms must be an integer in 100..2000')
        for name, low, high in (('scroll_swipe_confirm_ms', 30, 250), ('recovery_hold_ms', 100, 2000)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} must be in {low}..{high}')
        if type(self.scroll_reverse_confirm_ms) is not int or not 0 <= self.scroll_reverse_confirm_ms <= 500:
            raise ValueError('scroll_reverse_confirm_ms must be in 0..500')
        if type(self.scroll_burst_window_ms) is not int or not 200 <= self.scroll_burst_window_ms <= 2000:
            raise ValueError('scroll_burst_window_ms must be in 200..2000')
        for name, low, high in (('scroll_burst_step', 0, 2), ('scroll_burst_max', 1, 6)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not low <= value <= high:
                raise ValueError(f'{name} must be in {low}..{high}')
        if type(self.double_click_stabilize_ms) is not int or not 0 <= self.double_click_stabilize_ms <= 1000:
            raise ValueError('double_click_stabilize_ms must be an integer in 0..1000')
        for name, upper in (("camera_width", 7680), ("camera_height", 4320), ("camera_fps", 240)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an integer in 1..{upper}")
        if self.camera_backend not in ("auto", "dshow", "msmf"):
            raise ValueError("camera_backend must be auto, dshow or msmf")
        for name in ("camera_start_timeout_ms", "camera_frame_timeout_ms"):
            value = getattr(self, name)
            if type(value) is not int or not 100 <= value <= 120000:
                raise ValueError(f"{name} must be an integer in 100..120000 ms")
        if type(self.preview_mirrored) is not bool:
            raise ValueError("preview_mirrored must be boolean")
        if type(self.max_hands) is not int or self.max_hands not in (1, 2):
            raise ValueError("max_hands must be 1 or 2")
        for name in ("detection_confidence", "presence_confidence", "tracking_confidence"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be a finite number in 0..1")
        if self.primary_hand not in ("FIRST", "LEFT", "RIGHT"):
            raise ValueError("primary_hand must be FIRST, LEFT or RIGHT")
        if self.pointer_mode not in ('PALM', 'INDEX'):
            raise ValueError('pointer_mode must be PALM or INDEX')
        if self.pointer_anchor not in ('INDEX', 'PALM'):
            raise ValueError('pointer_anchor must be INDEX or PALM')
        if self.right_pinch_finger not in ('MIDDLE', 'RING'):
            raise ValueError('right_pinch_finger must be MIDDLE or RING')
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ValueError("profile_id must be a nonempty string")
        for name in ("activation_hold_ms", "gesture_rearm_ms", "keyboard_hold_ms"):
            value = getattr(self, name)
            if type(value) is not int or not 100 <= value <= 5000:
                raise ValueError(f"{name} must be an integer in 100..5000 ms")
        for name in ("pinch_confirm_ms", "pinch_release_ms", "pinch_aim_timeout_ms", "pinch_aim_stall_ms", "cursor_response_ms"):
            if type(getattr(self, name)) is not int or not 20 <= getattr(self, name) <= 1000:
                raise ValueError(f"{name} must be an integer in 20..1000 ms")
        if type(self.pointer_mirrored) is not bool:
            raise ValueError("pointer_mirrored must be boolean")
        bounds = {
            "work_area_left": (0, 1), "work_area_top": (0, 1),
            "work_area_right": (0, 1), "work_area_bottom": (0, 1),
            "smoothing_min_cutoff": (0.01, 30), "smoothing_beta": (0, 100),
            "smoothing_derivative_cutoff": (0.01, 30), "pointer_dead_zone": (0, 0.05),
            "cursor_max_speed": (0.1, 10),
            "jitter_radius_px": (0.5, 12),
            "double_click_escape_distance": (.005, .2),
            "scroll_dead_zone": (.001, .1), "scroll_sensitivity": (120, 20000),
            "scroll_max_rate": (120, 10000),
            "pinch_on_ratio": (0.05, 1), "pinch_off_ratio": (0.1, 1.5),
            "pinch_aim_ratio": (0.1, 2),
            "pinch_tip_approach_delta": (.005, .2),
            "drag_start_distance": (0.005, 0.15),
            "hand_min_size": (0.001, 0.5), "hand_match_distance": (0.01, 0.5),
            "hand_match_margin": (0.001, 0.2), "hand_size_ratio_limit": (1.01, 5),
            "hand_side_min_score": (0.5, 1),
            "hold_max_speed": (0.01, 5), "finger_straight_cosine": (0, 1),
            "finger_extension_ratio": (1, 2), "thumb_spread_ratio": (0.1, 3),
        }
        for name, (lower, upper) in bounds.items():
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f"{name} must be finite in {lower}..{upper}")
        if (self.work_area_right - self.work_area_left < 0.1
                or self.work_area_bottom - self.work_area_top < 0.1):
            raise ValueError("Work area width and height must be at least 0.1")
        if self.pinch_on_ratio >= self.pinch_off_ratio:
            raise ValueError("pinch_on_ratio must be smaller than pinch_off_ratio")
        if self.pinch_aim_ratio <= self.pinch_off_ratio:
            raise ValueError('pinch_aim_ratio must be larger than pinch_off_ratio')


@dataclass(frozen=True)
class SettingsResult:
    settings: Settings
    warning: str | None = None


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".local" / "share") / "GestureControl"


def load_settings(path: Path) -> SettingsResult:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Settings root must be an object")
        return SettingsResult(Settings(**data))
    except FileNotFoundError:
        return SettingsResult(Settings())
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return SettingsResult(Settings(), f"Settings rejected; safe defaults loaded: {exc}")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_settings(path: Path, settings: Settings) -> None:
    settings.__post_init__()
    if path.exists():
        previous = load_settings(path)
        if previous.warning is None:
            _atomic_write(path.with_suffix(path.suffix + ".bak"),
                          json.dumps(asdict(previous.settings), indent=2) + "\n")
    _atomic_write(path, json.dumps(asdict(settings), indent=2) + "\n")
