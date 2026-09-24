"""Input executes in a separate process with a latched, 400 ms heartbeat lease."""

import logging
import multiprocessing as mp
from threading import Lock
from time import monotonic

from .command_engine import CommandEngine
from .events import CommandType
from .native_cursor import WindowsCursorBackend

log = logging.getLogger(__name__)


class InputLease:
    def __init__(self, backend, clock=monotonic, timeout=.4):
        self.backend, self.clock, self.timeout = backend, clock, timeout
        self.engine = CommandEngine(backend, clock)
        self.deadline = None
        self.fault = False

    def stop(self):
        self.deadline = None
        try:
            self.engine.stop()
        finally:
            restore=getattr(self.backend,'set_cursor_hidden',None)
            if restore is not None:
                restore(False)

    def check(self):
        if self.deadline is not None and self.clock() >= self.deadline:
            self.fault = True
            self.stop()
        # Retry failed releases on every worker tick, with no new commands.
        if not self.engine.enabled and (self.engine.buttons or self.engine.keys or getattr(self.backend,'cursor_hidden',False)):
            self.stop()

    def request(self, kind, value=None):
        self.check()
        if kind == 'stop':
            self.stop()
            return None
        if kind == 'arm':
            self.stop()
            self.engine.session_id = value-1
            self.engine.activate()
            self.fault = False
            self.deadline = self.clock()+self.timeout
            return None
        if kind == 'cursor_visibility' and not value:
            setter=getattr(self.backend,'set_cursor_hidden',None)
            if setter is not None: setter(False)
            return None
        if self.fault or not self.engine.enabled:
            raise OSError('Input watchdog stopped the session. Click Resume')
        if kind == 'cursor_visibility':
            self.backend.set_cursor_hidden(bool(value))
        elif kind == 'pulse':
            self.deadline = self.clock()+self.timeout
        elif kind == 'anchor':
            return self.backend.anchor()
        elif kind == 'double_click_limits':
            return self.backend.double_click_limits()
        elif kind == 'send':
            accepted = self.engine.submit(value)
            if (not accepted and value.type == CommandType.POINTER_MOVE
                    and value.session_id == self.engine.session_id):
                return False
            if not accepted:
                raise OSError('Input command expired or belongs to an old session')
            return True
        else:
            raise ValueError('Unknown input request')


def input_worker(connection, backend_factory=WindowsCursorBackend, timeout=.4):
    lease = None
    try:
        lease = InputLease(backend_factory(), timeout=timeout)
        connection.send((True, None))
        while True:
            try:
                lease.check()
            except OSError:
                pass  # Retain ownership and retry release; commands remain disabled.
            if not connection.poll(.02):
                continue
            kind, value = connection.recv()
            if kind == 'close':
                lease.stop()
                connection.send((True, None))
                break
            try:
                result = lease.request(kind, value)
                connection.send((True, result))
            except Exception as exc:
                lease.fault = True
                try:
                    lease.stop()
                except OSError:
                    pass
                connection.send((False, str(exc)))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        if lease is not None:
            # Parent death / pipe loss follows the same ownership cleanup path.
            for _ in range(3):
                try:
                    lease.stop()
                    break
                except OSError:
                    continue
        connection.close()
        if lease is not None and (lease.engine.buttons or lease.engine.keys or getattr(lease.backend,'cursor_hidden',False)):
            # A successful process exit is the parent's cleanup acknowledgement.
            # Never allow replacement when releasing owned input failed.
            raise RuntimeError('Input watchdog exited with unreleased input')


class GuardedInputBackend:
    def __init__(self, backend_factory=WindowsCursorBackend, response_timeout=.2):
        self.backend_factory = backend_factory
        self.response_timeout = response_timeout
        self._lock = Lock()
        self._closed = False
        self._start_worker()

    def _start_worker(self):
        self._cursor_hidden=False
        context = mp.get_context('spawn')
        self.connection, child = context.Pipe()
        self._broken = False
        self._last_pulse = float('-inf')
        self.process = context.Process(target=input_worker, args=(child, self.backend_factory),
                                       name='gesture-input-watchdog')
        try:
            self.process.start()
        except Exception:
            self.connection.close()
            raise
        finally:
            child.close()
        try:
            self._receive(5)
        except Exception:
            self.connection.close()
            self._broken = True
            self.process.join(1)
            raise

    def _receive(self, timeout=None):
        timeout = self.response_timeout if timeout is None else timeout
        if not self.connection.poll(timeout):
            raise OSError(f'Input watchdog response timed out after {timeout*1000:.0f} ms')
        success, result = self.connection.recv()
        if not success:
            raise ValueError(result)
        return result

    def _request(self, kind, value=None):
        with self._lock:
            if self._broken or self._closed:
                raise OSError('Input watchdog disconnected. Click Resume to reconnect')
            try:
                started = monotonic()
                self.connection.send((kind, value))
                result = self._receive()
                elapsed = monotonic()-started
                if elapsed > .08:
                    log.warning('input_response_slow request=%s elapsed_ms=%.0f', kind, elapsed*1000)
                return result
            except (EOFError, OSError) as exc:
                self._broken = True
                self.connection.close()  # EOF makes the worker release owned input.
                log.error('input_connection_lost request=%s alive=%s exitcode=%s reason=%s',
                          kind, self.process.is_alive(), self.process.exitcode, exc)
                raise OSError('Input watchdog disconnected. Click Resume to reconnect') from exc
            except ValueError as exc:
                raise OSError(str(exc)) from exc

    def recover(self):
        """Explicit Resume only; never replay a possibly executed command."""
        with self._lock:
            if self._closed:
                raise OSError('Input backend is closed')
            if not self._broken:
                return
            self.process.join(0)
            if self.process.is_alive():
                raise OSError('Input watchdog is still releasing input. Try Resume shortly')
            if self.process.exitcode != 0:
                raise OSError('Input watchdog cleanup was not confirmed; restart control mode')
            self.process.close()
            self._start_worker()
            log.info('input_watchdog_reconnected')

    def begin_session(self, session_id):
        self._request('arm', session_id)
        self._cursor_hidden=False
        self._last_pulse = monotonic()

    def end_session(self):
        if not self._broken:
            self._request('stop')
        self._cursor_hidden=False

    def set_cursor_hidden(self, hidden):
        if hidden != self._cursor_hidden:
            self._request('cursor_visibility',hidden)
            self._cursor_hidden=hidden

    def heartbeat(self):
        now = monotonic()
        if now-self._last_pulse >= .05:
            self._request('pulse')
            self._last_pulse = now

    def anchor(self):
        return self._request('anchor')

    def double_click_limits(self):
        return self._request('double_click_limits')

    def send(self, command):
        return self._request('send', command)

    def release(self, buttons, keys):
        self.end_session()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if not self._broken:
                # Closing prevents new sessions, but the stop request is allowed.
                with self._lock:
                    self.connection.send(('close', None))
                    self._receive()
        finally:
            self.connection.close()
            self._broken = True
            self.process.join(2)
        if self.process.is_alive():
            raise OSError('Input watchdog is still stopping')
