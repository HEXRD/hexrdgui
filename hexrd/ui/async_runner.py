from PySide2.QtCore import QThreadPool
from PySide2.QtWidgets import QMessageBox

from hexrd.ui.async_worker import AsyncWorker
from hexrd.ui.progress_dialog import ProgressDialog


class AsyncRunner:

    def __init__(self, parent):
        self.parent = parent

        self.thread_pool = QThreadPool(parent)

        self.progress_dialog = ProgressDialog(parent)

        # Some defaults...
        self.progress_dialog.setWindowTitle('Working...')
        self.progress_dialog.setRange(0, 0)

        self.reset_callbacks()

    def run(self, f):
        worker = AsyncWorker(f)
        self.thread_pool.start(worker)

        if self.success_callback:
            worker.signals.result.connect(self.success_callback)

        if self.error_callback:
            worker.signals.error.connect(self.error_callback)
        else:
            worker.signals.error.connect(self.on_async_error)

        worker.signals.finished.connect(self.reset_callbacks)
        worker.signals.finished.connect(self.progress_dialog.accept)
        self.progress_dialog.exec_()

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
        msg_box.exec_()
