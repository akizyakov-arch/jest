"""Native desktop interface based on the four supplied Gesture Control sketches."""

from collections import deque
from dataclasses import replace
import json
from math import cos, sin, pi
from pathlib import Path
from statistics import median
from time import monotonic
from threading import Thread
from queue import SimpleQueue, Empty
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .tray import TrayService
from .calibration import STEPS, calibrated_settings
from .settings import Settings, save_settings, _atomic_write
from .svg_rune import SvgRune
from .pointer import palm_geometry
from .camera_devices import enumerate_devices, read_default, write_default

BG, PANEL, CARD = '#151617', '#222222', '#202020'
BORDER, BLUE, TEXT, MUTED = '#383838', '#55CFFF', '#F1F2F4', '#B2B7BF'
SELECT, DANGER = '#222C39', '#361F25'
PAGES = ('Главный экран', 'Жесты', 'Камера и калибровка', 'Настройки и профили')

GESTURES = (
    ('Pointer', 'Наведение ладонью или пальцем.\nТочка выбирается в опциях.', 'gesture_pointer', 'Основные'),
    ('Pinch', 'Большой + указательный: клик.\nУдержание и движение: drag.', 'gesture_pinch', 'Основные'),
    ('Средняя кнопка', 'Два пальца: один средний клик.\nОпустите пальцы для повтора.', 'gesture_middle', 'Основные'),
    ('Active / Pause', 'Ладонь: активация и возврат.\nПауза: кнопка или горячая клавиша.', None, 'Основные'),
    ('Правый / двойной клик', 'Большой + средний: правый.\nДва левых щипка: двойной.', None, 'Дополнительные'),
    ('Back / Esc', 'Удержите кулак ½ секунды: Esc.\nРазожмите руку для повтора.', 'gesture_cancel', 'Дополнительные'),
    ('Переключение окон', 'Кистью: короткое смахивание вбок.\nВправо — следующее; влево — назад.', 'gesture_swipe', 'Дополнительные'),
    ('Вторая рука / Zoom', 'Щипки — ЛКМ/ПКМ; два пальца — СКМ.\nОбе руки в щипке — Zoom.', 'second_hand_enabled', 'Профессиональные'),
    ('Рабочие столы', 'Любая рука: щепотка 3 пальцами, 0,3 с.\nЗолотая руна: вверх — обзор, вниз — стол.', 'gesture_workspace', 'Дополнительные'),
    ('Профили 3D / Video', 'Архитектура и шаблоны готовы.\nДействия программ будут добавлены.', 'future', 'Профессиональные'),
)


class Slider(tk.Canvas):
    """Keyboard-accessible native slider matching the supplied visual target."""
    def __init__(self, master, value, low, high, step, command, commit=None, background=PANEL):
        super().__init__(master, bg=background, highlightthickness=0, takefocus=True, cursor='hand2')
        self.value, self.low, self.high, self.step = value, low, high, step
        self.command, self.commit = command, commit
        self.bind('<Configure>', lambda event: self.draw())
        self.bind('<FocusIn>', lambda event: self.draw())
        self.bind('<FocusOut>', lambda event: self.draw())
        self.bind('<Button-1>', self.drag)
        self.bind('<B1-Motion>', self.drag)
        self.bind('<ButtonRelease-1>', lambda event: self.commit() if self.commit else None)
        self.bind('<Left>', lambda event: self.key(-1))
        self.bind('<Right>', lambda event: self.key(1))
        self.bind('<Up>', lambda event: self.key(1))
        self.bind('<Down>', lambda event: self.key(-1))

    def set_value(self, value):
        self.value = min(self.high, max(self.low, self.low+round((value-self.low)/self.step)*self.step))
        self.command(self.value)
        self.draw()

    def drag(self, event):
        self.focus_set()
        self.set_value(self.low+(self.high-self.low)*(event.x-12)/max(1,self.winfo_width()-24))

    def key(self, direction):
        self.set_value(self.value+direction*self.step)
        if self.commit:
            self.commit()
        return 'break'

    def draw(self):
        self.delete('all')
        w,h = self.winfo_width(), self.winfo_height()
        x = 12+(w-24)*(self.value-self.low)/(self.high-self.low)
        self.create_line(12,h/2,w-12,h/2,fill=BORDER,width=7,capstyle='round')
        self.create_line(12,h/2,x,h/2,fill=BLUE,width=7,capstyle='round')
        self.create_oval(x-10,h/2-10,x+10,h/2+10,fill=TEXT,outline=TEXT)
        if self.focus_get() == self:
            self.create_rectangle(1,1,w-1,h-1,outline=BLUE)


