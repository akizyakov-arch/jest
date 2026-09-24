"""Canvas adapter for the bundled tech-rune SVG geometry and animation hooks.

Not a general SVG/CSS engine: supports the paths and classes in this asset.
Color-key transparency uses bright contours, without dark blur or background fills.
"""

from dataclasses import dataclass
from math import atan2, cos, sin, sqrt, tau
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ASSET = Path(__file__).with_name('assets') / 'tech_rune_hud_clean_animated.svg'


def path_points(data):
    tokens = re.findall(r'[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?', data)
    points, current, origin = [], (0., 0.), (0., 0.)
    i, command = 0, None
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        op = command.upper()
        relative = command.islower()
        if op == 'Z':
            points.append(origin)
            current = origin
            command = None
            continue
        count = {'M': 2, 'L': 2, 'H': 1, 'V': 1, 'A': 7}.get(op)
        if count is None:
            raise ValueError(f'Unsupported SVG command: {command}')
        values = list(map(float, tokens[i:i+count]))
        i += count
        x, y = current
        if op in ('M', 'L'):
            end = (values[0]+(x if relative else 0), values[1]+(y if relative else 0))
        elif op == 'H':
            end = (values[0]+(x if relative else 0), y)
        elif op == 'V':
            end = (x, values[0]+(y if relative else 0))
        else:
            rx, ry, rotation, large, sweep, ex, ey = values
            if rotation or rx <= 0 or ry <= 0:
                raise ValueError('Asset adapter requires unrotated nonzero arcs')
            end = (ex+(x if relative else 0), ey+(y if relative else 0))
            px, py = (x-end[0])/2, (y-end[1])/2
            scale = sqrt(max(1., px*px/(rx*rx)+py*py/(ry*ry)))
            rx, ry = rx*scale, ry*scale
            denominator = rx*rx*py*py+ry*ry*px*px
            factor = sqrt(max(0., (rx*rx*ry*ry-denominator)/denominator)) if denominator else 0.
            if bool(large) == bool(sweep):
                factor = -factor
            cx, cy = factor*rx*py/ry, -factor*ry*px/rx
            start = atan2((py-cy)/ry, (px-cx)/rx)
            finish = atan2((-py-cy)/ry, (-px-cx)/rx)
            extent = (finish-start) % tau if sweep else -((start-finish) % tau)
            cx, cy = cx+(x+end[0])/2, cy+(y+end[1])/2
            points.extend((cx+rx*cos(start+extent*j/24), cy+ry*sin(start+extent*j/24))
                          for j in range(1, 24))
        points.append(end)
        current = end
        if op == 'M':
            origin = end
            command = 'l' if relative else 'L'
    return tuple(points)


@dataclass(frozen=True)
class Shape:
    points: tuple
    group: str
    stroke: str
    fill: str
    width: float
    opacity: float
    dash: tuple
    glow: bool


def load_shapes(path=ASSET):
    shapes = []
    root = ET.parse(path).getroot()
    vx, vy, vw, vh = map(float, root.get('viewBox', '0 0 512 512').split())
    aliases = {'outer': 'outer-ring', 'mid': 'mid-ring', 'inner': 'inner-ring',
               'orbit': 'orbit-dot', 'core': 'rune', 'click': 'pulse-ring', 'thin': 'line-thin'}

    def visit(node, inherited, groups):
        tag = node.tag.split('}')[-1]
        if tag in ('defs', 'title', 'desc'):
            return
        classes = [aliases.get(c, c) for c in node.get('class', '').split()]
        style = dict(inherited)
        if 'line' in classes or 'line-thin' in classes:
            thin = 'line-thin' in classes
            style.update(fill='none', stroke='#83edff' if thin else '#28b8ff',
                         **{'stroke-width': '1.15' if thin else '2'})
        if 'pulse-ring' in classes:
            style.update(fill='none', stroke='#7ce8ff', **{'stroke-width': '2'})
        if 'dim' in classes:
            style['opacity'] = '.42'
        for key in ('fill', 'stroke', 'stroke-width', 'opacity', 'stroke-dasharray', 'filter'):
            if key in node.attrib:
                style[key] = node.attrib[key]
        for key in ('fill', 'stroke'):
            if key in style:
                style[key] = style[key].replace('var(--c2)', '#83edff').replace('var(--c)', '#28b8ff')
        groups = groups + classes
        group = next((g for g in groups if g in ('outer-ring', 'mid-ring', 'inner-ring',
                                                 'orbit-dot', 'rune', 'pulse-ring')), '')
        background = (float(style.get('opacity', 1)) < .1 and style.get('stroke', 'none') == 'none')
        if tag in ('path', 'circle') and not background and not style.get('fill', '').startswith('url('):
            if tag == 'path':
                # A new moveto starts a disconnected contour, never a joining line.
                contours = [path_points(d) for d in re.split(r'(?=M)', node.attrib['d']) if d.strip()]
            else:
                x, y, r = (float(node.get(k, 0)) for k in ('cx', 'cy', 'r'))
                contours = [tuple((x+r*cos(i*tau/96), y+r*sin(i*tau/96)) for i in range(97))]
            for points in contours:
                points = tuple(((x-vx)*512/vw, (y-vy)*512/vh) for x, y in points)
                shapes.append(Shape(points, group, style.get('stroke', 'none'), style.get('fill', 'none'),
                                float(style.get('stroke-width', 1)), float(style.get('opacity', 1)),
                                tuple(float(v)*512/vw for v in style.get('stroke-dasharray', '').split()),
                                'bright' in groups or 'core' in groups or 'filter' in style))
        for child in node:
            visit(child, style, groups)

    visit(root, {}, [])
    return shapes


