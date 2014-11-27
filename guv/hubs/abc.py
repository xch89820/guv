from abc import ABCMeta, abstractmethod
import greenlet
import sys
import traceback

from ..const import READ, WRITE


class AbstractTimer(metaclass=ABCMeta):
    """Timer interface

    This is required for anything depending on this interface, such as :func:`hubs.trampoline`.
    """

    @abstractmethod
    def cancel(self):
        """Cancel the timer
        """
        pass


class AbstractListener(metaclass=ABCMeta):
    def __init__(self, evtype, fd):
        """
        :param str evtype: the constant hubs.READ or hubs.WRITE
        :param int fd: fileno
        """
        assert evtype in [READ, WRITE]
        self.evtype = evtype
        self.fd = fd
        self.greenlet = greenlet.getcurrent()

    def __repr__(self):
        return '{0}({1.evtype}, {1.fd})'.format(type(self).__name__, self)

    __str__ = __repr__


class AbstractHub(greenlet.greenlet, metaclass=ABCMeta):
    def __init__(self):
        super().__init__()
        self.listeners = {READ: {}, WRITE: {}}
        self.Listener = AbstractListener
        self.stopping = False

        self._debug_exceptions = True

    @abstractmethod
    def run(self, *args, **kwargs):
        """Run event loop
        """

    @abstractmethod
    def abort(self):
        """Stop the runloop
        """
        pass

    @abstractmethod
    def schedule_call_now(self, cb, *args, **kwargs):
        """Schedule a callable to be called on the next event loop iteration

        This is faster than calling :meth:`schedule_call_global(0, ...)`

        :param Callable cb: callback to call after timer fires
        :param args: positional arguments to pass to the callback
        :param kwargs: keyword arguments to pass to the callback
        """
        pass

    @abstractmethod
    def schedule_call_global(self, seconds, cb, *args, **kwargs):
        """Schedule a callable to be called after 'seconds' seconds have elapsed. The timer will NOT
        be canceled if the current greenlet has exited before the timer fires.

        :param float seconds: number of seconds to wait
        :param Callable cb: callback to call after timer fires
        :param args: positional arguments to pass to the callback
        :param kwargs: keyword arguments to pass to the callback
        :return: timer object that can be cancelled
        :rtype: hubs.abc.Timer
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def remove(self, listener):
        """Remove listener

        :param listener: listener to remove
        :type listener: self.Listener
        """
        pass

    def switch(self):
        """Switch to the hub greenlet
        """
        assert greenlet.getcurrent() is not self, 'Cannot switch to the hub from the hub'
        return super().switch()

    def _squelch_generic_exception(self, exc_info):
        if self._debug_exceptions:
            traceback.print_exception(*exc_info)
            sys.stderr.flush()

    def _add_listener(self, listener):
        """Add listener to internal dictionary

        :type listener: abc.AbstractListener
        :raise RuntimeError: if attempting to add multiple listeners with the same `evtype` and `fd`
        """
        evtype = listener.evtype
        fd = listener.fd

        bucket = self.listeners[evtype]
        if fd in bucket:
            raise RuntimeError('Multiple {evtype} on {fd} not supported'
                               .format(evtype=evtype, fd=fd))
        else:
            bucket[fd] = listener

    def _remove_listener(self, listener):
        """Remove listener

        :param listener: listener to remove
        :type listener: self.Listener
        """
        self.listeners[listener.evtype][listener.fd] = None
        del self.listeners[listener.evtype][listener.fd]
