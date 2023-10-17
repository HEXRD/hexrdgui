from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QMessageBox

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.progress_dialog import ProgressDialog


class AsyncRunner:

    def __init__(self, parent):
        self.parent = parent

        self.progress_dialog = ProgressDialog(parent)

        # Some defaults...
        self.progress_dialog.setWindowTitle('Working...')
        self.progress_dialog.setRange(0, 0)

        self.reset_callbacks()

    def run(self, f, *args, **kwargs):
        worker = AsyncWorker(f, *args, **kwargs)

        if self.success_callback:
            worker.signals.result.connect(self.success_callback)

        if self.error_callback:
            error_callback = self.error_callback
        else:
            error_callback = self.on_async_error

        worker.signals.error.connect(error_callback)
        worker.signals.finished.connect(self.on_worker_finished)

        # We must start the worker after creating all connections because
        # sometimes the worker will very quickly encounter an error, and
        # since the worker is running in another thread, if it encounters
        # an error and exits before the connections are made, Qt will
        # have a segmentation fault.
        self.thread_pool.start(worker)

        self.progress_dialog.exec()

    def on_worker_finished(self):
        self.reset_callbacks()
        # Sometimes the progress dialog seems to hang around for no apparent
        # reason, unless we close it in the next iteration of the event loop.
        # So don't close it yet, but close it soon.
        QTimer.singleShot(0, self.progress_dialog.accept)

    def reset_callbacks(self):
        self.success_callback = None
        self.error_callback = None

    @property
    def progress_title(self):
        return self.progress_dialog.windowTitle()

    @progress_title.setter
    def progress_title(self, title):
        self.progress_dialog.setWindowTitle(title)

    def on_async_error(self, t):
        exctype, value, traceback = t
        msg = f'An ERROR occurred: {exctype}: {value}.'
        msg_box = QMessageBox(QMessageBox.Critical, 'Error', msg)
        msg_box.setDetailedText(traceback)
        msg_box.exec()

    @property
    def thread_pool(self):
        return QThreadPool.globalInstance()