def tint(color, opacity):
    # Color-keyed windows cannot blend alpha. Darkening against black produced
    # opaque dark halos on light apps. Keep emissive colors; fade by hiding only.
    return color


class SvgRune:
    def __init__(self, canvas, size, shapes=None):
        self.canvas, self.size = canvas, size
        self.items = []
        self.angles = dict.fromkeys(('outer-ring', 'mid-ring', 'inner-ring', 'orbit-dot'), 0.)
        self.last_time = None
        self.last_action = '-'
        self.click_at = float('-inf')
        self.click_event = None
        for shape in load_shapes() if shapes is None else shapes:
            dash = tuple(max(1, round(v*size/512)) for v in shape.dash)
            layers = []
            coords = [v*size/512 for p in shape.points for v in p]
            if shape.fill != 'none':
                layers.append((canvas.create_polygon(*coords, fill=tint(shape.fill, shape.opacity), outline=''),
                               shape.fill, shape.opacity))
            if shape.stroke != 'none':
                layers.append((canvas.create_line(*coords, fill=tint(shape.stroke, shape.opacity),
                                  width=max(.7, shape.width*size/512), dash=dash,
                                  joinstyle='round'), shape.stroke, shape.opacity))
            self.items.append((shape, layers))

    def update(self, now, action, click_event=None):
        dt = 0 if self.last_time is None else min(.1, max(0, now-self.last_time))
        self.last_time = now
        drag = action == 'DRAG'
        for group, period in (('outer-ring', 4 if drag else 9), ('mid-ring', -2.8 if drag else -5.5),
                              ('inner-ring', 2 if drag else 3.8), ('orbit-dot', 4.8)):
            self.angles[group] = (self.angles[group]+dt*tau/period) % tau
        if action in ('LEFT_CLICK', 'RIGHT_CLICK', 'DOUBLE_CLICK') and action != self.last_action:
            self.click_at = now
        if click_event is not None and click_event != self.click_event:
            self.click_at = click_event
            self.click_event = click_event
        self.last_action = action
        for shape, layers in self.items:
            angle = self.angles.get(shape.group, 0)
            scale, opacity = 1., 1.
            if shape.group == 'rune':
                breath = (1-cos(now*tau/2.6))/2
                scale, opacity = (1.045 if drag else 1+.025*breath), .86+.14*breath
            if shape.group == 'pulse-ring':
                progress = (now-self.click_at)/.45
                opacity = .9*(1-progress) if 0 <= progress < 1 else 0.
                scale = .65+.8*min(1, max(0, progress))
            c, s = cos(angle)*scale, sin(angle)*scale
            coords = []
            for x, y in shape.points:
                x, y = x-256, y-256
                coords.extend(((256+x*c-y*s)*self.size/512, (256+x*s+y*c)*self.size/512))
            for item, color, base_opacity in layers:
                self.canvas.coords(item, *coords)
                self.canvas.itemconfigure(item, fill=tint(color, opacity*base_opacity),
                                          state='normal' if opacity > .01 else 'hidden')
