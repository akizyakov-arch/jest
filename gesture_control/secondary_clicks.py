"""One-shot secondary-hand clicks. No persistent ownership of OS buttons."""
from .activation import classify_pose
from .pinch import PinchGate, pinch_ratio


class SecondaryClicks:
    def __init__(self, settings):
        self.settings = settings
        self.gates = {button: PinchGate(settings.pinch_on_ratio, settings.pinch_off_ratio,
                                        min(settings.pinch_confirm_ms, 40), min(settings.pinch_release_ms, 40))
                      for button in ('left', 'right')}
        self.middle = PinchGate(.25, .4, settings.middle_confirm_ms, settings.middle_release_ms)
        self.reset()

    def reset(self):
        for gate in self.gates.values():
            gate.reset()
        self.middle.reset()
        self.owner = None

    def update(self, hand, timestamp, width, height, pinch=True, right=True, middle=True):
        if hand is None:
            self.reset()
            return None, False
        pose = classify_pose(hand, width, height)
        ratios = {'left': pinch_ratio(hand, width, height),
                  'right': pinch_ratio(hand, width, height,
                      12 if self.settings.right_pinch_finger == 'MIDDLE' else 16)}
        # A raised middle finger during an index pinch is not a middle click.
        # Once the middle gesture owns the pose, keep it until fingers lower.
        thumb_open = all(r is not None and r >= self.settings.pinch_off_ratio
                         for r in ratios.values())
        if self.owner is None and middle and pose == 'TWO_FINGERS' and (thumb_open or self.middle.held):
            for gate in self.gates.values():
                gate.reset()
            event = self.middle.update(0., timestamp)
            return ('middle' if event == 'down' else None), True
        self.middle.update(1., timestamp)
        enabled = {'left': pinch, 'right': pinch and right}
        if self.owner is None and all(enabled.values()) and all(
                r is not None and r <= self.settings.pinch_on_ratio for r in ratios.values()):
            self.reset()
            return None, False
        events = []
        for button, gate in self.gates.items():
            if not enabled[button] or (self.owner is not None and button != self.owner):
                gate.reset()
                continue
            event = gate.update(ratios[button], timestamp)
            if event == 'down':
                self.owner = button
            elif event == 'up' and self.owner == button:
                events.append(button)
        if events:
            self.owner = None
            for button, gate in self.gates.items():
                if button != events[0]:
                    gate.reset()
            return events[0], True
        return None, self.owner is not None or any(g.pending for g in self.gates.values())
