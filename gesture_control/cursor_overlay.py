"""Optional click-through Windows cursor decoration, independent of control."""

from dataclasses import replace
import ctypes as ct
import logging
import math
from threading import Event, Thread
from time import monotonic

log = logging.getLogger(__name__)
SIZE = 144
CENTER = SIZE // 2
TRANSPARENT_COLOR = '#ff00ff'
# Layered + transparent + tool window + no activation.
OVERLAY_STYLE = 0x00080000 | 0x20 | 0x80 | 0x08000000


def rune_strokes(phase=0.):
    """Small geometric glyphs: no font dependency and a clear cursor center."""
    glyphs = (((-3, 5), (-3, -5), (3, 1), (3, -5), (3, 5)),
              ((-3, 5), (-3, -5), (3, -2), (-3, 1), (3, 5)),
              ((0, 5), (0, -5), (-4, -1), (0, 2), (4, -2)),
              ((-3, -5), (3, 5), (0, 0), (-3, 5), (3, -5)),
              ((-3, 5), (-3, -5), (3, -1), (-3, 0)),
              ((-3, 5), (0, -5), (3, 5), (-2, 1), (2, 1)))
    strokes = []
    for i in range(24):
        angle = phase + (i+.5) * math.tau / 24
        c, s = math.cos(angle), math.sin(angle)
        points = []
        for x, y in glyphs[i % len(glyphs)]:
            points.extend((CENTER + (49+y)*c-x*s, CENTER + (49+y)*s+x*c))
        strokes.append(tuple(points))
    return strokes


def draw_sigil(canvas, full=True, pressed=False):
    """Vector interpretation of Руны.png; hollow center, no bitmap background."""
    canvas.delete('all')
    bright = '#dbffff' if pressed else '#82eaff'

    def ring(radius, strong=True):
        for width, color in (((5, '#062b68'), (3, '#087ddd'), (1, bright)) if strong
                             else ((1, '#259dff'),)):
            canvas.create_oval(CENTER-radius, CENTER-radius, CENTER+radius, CENTER+radius,
                               outline=color, width=width)

    def glow_line(points):
        for width, color in ((5, '#072458'), (3, '#076dde'), (1, bright)):
            canvas.create_line(*points, fill=color, width=width, joinstyle='round')

    if not full:
        canvas.create_oval(CENTER-17, CENTER-17, CENTER+17, CENTER+17,
                           outline=bright, width=1)
        return
    for radius in (34, 39, 41, 59, 61):
        ring(radius, radius in (34, 41, 61))
    for stroke in rune_strokes():
        glow_line(stroke)
    # Fine dotted band between the inner circle and the rune band.
    for i in range(64):
        if i % 16 in (0, 1, 15):
            continue
        angle = i*math.tau/64
        x, y = CENTER+37*math.cos(angle), CENTER+37*math.sin(angle)
        r = 1.3 if i % 8 == 0 else .55
        canvas.create_oval(x-r, y-r, x+r, y+r, outline='#52cbff', width=1)
    # Four cardinal diamonds with long tips, repeated on the inner ring.
    for angle in (0, math.pi/2, math.pi, 3*math.pi/2):
        c, s = math.cos(angle), math.sin(angle)
        for radius, reach, spread in ((61, 9, 4), (36, 8, 3)):
            points = []
            for radial, tangent in ((-reach, 0), (-1, -spread), (reach, 0),
                                     (1, spread), (-reach, 0)):
                points.extend((CENTER+(radius+radial)*c-tangent*s,
                               CENTER+(radius+radial)*s+tangent*c))
            glow_line(points)


