import signal
import logging
import pyuv
import greenlet

from ..const import READ, WRITE
from . import abc
from .watchers import UvFdListener

log = logging.getLogger('guv')


class Timer(abc.AbstractTimer):
    def __init__(self, timer_handle):
        """
        :type timer_handle: pyuv.Timer
        """
        self.timer_handle = timer_handle

    def cancel(self):
        if not self.timer_handle.closed:
            self.timer_handle.stop()
            self.timer_handle.close()


class Hub(abc.AbstractHub):
    def __init__(self):
        super().__init__()
        self.Listener = UvFdListener
        self.stopping = False
        self.running = False
        self.callbacks = []

        #: :type: pyuv.Loop
        self.loop = pyuv.Loop.default_loop()

        sig = pyuv.Signal(self.loop)
        sig.start(self.signal_received, signal.SIGINT)

        # fire immediate callbacks every loop iteration
        self.prepare = pyuv.Prepare(self.loop)
        self.prepare.start(self._fire_callbacks)

    def run(self):
        assert self is greenlet.getcurrent()

        if self.stopping:
            return

        if self.running:
            raise RuntimeError("The hub's runloop is already running")

        log.debug('Start runloop')
        try:
            self.running = True
            self.stopping = False
            self.loop.run(pyuv.UV_RUN_DEFAULT)
        finally:
            self.running = False
            self.stopping = False

    def abort(self):
        print()
        log.debug('Abort loop')
        if self.running:
            self.stopping = True

        self.loop.stop()

    def _fire_callbacks(self, prepare_handle):
        """Fire immediate callbacks
        """
        callbacks = self.callbacks
        self.callbacks = []
        for cb, args, kwargs in callbacks:
            cb(*args, **kwargs)

    def schedule_call_now(self, cb, *args, **kwargs):
        self.callbacks.append((cb, args, kwargs))

    def schedule_call_global(self, seconds, cb, *args, **kwargs):
        def timer_callback(timer_handle):
            cb(*args, **kwargs)

            # required for cleanup
            if not timer_handle.closed:
                timer_handle.stop()
                timer_handle.close()

        timer_handle = pyuv.Timer(self.loop)
        timer_handle.start(timer_callback, seconds, 0)

        return Timer(timer_handle)

    def add(self, evtype, fd, cb, tb):
        """Signals an intent to or write a particular file descriptor

        Signature of Callable cb: cb(fd: int)

        :param str evtype: either the constant READ or WRITE
        :param int fd: file number of the file of interest
        :param cb: callback which will be called when the file is ready for reading/writing
        :param tb: throwback used to signal (into the greenlet) that the file was closed
        :return: listener
        :rtype: self.Listener
        """

        def pyuv_cb(poll_handle, events, errno):
            """Read callback for pyuv

            pyuv requires a callback with this signature

            :type poll_handle: pyuv.Poll
            :type events: int
            :type errno: int
            """
            cb()

        poll_handle = pyuv.Poll(self.loop, fd)

        # create and add listener object
        listener = UvFdListener(evtype, fd, poll_handle)
        self._add_listener(listener)

        # start the pyuv Poll object
        flags = 0
        if evtype == READ:
            flags = pyuv.UV_READABLE
        elif evtype == WRITE:
            flags = pyuv.UV_WRITABLE

        poll_handle.start(flags, pyuv_cb)

        # self.debug()
        return listener

    def remove(self, listener):
        """Remove listener

        :param listener: listener to remove
        :type listener: self.Listener
        """
        super()._remove_listener(listener)
        # log.debug('call w.handle.stop(), fd: {}'.format(listener.handle.fileno()))

        # initiate correct cleanup sequence (these three statements are critical)
        listener.handle.ref = False
        listener.handle.stop()
        listener.handle.close()
        listener.handle = None
        # self.debug()

    def signal_received(self, sig_handle, signo):
        """Signal handler for pyuv.Signal

        pyuv.Signal requies a callback with the following signature::

            Callable(signal_handle, signal_num)

        :type sig_handle: pyuv.Signal
        :type signo: int
        """
        if signo == signal.SIGINT:
            sig_handle.stop()
            self.abort()
            self.parent.throw(KeyboardInterrupt)

    def _debug(self):
        msg = ['', '---------- hub state ----------']
        msg.append('listeners: {}'.format(self.listeners))
        msg.append('poll handles:')

        for h in self.loop.handles:
            if h.closed:
                msg.append('fd: {}, active: {}, closed: {}, handle: {}'
                           .format(None, h.active, h.closed, h))
                continue
            if hasattr(h, 'fileno'):
                msg.append('fd: {}, active: {}, closed: {}, handle: {}'
                           .format(h.fileno(), h.active, h.closed, h))

        msg.append('---------- end report ----------')
        log.debug('\n'.join(msg))
