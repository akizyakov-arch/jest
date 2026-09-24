"""Run tracking/control independently of the native window event pump."""

from threading import Event, RLock, Thread


class ControlLoop:
    def __init__(self, update, on_failure):
        self.update, self.on_failure = update, on_failure
        self.lock = RLock()
        self.stopped = Event()
        self.error = None
        self.thread = Thread(target=self._run, name='gesture-control', daemon=True)

    def start(self):
        self.thread.start()

    def _run(self):
        try:
            while not self.stopped.is_set():
                with self.lock:
                    if self.update():
                        break
                self.stopped.wait(.005)
        except Exception as exc:
            self.error = exc
            try:
                self.on_failure()
            except Exception:
                pass  # Preserve the original failure; the input lease also expires.
        finally:
            self.stopped.set()

    def close(self):
        self.stopped.set()
        if self.thread.ident is not None:
            self.thread.join(3)
        if self.thread.is_alive():
            raise RuntimeError('Control worker did not stop within 3 seconds')