class DesktopApp:
    def __init__(self, root, controller):
        self.root, self.controller = root, controller
        self.settings = controller.settings
        self.devices = ()
        self.device_results = SimpleQueue()
        self.scanning = False
        self.default_path = controller.path.parent / 'camera-default.json'
        self.default_camera = read_default(self.default_path)
        self.restore_default = True
        self.camera_selection_required = False
        self.page = 0
        self.category = 'Основные'
        self.widgets = []
        self.status_items = {}
        self.calibration_points = None
        self.samples = deque(maxlen=12)
        self.last_frame_id = None
        self.notice = ''
        self.notice_until = 0.
        self.keyboard_seen = 0
        self.closing = False
        self.hidden = False
        self.tray_actions = SimpleQueue()
        self.tray = TrayService(self.tray_actions.put)
        self.tray.start()
        self._resize_job = None
        self.building = False
        self.camera_photo = self.rune = self.rune_canvas = None
        self.root.title('Gesture Control')
        self.root.configure(bg=BG)
        self.root.geometry('1440x900')
        self.root.minsize(1100, 720)
        self.root.protocol('WM_DELETE_WINDOW', self.hide_to_tray)
        self.root.bind('<Unmap>', self._minimized, add='+')
        self.root.bind('<Escape>', lambda event: self.pause())
        self.root.bind('<Control-s>', lambda event: self.save())
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', self._resize)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('GC.TCombobox', fieldbackground=CARD, background=SELECT, foreground=TEXT,
                        arrowcolor=BLUE, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        selectbackground=SELECT, selectforeground=TEXT, padding=10)
        style.map('GC.TCombobox', fieldbackground=[('readonly', CARD)], foreground=[('readonly', TEXT)])
        self.root.after(80, self.build)
        self.root.after(100, self.refresh)
        self.scan_cameras()

    def hide_to_tray(self):
        if self.closing:
            return
        if not self.tray.available:
            self.close()  # Never leave an inaccessible hidden application.
            return
        if self.calibration_points is not None:
            self.cancel_calibration()
        self.hidden = True
        self.root.withdraw()

    def _minimized(self, event):
        if event.widget == self.root and self.root.state() == 'iconic' and self.tray.available:
            self.hide_to_tray()

    def show_window(self):
        if self.closing:
            return
        self.hidden = False
        self.last_frame_id = None
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def poll_tray(self):
        for _ in range(16):
            try:
                action,value = self.tray_actions.get_nowait()
            except Empty:
                break
            if action == 'show':
                self.show_window()
            elif action == 'settings':
                self.show_window()
                self.navigate(3)
            elif action == 'exit':
                self.close()
                return
            elif action == 'pause':
                self.pause()
            elif action == 'fx':
                self.fx(value)
            elif action == 'start':
                if self.controller.snapshot.running:
                    self.controller.submit('start')
                elif self.scanning or self.camera_selection_required or not self.devices:
                    self.show_window()
                    self.notify('Выберите камеру на главном экране.')
                else:
                    self.start_camera()
            elif action == 'stop':
                self.controller.submit('stop')
        if self.hidden and not self.tray.available:
            self.show_window()
            self.notify('Значок трея недоступен. Окно восстановлено.')
        snap = self.controller.snapshot
        self.tray.update(snap.view.state, self.settings.visual_fx)

    def scan_cameras(self):
        if self.scanning:
            return
        self.scanning = True
        backend = self.default_camera.get('backend', self.settings.camera_backend) if self.restore_default else self.settings.camera_backend
        def work():
            try:
                self.device_results.put((enumerate_devices(backend), ''))
            except Exception as exc:
                self.device_results.put(((), str(exc)))
        Thread(target=work, name='camera-enumeration', daemon=True).start()

    def camera_picker(self, x, y, width):
        current = None if self.camera_selection_required else next((d for d in self.devices if d.index == self.settings.camera_index), None)
        self.combo(x, y, width, [d.label for d in self.devices],
                   current.label if current else 'Выберите камеру' if self.devices else 'Камеры не найдены', self.camera_selected)
        self.default_var = tk.BooleanVar(value=bool(current and current.path and
            current.path == self.default_camera.get('path') and current.backend == self.default_camera.get('backend')))
        check = tk.Checkbutton(self.root, text='Использовать по умолчанию', variable=self.default_var,
            command=self.set_default_camera, bg=PANEL, fg=TEXT, selectcolor=CARD,
            activebackground=PANEL, activeforeground=BLUE, font=self.font(12), anchor='w',
            state='normal' if current else 'disabled')
        self.place(check, x, y+47, width, 24)

    def set_default_camera(self):
        device = next((d for d in self.devices if d.index == self.settings.camera_index), None)
        try:
            write_default(self.default_path, device if self.default_var.get() else None)
            self.default_camera = read_default(self.default_path)
            self.notify('Камера по умолчанию сохранена.' if self.default_var.get() else 'Камера по умолчанию отключена.')
        except (OSError, ValueError) as exc:
            self.notify(exc)
        self.build()

    def start_camera(self):
        if self.scanning:
            self.notify('Дождитесь обновления списка камер.')
            return
        device = next((d for d in self.devices if d.index == self.settings.camera_index), None)
        if self.camera_selection_required or device is None:
            self.notify('Выберите подключённую камеру из списка.')
            return
        if self.settings.camera_backend != device.backend:
            self.settings = replace(self.settings, camera_backend=device.backend)
            self.controller.submit('apply', self.settings)
        self.controller.submit('start')

    def _resize(self, event):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self.build)

    def font(self, size=16, bold=False):
        return ('Segoe UI', -max(11, round(size*self.scale)), 'bold' if bold else 'normal')

    def xy(self, x, y):
        return self.ox+x*self.scale, self.oy+y*self.scale

    def panel(self, x, y, w, h, fill=PANEL, radius=24, outline=BORDER):
        x, y = self.xy(x, y)
        w, h, r = w*self.scale, h*self.scale, radius*self.scale
        points = []
        for cx,cy,start in ((x+w-r,y+r,-pi/2),(x+w-r,y+h-r,0),(x+r,y+h-r,pi/2),(x+r,y+r,pi)):
            for i in range(13):
                angle = start+i*pi/24
                points.extend((cx+r*cos(angle),cy+r*sin(angle)))
        return self.canvas.create_polygon(*points, fill=fill, outline=outline, width=1.3)

    def text(self, x, y, value, size=16, color=TEXT, bold=False, width=None, anchor='nw', tag=None):
        item = self.canvas.create_text(*self.xy(x, y), text=value, fill=color, font=self.font(size, bold),
            anchor=anchor, width=round(width*self.scale) if width else 0)
        if tag:
            self.status_items[tag] = item
        return item

    def place(self, widget, x, y, w, h):
        self.widgets.append(widget)
        px, py = self.xy(x, y)
        widget.place(x=round(px), y=round(py), width=round(w*self.scale), height=round(h*self.scale))
        return widget

    def button(self, label, x, y, w, command, *, active=False, danger=False, enabled=True, h=52):
        color = DANGER if danger else SELECT if active else CARD
        panel = self.panel(x, y, w, h, color, 18, '#CC3B4B' if danger else BLUE if active else BORDER)
        if enabled:
            self.canvas.tag_bind(panel, '<Button-1>', lambda event: command())
        b = tk.Button(self.root, text=label, command=command, font=self.font(12 if w < 80 else 15, True),
            bg=color, fg=TEXT if enabled else MUTED, activebackground=SELECT, activeforeground=TEXT,
            relief='flat', borderwidth=0, padx=0, pady=0, highlightthickness=1, highlightbackground=color,
            highlightcolor=BLUE, cursor='hand2' if enabled else 'arrow', takefocus=enabled,
            state='normal' if enabled else 'disabled', disabledforeground=MUTED)
        inset = 3 if w < 80 else 9
        return self.place(b, x+inset, y+4, w-2*inset, h-8)

    def combo(self, x, y, w, choices, value, callback):
        var = tk.StringVar(value=value)
        combo = ttk.Combobox(self.root, values=choices, textvariable=var, state='readonly',
                             style='GC.TCombobox', font=self.font(15))
        combo.bind('<<ComboboxSelected>>', lambda event: callback(var.get()))
        self.place(combo, x, y, w, 44)
        return combo

    def slider(self, label, name, x, y, w, low, high, resolution=1, convert=float, live=False):
        value = getattr(self.settings, name)
        self.text(x, y, label, 14, MUTED)
        value_id = self.text(x+w, y, f'{value:g}', 14, BLUE, anchor='ne')
        def changed(raw):
            if self.building:
                return
            val = convert(float(raw))
            try:
                self.settings = replace(self.settings, **{name: val})
                self.canvas.itemconfigure(value_id, text=f'{val:g}')
            except ValueError as exc:
                self.notify(str(exc))
        slider = Slider(self.root, value, low, high, resolution, changed, self.apply if live else None)
        self.place(slider, x-10, y+22, w+20, 44)

    def notify(self, text):
        self.notice, self.notice_until = str(text), monotonic()+7

    def navigate(self, page):
        if not self.collect():
            return
        self.page = page
        self.build()

    def build(self):
        if self.closing:
            return
        self._resize_job = None
        self.building = True
        for widget in self.widgets:
            widget.destroy()
        self.widgets.clear()
        self.canvas.delete('all')
        self.status_items.clear()
        self.rune = self.rune_canvas = self.camera_photo = None
        self.last_frame_id = None
        w, h = max(1100, self.canvas.winfo_width()), max(720, self.canvas.winfo_height())
        self.scale = min(w/1440, h/900)
        self.ox, self.oy = (w-1440*self.scale)/2, (h-900*self.scale)/2
        self.text(160, 36, 'GESTURE CONTROL', 18, MUTED, True)
        self.text(160, 66, 'Управление руками' if self.page == 0 else PAGES[self.page], 32, bold=True)
        self.text(920, 58, 'OFF', 15, BLUE, True, tag='state')
        self.button('Остановить', 1190, 40, 220, self.pause, danger=True)
        self.panel(28, 135, 72, 650)
        for i, (label, page) in enumerate((('Камера', 0), ('Опции', 3))):
            self.button(label, 32, 160+i*100, 64, lambda p=page: self.navigate(p), active=self.page == page, h=56)
        if self.page in (1, 2):
            self.button('Назад', 32, 360, 64, lambda: self.navigate(0), h=56)
        self.text(64, 735, 'GC', 18, BLUE, True, anchor='center')
        (self.home, self.gestures, self.camera_page, self.settings_page)[self.page]()
        self.text(128, 810, '', 15, MUTED, width=1280, tag='message')
        self.text(128, 859, f'Аварийная остановка: {self.settings.emergency_hotkey.upper()}    ·    Esc — пауза в окне приложения',
                  13, MUTED)
        self.building = False

    def home(self):
        self.panel(126, 135, 1286, 650, radius=32)
        self.camera_picker(164, 150, 294)
        self.button('Обновить', 759, 210, 135, self.scan_cameras, h=32)
        self.button('Точное наведение: '+('вкл' if self.settings.precision_mode else 'выкл'),
                    478, 210, 265, lambda: self.toggle('precision_mode'),
                    active=self.settings.precision_mode, h=32)
        self.button('Вторая рука: '+('вкл' if self.settings.second_hand_enabled else 'выкл'),
                    910, 210, 185, lambda: self.toggle('second_hand_enabled'),
                    active=self.settings.second_hand_enabled, h=32)
        self.text(1111, 218, '', 13, MUTED, tag='secondary')
        self.button('Включить / продолжить', 478, 150, 265,
                    self.start_camera, active=True)
        self.button('Пауза', 759, 150, 135, self.pause)
        self.button('Калибровка', 910, 150, 185, lambda: self.navigate(2))
        self.button('Выключить камеру', 1111, 150, 265, lambda: self.controller.submit('stop'))
        self.panel(164, 250, 1212, 340, CARD, 30)
        self.preview_size = (1200, 328)
        self.camera_image = self.canvas.create_image(*self.xy(770, 420), anchor='center')
        self.text(770, 420, 'Включите камеру — здесь появятся рука и рабочая область',
                  21, MUTED, anchor='center', tag='camera_empty')
        self.text(186, 552, 'Камера выключена', 13, MUTED, tag='fps')
        self.text(1354, 557, '', 13, BLUE, anchor='ne', tag='action')
        for x in (164, 576, 988):
            self.panel(x, 611, 388, 146, CARD, 26)
        self.text(186, 627, 'Ладонь' if self.settings.pointer_anchor == 'PALM' else 'Указательный палец', 21, bold=True)
        self.slider('Скорость курсора', 'cursor_max_speed', 186, 667, 338, .3, 10, .1, live=True)
        self.text(598, 627, 'Плавность', 21, bold=True)
        self.button('Антидрожь: '+('вкл' if self.settings.suppress_jitter else 'выкл'),
                    758, 624, 190, lambda: self.toggle('suppress_jitter'),
                    active=self.settings.suppress_jitter, h=32)
        self.slider('Сглаживание, мс', 'cursor_response_ms', 598, 667, 338, 20, 180, 5, int, live=True)
        self.button('Жесты', 1006, 625, 164, lambda: self.navigate(1))
        self.button('Клавиатура', 1180, 625, 178, self.keyboard)
        self.button('Сохранить настройки', 1006, 691, 352, self.save, h=46)

    def fx(self, mode):
        self.settings = replace(self.settings, visual_fx=mode)
        self.controller.submit('fx', mode)
        self.build()

    def pause(self):
        self.controller.emergency_stop()
        self.controller.submit('pause')
        self.notify('Управление приостановлено. Для возврата нажмите «Продолжить».')

    def keyboard(self):
        try:
            from .screen_keyboard import open_screen_keyboard
            open_screen_keyboard()
        except OSError as exc:
            self.notify(exc)

    def gestures(self):
        self.panel(126, 135, 1286, 650)
        self.text(164, 164, 'Библиотека жестов', 26, bold=True)
        self.text(164, 205, 'Настройте доступные жесты. Изменения применяются с безопасной паузой.', 15, MUTED)
        for x, label, width in ((164, 'Основные', 140), (316, 'Дополнительные', 185), (513, 'Профессиональные', 214)):
            self.button(label, x, 246, width, lambda c=label: self.set_category(c), active=self.category == label, h=44)
        items = [g for g in GESTURES if g[3] == self.category]
        self.combo(1010, 246, 334, ('Два пальца: средняя кнопка', 'Два пальца: прокрутка'),
                   'Два пальца: средняя кнопка' if self.settings.two_finger_action == 'MIDDLE' else 'Два пальца: прокрутка',
                   self.two_finger_action)
        for i, (name, description, setting, category) in enumerate(items):
            if setting == 'gesture_middle' and self.settings.two_finger_action == 'SCROLL':
                name, description, setting = 'Scroll', 'Два пальца: свайп и прокрутка.\nСогните их для переноса руки.', 'gesture_scroll'
            x, y = 164+(i%3)*390, 322+(i//3)*194
            self.panel(x, y, 360, 166, CARD, 24)
            self.text(x+24, y+24, name, 19, bold=True)
            self.text(x+24, y+62, description, 14, MUTED, width=310)
            if setting == 'future':
                self.button('В разработке', x+20, y+114, 178, lambda: None, enabled=False, h=44)
            elif setting:
                on = getattr(self.settings, setting)
                self.button('Включён' if on else 'Выключен', x+20, y+114, 166,
                            lambda key=setting: self.toggle(key), active=on, h=44)
            else:
                self.text(x+24, y+124, 'Всегда доступно' if name == 'Active / Pause' else 'В составе Pinch', 13, BLUE)

    def two_finger_action(self, label):
        self.settings = replace(self.settings, two_finger_action='MIDDLE' if label.endswith('кнопка') else 'SCROLL')
        self.apply()
        self.build()

    def set_category(self, category):
        self.category = category
        self.build()

    def toggle(self, name):
        changes = {name: not getattr(self.settings, name)}
        if name == 'second_hand_enabled' and changes[name]:
            changes['max_hands'] = 2
        self.settings = replace(self.settings, **changes)
        self.apply()
        self.build()

    def camera_page(self):
        self.panel(126, 135, 860, 650)
        self.panel(1005, 135, 407, 650)
        self.text(164, 165, 'Камера и отслеживание', 25, bold=True)
        self.text(164, 202, 'Камера выключена', 14, MUTED, tag='fps')
        self.panel(164, 256, 784, 420, BG, 24)
        self.preview_size = (778, 414)
        self.camera_image = self.canvas.create_image(*self.xy(556, 466), anchor='center')
        self.text(556, 462, 'Включите камеру для предпросмотра', 19, MUTED, anchor='center', tag='camera_empty')
        self.button('Включить камеру', 164, 708, 235, self.start_camera, active=True)
        self.button('Повторить', 411, 708, 166, lambda: self.controller.submit('retry'))
        self.button('Остановить', 589, 708, 170, lambda: self.controller.submit('stop'))
        self.button('Загрузить профиль', 771, 708, 177, self.load_camera_profile)
        self.text(1038, 165, 'Камера', 19, bold=True)
        self.camera_picker(1038, 195, 335)
        self.text(1038, 268, 'Калибровка', 20, bold=True)
        step = 'Пять точек: центр и удобные края' if self.calibration_points is None else f'{len(self.calibration_points)+1} из 5 · {STEPS[len(self.calibration_points)]}'
        self.text(1038, 302, step, 14, MUTED, width=336)
        if self.calibration_points is None:
            self.button('Начать калибровку', 1038, 338, 335, self.begin_calibration, active=True)
        else:
            self.button('Зафиксировать точку', 1038, 338, 335, self.capture_calibration, active=True)
            anchor = 'центр ладони' if self.settings.pointer_anchor == 'PALM' else 'кончик указательного'
            self.text(1038, 398, f'Держите {anchor}\nв выбранной точке около ½ секунды.', 13, MUTED)
        self.text(1038, 451, 'Рабочая область', 19, bold=True)
        self.area_slider('Ширина', 488, True)
        self.area_slider('Высота', 572, False)
        self.button('50%', 1038, 657, 96, lambda: self.area_preset(.5))
        self.button('100%', 1148, 657, 96, lambda: self.area_preset(1.))
        self.button('Отмена', 1258, 657, 115, self.cancel_calibration)
        self.button('Сохранить профиль камеры', 1038, 722, 335, self.save_camera_profile, active=True)

    def area_slider(self, label, y, horizontal):
        size = ((self.settings.work_area_right-self.settings.work_area_left) if horizontal else
                (self.settings.work_area_bottom-self.settings.work_area_top))
        value_item = self.text(1038, y, f'{label}: {size*100:.0f}%', 14, MUTED)
        def change(raw):
            if self.building:
                return
            size = float(raw)/100
            a, b = ('work_area_left', 'work_area_right') if horizontal else ('work_area_top', 'work_area_bottom')
            center = max(size/2, min(1-size/2, (getattr(self.settings, a)+getattr(self.settings, b))/2))
            self.settings = replace(self.settings, **{a: center-size/2, b: center+size/2})
            self.canvas.itemconfigure(value_item, text=f'{label}: {size*100:.0f}%')
        control = Slider(self.root, size*100, 20, 100, 5, change, self.apply)
        self.place(control, 1028, y+22, 355, 44)

    def camera_selected(self, label):
        device = next((d for d in self.devices if d.label == label), None)
        if device is None:
            return
        self.camera_selection_required = False
        self.settings = replace(self.settings, camera_index=device.index, camera_backend=device.backend)
        self.calibration_points = None
        self.samples.clear()
        self.apply()
        self.build()

    def area_preset(self, size):
        self.settings = replace(self.settings, work_area_left=(1-size)/2, work_area_top=(1-size)/2,
                                work_area_right=(1+size)/2, work_area_bottom=(1+size)/2)
        self.apply()
        self.build()

    def begin_calibration(self):
        if not self.controller.snapshot.running:
            self.notify('Сначала включите камеру.')
            return
        self.pause()
        self.calibration_points = []
        self.samples.clear()
        self.build()

    def cancel_calibration(self):
        self.calibration_points = None
        self.samples.clear()
        self.build()

    def capture_calibration(self):
        snap = self.controller.snapshot
        if (snap.view.state == 'ACTIVE' or snap.camera_index != self.settings.camera_index
                or not snap.frame or monotonic()-snap.frame.frame.captured_at > .15):
            self.notify('Нужен свежий кадр камеры и приостановленное управление.')
            return
        if len(self.samples) < 8 or self.samples[-1][0]-self.samples[0][0] < .2:
            self.notify('Покажите одну руку и ненадолго удержите палец неподвижно.')
            return
        points = [p for _, p in self.samples]
        if any(max(p[i] for p in points)-min(p[i] for p in points) > .04 for i in (0, 1)):
            self.notify('Палец движется. Удержите его неподвижно и повторите.')
            return
        self.calibration_points.append(tuple(median(p[i] for p in points) for i in (0, 1)))
        self.samples.clear()
        if len(self.calibration_points) == 5:
            try:
                self.settings = calibrated_settings(self.settings, self.calibration_points)
                self.apply()
                self.notify('Калибровка применена. Сохраните профиль камеры.')
            except ValueError as exc:
                self.notify(exc)
            self.calibration_points = None
        self.build()

    def save_camera_profile(self):
        frame = self.controller.snapshot.frame
        if (not frame or monotonic()-frame.frame.captured_at > .3 or
                self.controller.snapshot.camera_index != self.settings.camera_index):
            self.notify('Для профиля нужен свежий кадр выбранной камеры.')
            return
        path = self.controller.path.parent / f'camera-{self.settings.camera_index}.json'
        data = {'schema_version': 1, 'camera_index': self.settings.camera_index,
                'width': frame.frame.width, 'height': frame.frame.height,
                'pointer_mirrored': self.settings.pointer_mirrored,
                'pointer_anchor': self.settings.pointer_anchor,
                'area': [self.settings.work_area_left, self.settings.work_area_top,
                         self.settings.work_area_right, self.settings.work_area_bottom]}
        try:
            _atomic_write(path, json.dumps(data, indent=2)+'\n')
            self.save()
        except OSError as exc:
            self.notify(exc)

    def load_camera_profile(self):
        frame = self.controller.snapshot.frame
        if (not frame or monotonic()-frame.frame.captured_at > .3 or
                self.controller.snapshot.camera_index != self.settings.camera_index):
            self.notify('Сначала включите нужную камеру.')
            return
        path = self.controller.path.parent / f'camera-{self.settings.camera_index}.json'
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if (data['schema_version'] != 1 or data['camera_index'] != self.settings.camera_index or
                (data['width'], data['height']) != (frame.frame.width, frame.frame.height) or
                data['pointer_mirrored'] != self.settings.pointer_mirrored or
                data.get('pointer_anchor', 'INDEX') != self.settings.pointer_anchor):
                raise ValueError('Профиль не соответствует камере, разрешению, зеркальности или точке курсора.')
            left, top, right, bottom = data['area']
            self.settings = replace(self.settings, work_area_left=left, work_area_top=top,
                                    work_area_right=right, work_area_bottom=bottom)
            self.apply()
            self.build()
            self.notify('Профиль камеры загружен.')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.notify(f'Не удалось загрузить профиль: {exc}')

    def settings_page(self):
        self.panel(126, 135, 1286, 650)
        self.text(164, 165, 'Настройки', 26, bold=True)
        self.text(164, 205, 'Изменения применяются с паузой. Настройки можно сохранить и экспортировать.', 15, MUTED)
        for x, y in ((164, 260), (762, 260), (164, 465), (762, 465)):
            self.panel(x, y, 570, 180, CARD, 24)
        self.text(188, 280, 'Управление', 20, bold=True)
        self.text(188, 325, 'Ведущая рука', 14, MUTED)
        hands = {'Первая в кадре': 'FIRST', 'Левая': 'LEFT', 'Правая': 'RIGHT'}
        self.combo(420, 306, 282, tuple(hands), next(k for k, v in hands.items() if v == self.settings.primary_hand),
                   lambda label: self.draft(primary_hand=hands[label]))
        self.text(188, 366, 'Правый щипок', 14, MUTED)
        self.combo(420, 350, 282, ('Средний палец', 'Безымянный палец'),
                   'Средний палец' if self.settings.right_pinch_finger == 'MIDDLE' else 'Безымянный палец',
                   lambda label: self.draft(right_pinch_finger='MIDDLE' if label.startswith('Средний') else 'RING'))
        self.text(188, 409, 'Точка курсора', 14, MUTED)
        self.combo(420, 394, 282, ('Центр ладони', 'Указательный палец'),
                   'Центр ладони' if self.settings.pointer_anchor == 'PALM' else 'Указательный палец',
                   lambda label: self.draft(pointer_anchor='PALM' if label == 'Центр ладони' else 'INDEX'))
        self.text(786, 280, 'Visual FX', 20, bold=True)
        self.text(786, 325, 'Режим руны', 14, MUTED)
        self.combo(1012, 313, 286, ('FULL', 'MINIMAL', 'OFF'), self.settings.visual_fx, lambda v: self.draft(visual_fx=v))
        self.text(786, 375, 'Ожидание руки, мс', 14, MUTED)
        self.entry('rune_loss_delay_ms', 1080, 360, 218, int)
        self.button('Курсор Windows: '+('скрывать' if self.settings.hide_windows_cursor else 'показывать'),
                    786,408,512,lambda:self.toggle('hide_windows_cursor'),
                    active=self.settings.hide_windows_cursor,h=28)
        self.text(188, 484, 'Система', 20, bold=True)
        self.text(188, 530, 'Аварийная клавиша', 14, MUTED)
        self.entry('emergency_hotkey', 420, 516, 282, str)
        self.text(188, 586, 'Автозапуск и трей\nпоявятся позже', 13, MUTED, width=220)
        self.button('Параметры щипка', 426, 592, 276, self.pinch_settings, h=40)
        self.text(786, 484, 'Профиль и прокрутка', 20, bold=True)
        profiles = {p.name+(' · шаблон' if p.template else ''): p.id for p in self.controller.profiles}
        self.combo(786, 522, 240, tuple(profiles), next(k for k,v in profiles.items() if v == self.settings.profile_id),
                   lambda label: self.draft(profile_id=profiles[label]))
        self.button('Инверсия: '+('да' if self.settings.scroll_invert else 'нет'), 1045, 522, 253,
                    lambda: self.invert_scroll(), active=self.settings.scroll_invert, h=44)
        self.text(786, 592, 'Скорость прокрутки', 14, MUTED)
        self.entry('scroll_sensitivity', 1080, 578, 218, float)
        self.button('Экспортировать', 164, 686, 248, self.export)
        self.button('Сбросить настройки', 426, 686, 255, self.reset_settings)
        self.button('Применить', 938, 686, 169, self.apply)
        self.button('Сохранить', 1121, 686, 211, self.save, active=True)

    def entry(self, name, x, y, width, convert):
        var = tk.StringVar(value=str(getattr(self.settings, name)))
        entry = tk.Entry(self.root, textvariable=var, bg=PANEL, fg=TEXT, insertbackground=BLUE,
                          relief='flat', highlightthickness=1, highlightbackground=BORDER,
                          highlightcolor=BLUE, font=self.font(15))
        self.place(entry, x, y, width, 44)
        def commit(event=None):
            try:
                self.settings = replace(self.settings, **{name: convert(var.get().strip())})
                return True
            except ValueError as exc:
                self.notify(exc)
                return False
        entry.bind('<FocusOut>', commit)
        entry.bind('<Return>', commit)
        entry.commit_value = commit

    def pinch_settings(self):
        if not self.collect():
            return
        self.pause()
        dialog = tk.Toplevel(self.root)
        dialog.title('Настройка щипка')
        dialog.configure(bg=PANEL)
        dialog.geometry('490x340')
        dialog.transient(self.root)
        dialog.grab_set()
        tk.Label(dialog, text='Расстояния относительно размера ладони', bg=PANEL, fg=TEXT,
                 font=('Segoe UI', 12, 'bold')).pack(pady=(20,14))
        fields = {}
        for name,label in (('pinch_on_ratio','Порог нажатия'),('pinch_off_ratio','Порог отпускания'),
                           ('pinch_aim_ratio','Ранняя фиксация')):
            row=tk.Frame(dialog,bg=PANEL); row.pack(fill='x',padx=24,pady=6)
            tk.Label(row,text=label,bg=PANEL,fg=TEXT,width=23,anchor='w').pack(side='left')
            value=tk.StringVar(value=str(getattr(self.settings,name)))
            tk.Entry(row,textvariable=value,bg=CARD,fg=TEXT,insertbackground=BLUE,width=14).pack(side='right')
            fields[name]=value
        error=tk.Label(dialog,text='',bg=PANEL,fg='#FF9DA6',wraplength=440)
        error.pack(pady=12)
        def commit():
            try:
                self.settings=replace(self.settings,**{key:float(value.get()) for key,value in fields.items()})
                self.apply()
                dialog.destroy()
            except ValueError as exc:
                error.configure(text=str(exc))
        tk.Button(dialog,text='Применить',command=commit,bg=SELECT,fg=TEXT,activebackground=SELECT,
                  activeforeground=TEXT,relief='flat',padx=30,pady=10).pack()

    def draft(self, **changes):
        self.settings = replace(self.settings, **changes)

    def invert_scroll(self):
        if not self.collect():
            return
        self.settings = replace(self.settings, scroll_invert=not self.settings.scroll_invert)
        self.build()

    def collect(self):
        for widget in self.widgets:
            if hasattr(widget, 'commit_value') and not widget.commit_value():
                return False
        from .hotkeys import parse_hotkey
        try:
            parse_hotkey(self.settings.emergency_hotkey)
            self.settings.__post_init__()
            return True
        except ValueError as exc:
            self.notify(exc)
            return False

    def apply(self):
        if self.collect():
            self.controller.submit('apply', self.settings)

    def save(self):
        if self.collect():
            self.controller.submit('save', self.settings)

    def export(self):
        if not self.collect():
            return
        self.pause()
        target = filedialog.asksaveasfilename(parent=self.root, title='Экспорт настроек',
            defaultextension='.json', filetypes=[('Настройки JSON', '*.json')], initialfile='gesture-settings.json')
        if target:
            try:
                save_settings(Path(target), self.settings)
                self.notify('Настройки экспортированы.')
            except OSError as exc:
                self.notify(exc)

    def reset_settings(self):
        self.pause()
        if messagebox.askyesno('Сброс настроек', 'Вернуть параметры интерфейса к исходным? Файл изменится только после сохранения.', parent=self.root):
            self.settings = Settings(visual_fx='FULL', work_area_left=.25, work_area_top=.25,
                                      work_area_right=.75, work_area_bottom=.75)
            self.apply()
            self.build()

    def _camera_frame(self, result):
        from PIL import Image, ImageTk, ImageDraw
        frame = result.frame
        image = Image.frombytes('RGB', (frame.width, frame.height), frame.pixels)
        mirrored = self.settings.preview_mirrored
        if mirrored:
            image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        image.thumbnail(tuple(round(value*self.scale) for value in self.preview_size), Image.Resampling.BILINEAR)
        draw = ImageDraw.Draw(image)
        from .preview import CONNECTIONS
        for hand in result.tracking.hands:
            pts = [((1-x if mirrored else x)*image.width, y*image.height) for x,y,z in hand.landmarks]
            if len(pts) != 21:
                continue
            for a,b in CONNECTIONS:
                draw.line((pts[a], pts[b]), fill=BLUE, width=2)
            for x,y in pts:
                draw.ellipse((x-3,y-3,x+3,y+3), fill=BLUE)
            anchor = palm_geometry(hand)[0] if self.settings.pointer_anchor == 'PALM' else hand.landmarks[8][:2]
            ax, ay = anchor
            ax = (1-ax if mirrored else ax)*image.width
            ay *= image.height
            draw.ellipse((ax-7,ay-7,ax+7,ay+7), outline='#FFFFFF', width=2)
        s = self.settings
        left,right = s.work_area_left,s.work_area_right
        if mirrored != s.pointer_mirrored:
            left,right = 1-right,1-left
        draw.rectangle((left*image.width,s.work_area_top*image.height,right*image.width,s.work_area_bottom*image.height),
                       outline=BLUE, width=2)
        self.camera_photo = ImageTk.PhotoImage(image, master=self.root)
        self.canvas.itemconfigure(self.camera_image, image=self.camera_photo)
        self.canvas.itemconfigure(self.status_items['camera_empty'], text='')

    def refresh(self):
        if not self.closing:
            self.poll_tray()
        if self.closing:
            if not self.controller.worker.thread.is_alive():
                self.root.destroy()
                return
            self.root.after(50, self.refresh)
            return
        try:
            devices, error = self.device_results.get_nowait()
        except Empty:
            pass
        else:
            self.scanning = False
            self.devices = devices
            if self.restore_default and not self.controller.snapshot.running:
                preferred = next((d for d in devices if d.path == self.default_camera.get('path')), None)
                if preferred:
                    self.settings = replace(self.settings, camera_index=preferred.index, camera_backend=preferred.backend)
                    self.controller.submit('apply', self.settings)
                elif self.default_camera:
                    self.camera_selection_required = True
                    self.notify('Камера по умолчанию не подключена. Выберите доступную.')
            self.restore_default = False
            if error:
                self.notify('Не удалось получить список камер: '+error)
            if self.page in (0, 2):
                self.build()
        snap = self.controller.snapshot
        if 'secondary' in self.status_items:
            label = ('Красная руна: выключена' if not self.settings.second_hand_enabled else
                     'Красная руна: рука видна' if snap.secondary_detected else
                     'Красная руна: ждём вторую руку')
            self.canvas.itemconfigure(self.status_items['secondary'], text=label,
                                      fill='#FF627D' if snap.secondary_detected else MUTED)
        if 'state' in self.status_items:
            self.canvas.itemconfigure(self.status_items['state'], text=snap.view.state)
            message = snap.error or (self.notice if monotonic() < self.notice_until else snap.notice)
            if snap.running and not snap.hotkey_ready:
                message = snap.error or 'Аварийная клавиша недоступна. Управление заблокировано.'
            elif not message:
                if snap.recovering:
                    message = 'Рука потеряна. Покажите одну открытую ладонь и удержите для возврата.'
                elif snap.view.state == 'ACTIVE':
                    message = 'Управление активно. Щипок — клик; два пальца — '+('средняя кнопка.' if self.settings.two_finger_action == 'MIDDLE' else 'прокрутка.')
                elif snap.view.state == 'PAUSED':
                    message = 'Пауза. Нажмите «Продолжить», затем покажите открытую ладонь.'
                else:
                    message = 'Покажите открытую ладонь для активации.' if snap.running else 'Камера выключена. Нажмите «Включить».'
            self.canvas.itemconfigure(self.status_items['message'], text=message,
                                      fill='#FF9DA6' if snap.error else MUTED)
        frame = snap.frame
        if frame and frame.frame.frame_id != self.last_frame_id:
            self.last_frame_id = frame.frame.frame_id
            if len(frame.tracking.hands) == 1:
                hand = frame.tracking.hands[0]
                x,y = palm_geometry(hand)[0] if self.settings.pointer_anchor == 'PALM' else hand.landmarks[8][:2]
                self.samples.append((frame.frame.captured_at, (1-x if self.settings.pointer_mirrored else x,y)))
            else:
                self.samples.clear()
            if not self.hidden and self.page in (0, 2) and hasattr(self, 'camera_image'):
                self._camera_frame(frame)
        if 'fps' in self.status_items:
            description = (f'Камера {self.settings.camera_index} · {frame.frame.width}×{frame.frame.height}\n'
                           f'{frame.capture_fps:.0f} FPS · распознавание {frame.inference_ms:.0f} мс' if frame else
                           'Камера запускается…' if snap.running else 'Камера выключена')
            self.canvas.itemconfigure(self.status_items['fps'], text=description)
        if self.page in (0, 2) and frame is None and self.camera_photo is not None:
            self.canvas.itemconfigure(self.camera_image, image='')
            self.camera_photo = None
            self.canvas.itemconfigure(self.status_items['camera_empty'], text='Камера недоступна' if snap.error else 'Ожидание камеры')
        if 'action' in self.status_items:
            action = f'Активация {snap.view.progress:.0%}' if snap.view.state == 'STANDBY' or snap.recovering else snap.view.action
            self.canvas.itemconfigure(self.status_items['action'], text=f'{snap.view.pose}  ·  {action}')
        if self.rune is not None:
            self.rune.update(monotonic(), snap.view.action)
        if snap.keyboard_request != self.keyboard_seen:
            self.keyboard_seen = snap.keyboard_request
            self.keyboard()
        self.root.after(50, self.refresh)

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.controller.close()
        self.tray.close()
        self.root.title('Gesture Control — завершение…')


def run_desktop(settings, path, model_path=None):
    from .desktop_controller import DesktopController
    from .model_assets import DEFAULT_MODEL
    root = tk.Tk()
    controller = DesktopController(settings, path, model_path=model_path or DEFAULT_MODEL)
    app = None
    try:
        app = DesktopApp(root, controller)
        root.mainloop()
    finally:
        controller.close()
        if app is not None:
            app.tray.close()
        controller.worker.thread.join(6)
    return 0