class CursorOverlay:
    def __init__(self, mode='FULL', loss_delay_ms=2000, clock=monotonic, external=False):
        self.external = external
        self.rendered = False
        self.position = None
        self.secondary = None
        self.clock = clock
        self.loss_delay = loss_delay_ms/1000
        self.loss_started = None
        self.recovering = False
        self.scroll_seen_at = float('-inf')
        self.scroll_loss = False
        self.mode = mode
        self.state = ('OFF', '-')
        self.updated_at = clock()
        self.click_event = None
        self.stopped = Event()
        self.error = None
        self.thread = Thread(target=self._run, name='cursor-decoration', daemon=True)

    def start(self):
        self.thread.start()

    def update(self, state, action, recovering=False):
        # Only the owning rune may show button feedback. The interaction action
        # is shared by both overlays, but their mouse ownership is not.
        if self.external:
            if action.startswith('SECONDARY_'):
                action = action.removeprefix('SECONDARY_')
            elif action != 'WORKSPACE_READY' and not action.startswith('ZOOM'):
                action = '-'
        elif action.startswith('SECONDARY_'):
            action = '-'
        now = self.clock()
        if state == 'ACTIVE' and action.startswith('SCROLL'):
            self.scroll_seen_at = now
        if recovering and not self.recovering:
            self.loss_started = now if self.state[0] == 'ACTIVE' else None
            self.scroll_loss = self.loss_started is not None and now-self.scroll_seen_at < .5
        elif not recovering:
            self.loss_started = None
            self.scroll_loss = False
            if state != 'ACTIVE':
                self.scroll_seen_at = float('-inf')
        self.recovering = recovering
        if action in ('LEFT_CLICK', 'RIGHT_CLICK', 'DOUBLE_CLICK') and action != self.state[1]:
            self.click_event = monotonic()
        self.state = (state, action)
        self.updated_at = now

    def update_secondary(self, state, action, position):
        if position is not None and state == 'ACTIVE' and self.secondary is None:
            self.secondary = CursorOverlay(self.mode, external=True)
            self.secondary.start()
        if self.secondary is not None:
            self.secondary.mode = self.mode
            self.secondary.position = position
            self.secondary.update(state if position is not None else 'OFF', action)

    def visible(self, now):
        if self.mode == 'OFF' or now-self.updated_at > .3:
            return False
        return self.state[0] == 'ACTIVE' or (self.recovering and self.loss_started is not None
                                             and (self.scroll_loss or now-self.loss_started < self.loss_delay))

    def cycle(self):
        modes = ('FULL', 'MINIMAL', 'OFF')
        self.mode = modes[(modes.index(self.mode)+1) % len(modes)]
        return self.mode

    def close(self):
        if self.secondary is not None:
            self.secondary.close()
        self.stopped.set()
        if self.thread.ident is not None:
            self.thread.join(2)
        if self.thread.is_alive():
            log.warning('cursor_overlay still stopping')

    def _run(self):
        import gc
        root = canvas = tick = renderer = None
        try:
            import tkinter as tk
            from .svg_rune import SvgRune, load_shapes
            from .native_cursor import WindowsCursorBackend, Point

            native = WindowsCursorBackend()
            user = native.user32
            signatures = {
                'GetAncestor': ([ct.c_void_p, ct.c_uint], ct.c_void_p),
                'GetWindowLongPtrW': ([ct.c_void_p, ct.c_int], ct.c_ssize_t),
                'SetWindowLongPtrW': ([ct.c_void_p, ct.c_int, ct.c_ssize_t], ct.c_ssize_t),
                'SetWindowPos': ([ct.c_void_p, ct.c_void_p, ct.c_int, ct.c_int,
                                  ct.c_int, ct.c_int, ct.c_uint], ct.c_int),
                'ShowWindow': ([ct.c_void_p, ct.c_int], ct.c_int),
                'SetLayeredWindowAttributes': ([ct.c_void_p, ct.c_uint32, ct.c_ubyte, ct.c_uint32], ct.c_int),
            }
            for name, (args, result) in signatures.items():
                fn = getattr(user, name)
                fn.argtypes, fn.restype = args, result
            with native.physical_coordinates():
                root = tk.Tk()
                root.withdraw()
                root.title('Gesture Control Cursor FX')
                root.overrideredirect(True)
                root.geometry(f'{SIZE}x{SIZE}+0+0')
                root.configure(bg=TRANSPARENT_COLOR)
                root.wm_attributes('-transparentcolor', TRANSPARENT_COLOR)
                canvas = tk.Canvas(root, width=SIZE, height=SIZE, bg=TRANSPARENT_COLOR,
                                   highlightthickness=0, borderwidth=0)
                canvas.pack()
                root.update_idletasks()
                hwnd = user.GetAncestor(root.winfo_id(), 2)
                if not hwnd:
                    raise OSError('Cannot obtain overlay window')
                style = user.GetWindowLongPtrW(hwnd, -20)
                ct.set_last_error(0)
                previous = user.SetWindowLongPtrW(hwnd, -20, style | OVERLAY_STYLE)
                if not previous and ct.get_last_error():
                    raise ct.WinError(ct.get_last_error())
                if not user.SetLayeredWindowAttributes(hwnd, 0x00ff00ff, 255, 1):
                    raise ct.WinError(ct.get_last_error())

                def tick():
                    nonlocal drawn, renderer
                    try:
                        if self.stopped.is_set():
                            root.quit()
                            return
                        state, action = self.state
                        point = Point()
                        if self.external or self.position is not None:
                            valid = self.position is not None
                            if valid:
                                point.x, point.y = native._screen().pixels(self.position)
                        else:
                            valid = bool(user.GetCursorPos(ct.byref(point)))
                        if not self.visible(monotonic()) or not valid:
                            self.rendered=False
                            user.ShowWindow(hwnd, 0)
                        else:
                            ready = action == 'WORKSPACE_READY'
                            appearance = (self.mode == 'FULL', 'PINCH' in action or 'DRAG' in action, ready)
                            if drawn is None or drawn[0] != appearance[0] or drawn[2] != ready or (not appearance[0] and drawn != appearance):
                                canvas.delete('all')
                                if appearance[0]:
                                    shapes = None
                                    if self.external or ready:
                                        shapes = [replace(s, stroke=('#FFD166' if ready else '#FF627D') if s.stroke!='none' else 'none',
                                                          fill=('#FFF0B0' if ready else '#FFB0BE') if s.fill!='none' else 'none') for s in load_shapes()]
                                    renderer = SvgRune(canvas, SIZE, shapes)
                                else:
                                    renderer = None
                                    draw_sigil(canvas, *appearance[:2])
                                    if self.external or ready:
                                        for item in canvas.find_all():
                                            canvas.itemconfigure(item, outline='#FFD166' if ready else '#FF627D')
                                drawn = appearance
                                canvas.create_oval(CENTER-3,CENTER-3,CENTER+3,CENTER+3,
                                                   fill='#ffffff',outline='#15202b',width=2,tags='aim-center')
                            if renderer is not None:
                                renderer.update(monotonic(), action, self.click_event)
                            canvas.tag_raise('aim-center')
                            # NOACTIVATE | SHOWWINDOW: never steal keyboard focus.
                            if not user.SetWindowPos(hwnd, ct.c_void_p(-1), point.x-CENTER,
                                                      point.y-CENTER, SIZE, SIZE, 0x10 | 0x40):
                                raise ct.WinError(ct.get_last_error())
                            self.rendered=True
                        root.after(33, tick)
                    except Exception as exc:
                        self.error = str(exc)
                        log.exception('cursor_overlay_failed')
                        root.quit()

                drawn = None
                root.after(0, tick)
                root.mainloop()
        except Exception as exc:
            self.error = str(exc)
            log.exception('cursor_overlay_unavailable')
        finally:
            self.rendered=False
            if root is not None:
                root.destroy()
            canvas = root = tick = renderer = None
            gc.collect()  # Tcl objects must be disposed on their owning thread.
