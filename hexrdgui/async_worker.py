# This class was modified from the following example online:
# https://www.learnpyqt.com/courses/concurrent-execution/multithreading-pyqt-applications-qthreadpool/

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

import inspect
import traceback
import sys


class AsyncWorkerSignals(QObject):
    '''
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        `tuple` (exctype, value, traceback.format_exc() )

    result
        `object` data returned from processing, anything

    progress
        `int` indicating % progress

    '''
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)


class AsyncWorker(QRunnable):
    '''
    AsyncWorker

    Inherits from QRunnable to handler worker thread setup, signals and
    wrap-up.

    :param callback: The function callback to run on this worker thread.
                     Supplied args and kwargs will be passed through to
                     the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function

    '''

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = AsyncWorkerSignals()
        self.print_error_traceback = True

        # If the function signature accepts an 'update_progress'
        # function, set it to emit the progress signal.
        if 'update_progress' in inspect.getfullargspec(self.fn)[0]:
            self.kwargs['update_progress'] = self.signals.progress.emit

    @Slot()
    def run(self):
        '''
        Initialise the runner function with passed args, kwargs.
        '''

        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            if self.print_error_traceback:
                traceback.print_exc()

            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            # Return the result of the processing
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()
