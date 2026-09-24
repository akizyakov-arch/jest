"""Windows tray service; callbacks only enqueue actions for the Tk thread."""
import logging
from threading import Event, Thread

log = logging.getLogger(__name__)


def tray_image():
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (64,64), (0,0,0,0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4,4,60,60), fill='#18232E', outline='#55CFFF', width=3)
    draw.ellipse((12,12,52,52), outline='#55CFFF', width=2)
    draw.line((32,18,32,46), fill='#E9FAFF', width=3)
    draw.line((21,30,32,20), fill='#55CFFF', width=3)
    draw.line((32,42,44,30), fill='#55CFFF', width=3)
    return image


class TrayService:
    def __init__(self, enqueue):
        self.enqueue = enqueue
        self.icon = self.thread = None
        self.ready = Event()
        self.stopping = Event()
        self.error = ''
        self.state, self.mode = 'OFF', 'FULL'

    @property
    def available(self):
        return self.ready.is_set() and not self.error and not self.stopping.is_set() and self.thread.is_alive()

    def _action(self, name, value=None):
        def callback(icon, item):
            if not self.stopping.is_set():
                self.enqueue((name,value))
        return callback

    def start(self):
        if self.thread is not None:
            return
        self.thread = Thread(target=self._run, name='gesture-tray', daemon=True)
        self.thread.start()

    def _run(self):
        try:
            import pystray
            item, menu = pystray.MenuItem, pystray.Menu
            effects = menu(*(item(label,self._action('fx',mode),
                checked=lambda item, mode=mode: self.mode==mode, radio=True)
                for label,mode in (('Полные','FULL'),('Минимальные','MINIMAL'),('Выключены','OFF'))))
            self.icon = pystray.Icon('gesture-control',tray_image(),'Gesture Control',menu(
                item('Открыть окно',self._action('show'),default=True),
                item(lambda item: 'Состояние: '+self.state,None,enabled=False),
                menu.SEPARATOR,
                item('Включить / продолжить',self._action('start')),
                item('Пауза',self._action('pause')),
                item('Выключить камеру',self._action('stop')),
                item('Эффекты руны',effects),
                item('Настройки',self._action('settings')),
                menu.SEPARATOR,
                item('Выход',self._action('exit'))))
            def setup(icon):
                if self.stopping.is_set():
                    icon.stop()
                    return
                icon.visible = True
                self.ready.set()
            self.icon.run(setup=setup)
        except Exception as exc:
            self.error = str(exc)
            log.exception('tray_failed')
        finally:
            self.ready.clear()

    def update(self, state, mode):
        if (state,mode)==(self.state,self.mode):
            return
        self.state,self.mode = state,mode
        if self.available:
            try:
                self.icon.title = 'Gesture Control — '+state
                self.icon.update_menu()
            except Exception as exc:
                self.error = str(exc)
                log.exception('tray_update_failed')

    def close(self):
        self.stopping.set()
        if self.icon is not None:
            self.icon.stop()
        if self.thread is not None:
            self.thread.join(2)
