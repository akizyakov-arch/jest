"""Keyboard and mouse controls shared by running and unavailable-camera views."""

from dataclasses import dataclass

from .pointer import WorkArea


@dataclass(frozen=True)
class Action:
    kind: str
    value: int = 0


def keyboard_action(key: int) -> Action | None:
    if key < 0:
        return None
    if ord("0") <= key <= ord("9"):
        return Action("camera", key - ord("0"))
    if key in (ord("-"), ord("_"), ord("[")):
        return Action("resize", -1)
    if key in (ord("+"), ord("="), ord("]")):
        return Action("resize", 1)
    commands = {27: "quit", ord("q"): "quit", ord("m"): "mirror", ord("p"): "image",
                ord("r"): "reset", ord("h"): "hand", ord("c"): "next_camera",
                ord("k"): "keyboard", ord("f"): "profile", 32: "pause", ord("u"): "resume",
                ord("b"): "full_area", ord("n"): "near_area", ord("v"): "visual_fx"}
    if ord("A") <= key <= ord("Z"):
        key += ord("a") - ord("A")
    return Action(commands[key]) if key in commands else None


@dataclass(frozen=True)
class Button:
    label: str
    bounds: tuple[int, int, int, int]
    action: Action


def buttons(width: int, image_height: int) -> tuple[Button, ...]:
    choices = (("Area -", Action("resize", -1)), ("Area +", Action("resize", 1)),
               ("Area 100%", Action("full_area")),
               ("Camera 0", Action("camera", 0)), ("Camera 1", Action("camera", 1)),
               ("Camera 2", Action("camera", 2)), ("Retry", Action("retry")))
    step = (width - 20) // len(choices)
    first = tuple(Button(label, (10+i*step, image_height+32, 10+(i+1)*step-6, image_height+64), action)
                  for i, (label, action) in enumerate(choices))
    extra = (("Pause", Action("pause")), ("Resume", Action("resume")),
             ("Profile", Action("profile")), ("Keyboard", Action("keyboard")),
             ("Near 50%", Action("near_area")), ("Cursor FX", Action("visual_fx")))
    step = (width-20)//len(extra)
    return first + tuple(Button(label, (10+i*step, image_height+98, 10+(i+1)*step-6, image_height+130), action)
                         for i, (label, action) in enumerate(extra))


def click_action(x: int, y: int, width: int, image_height: int) -> Action | None:
    for button in buttons(width, image_height):
        x0, y0, x1, y1 = button.bounds
        if x0 <= x <= x1 and y0 <= y <= y1:
            return button.action
    return None


def draw_controls(image, area: WorkArea, camera_index: int, interaction=None, notice: str = ""):
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    toolbar = np.full((142, width, 3), 32, np.uint8)
    output = np.concatenate((image, toolbar), axis=0)
    text = (f"Camera {camera_index} | Area {(area.right-area.left)*100:.0f}% x "
            f"{(area.bottom-area.top)*100:.0f}% | Smaller area = less hand travel | N: near | V: FX")
    cv2.putText(output, text, (10, height+21), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                (230, 230, 230), 1, cv2.LINE_AA)
    if interaction is not None:
        text = notice or f"{interaction.state} | Profile: {interaction.profile} | {interaction.note}"
        cv2.putText(output, text[:125], (10, height+87), cv2.FONT_HERSHEY_SIMPLEX, 0.46,
                    (0, 200, 255) if notice else (230, 230, 230), 1, cv2.LINE_AA)
    for button in buttons(width, height):
        x0, y0, x1, y1 = button.bounds
        selected = button.action.kind == "camera" and button.action.value == camera_index
        cv2.rectangle(output, (x0, y0), (x1, y1), (110, 75, 35) if selected else (60, 60, 60), -1)
        cv2.putText(output, button.label, (x0+9, y0+22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, (255, 255, 255), 1, cv2.LINE_AA)
    return output
