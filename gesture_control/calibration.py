"""Five-point work-area calibration, independent of UI and camera ownership."""

from dataclasses import replace
from math import isfinite

STEPS = ('Центр', 'Левый край', 'Правый край', 'Верхний край', 'Нижний край')


def calibrated_settings(settings, points):
    if len(points) != 5 or not all(len(p) == 2 and all(isfinite(v) and 0 <= v <= 1 for v in p) for p in points):
        raise ValueError('Нужны пять корректных точек в кадре')
    center, left, right, top, bottom = points
    bounds = left[0], top[1], right[0], bottom[1]
    if not (left[0] < center[0] < right[0] and top[1] < center[1] < bottom[1]):
        raise ValueError('Крайние точки должны окружать центр. Повторите калибровку.')
    if right[0]-left[0] < .1 or bottom[1]-top[1] < .1:
        raise ValueError('Область слишком мала: разнесите крайние точки шире.')
    return replace(settings, work_area_left=bounds[0], work_area_top=bounds[1],
                   work_area_right=bounds[2], work_area_bottom=bounds[3])
