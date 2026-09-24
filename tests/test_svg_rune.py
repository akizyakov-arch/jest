import math
import unittest
from unittest.mock import Mock

from gesture_control.svg_rune import SvgRune, load_shapes, path_points, tint


class SvgRuneTests(unittest.TestCase):
    def test_relative_segments_and_close_preserve_asset_geometry(self):
        self.assertEqual(path_points('M10 20l5-3 2 4V30H10z'),
                         ((10, 20), (15, 17), (17, 21), (17, 30), (10, 30), (10, 20)))

    def test_arc_stays_finite_and_reaches_svg_endpoint(self):
        points = path_points('M256 82A174 174 0 0 1 373 126')
        self.assertEqual(points[0], (256, 82))
        self.assertEqual(points[-1], (373, 126))
        self.assertTrue(all(math.isfinite(v) for p in points for v in p))

    def test_asset_groups_animate_without_recreating_canvas_items(self):
        shapes = load_shapes()
        self.assertGreater(len(shapes), 25)
        self.assertTrue({'outer-ring', 'mid-ring', 'inner-ring', 'rune', 'orbit-dot', 'pulse-ring'}
                        <= {s.group for s in shapes})
        canvas = Mock()
        renderer = SvgRune(canvas, 144, shapes)
        created = canvas.create_line.call_count + canvas.create_polygon.call_count
        renderer.update(0, 'POINTER')
        renderer.update(.033, 'POINTER')
        self.assertGreater(renderer.angles['mid-ring'], math.pi)
        self.assertLess(renderer.angles['outer-ring'], math.pi)
        renderer.update(.066, 'POINTER', click_event=.05)
        self.assertEqual(renderer.click_at, .05)
        for i in range(3, 60):
            renderer.update(i/30, 'DRAG')
        self.assertEqual(created, canvas.create_line.call_count + canvas.create_polygon.call_count)

    def test_clean_asset_has_no_dark_background_or_black_fade(self):
        shapes = load_shapes()
        for shape in shapes:
            for color in (shape.stroke, shape.fill):
                self.assertIn(color, ('none', '#83edff', '#28b8ff', '#7ce8ff'))
            self.assertTrue(all(0 <= value <= 512 for point in shape.points for value in point))
        self.assertEqual(tint('#83edff', .01), '#83edff')

    def test_disconnected_svg_crosshairs_do_not_gain_diagonal_connectors(self):
        shapes = load_shapes()
        outer_lines = [s for s in shapes if s.group == 'outer-ring' and len(s.points) == 2]
        self.assertEqual(len(outer_lines), 4)
