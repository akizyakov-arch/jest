"""Validated semantic profiles, independent of recognition and OS execution."""

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
SYSTEM_BINDINGS = {"PALM_HOLD": "CONTROL_TOGGLE", "THREE_FINGER_HOLD": "SHOW_KEYBOARD"}
GESTURES = {"POINT", "PINCH", "PINCH_RIGHT", "DRAG", "SCROLL", "FIST", "DOUBLE_PINCH",
            "TWO_FINGERS", "FOUR_SWIPE_UP", "FOUR_SWIPE_DOWN",
            "THREE_SWIPE_LEFT", "THREE_SWIPE_RIGHT", "TWO_HAND_ZOOM", "TWO_HAND_ROTATE"}
ACTION_NAMES = {"POINTER", "SELECT", "CONTEXT_MENU", "DRAG", "SCROLL", "CANCEL", "DOUBLE_SELECT",
                "MIDDLE_SELECT", "TASK_VIEW", "SHOW_DESKTOP",
                "PREVIOUS_APP", "NEXT_APP", "ZOOM", "ROTATE", "TRANSLATE", "SCRUB", "PLAY_PAUSE"}


@dataclass(frozen=True)
class GestureProfile:
    id: str
    name: str
    template: bool
    applications: tuple[str, ...]
    bindings: Mapping[str, str]

    def resolve(self, gesture: str) -> str | None:
        return SYSTEM_BINDINGS.get(gesture, self.bindings.get(gesture))


def load_profile(path: Path) -> GestureProfile:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "id", "name", "template", "applications", "bindings"}
    if not isinstance(data, dict) or set(data) != required or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError(f"Invalid profile schema: {path.name}")
    if not all(isinstance(data[k], str) and data[k].strip() for k in ("id", "name")):
        raise ValueError("Profile id/name must not be empty")
    if type(data["template"]) is not bool or not isinstance(data["applications"], list):
        raise ValueError("Invalid profile metadata")
    if not all(isinstance(app, str) and app.lower().endswith(".exe") for app in data["applications"]):
        raise ValueError("Profile applications must be executable names")
    bindings = data["bindings"]
    if not isinstance(bindings, dict) or any(k not in GESTURES or not isinstance(v, str) or v not in ACTION_NAMES for k, v in bindings.items()):
        raise ValueError("Unknown gesture/action or attempt to override a system gesture")
    return GestureProfile(data["id"], data["name"], data["template"], tuple(data["applications"]),
                          MappingProxyType(dict(bindings)))


def load_profiles(directory: Path = PROFILE_DIR) -> tuple[GestureProfile, ...]:
    profiles = tuple(load_profile(path) for path in sorted(directory.glob("*.json")))
    if not profiles or len({p.id for p in profiles}) != len(profiles):
        raise ValueError("Profile directory must contain profiles with unique ids")
    return profiles
