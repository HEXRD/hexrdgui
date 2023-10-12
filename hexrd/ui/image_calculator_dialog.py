from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Signal
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from hexrd import imageseries

from hexrd.ui.image_calculator import IMAGE_CALCULATOR_OPERATIONS
from hexrd.ui.image_file_manager import ImageFileManager
from hexrd.ui.progress_dialog import ProgressDialog
from hexrd.ui.ui_loader import UiLoader


class ImageCalculatorDialog(QObject):

    accepted = Signal()
    rejected = Signal()

    def __init__(self, images_dict, parent=None):
        super().__init__(parent)
        self.ui = UiLoader().load_file('image_calculator_dialog.ui', parent)

        self.images_dict = images_dict

        self.progress_dialog = ProgressDialog(self.ui)

        self.setup_detectors()
        self.setup_operations()
        self.setup_connections()

    def setup_connections(self):
        self.ui.select_operand_file.clicked.connect(self.select_operand_file)
        self.ui.accepted.connect(self.on_accepted)
        self.ui.rejected.connect(self.on_rejected)

    def show(self):
        self.ui.show()

    def hide(self):
        self.ui.hide()

    def on_accepted(self):
        if not self.validate():
            self.show()
            return

        self.accepted.emit()

    def on_rejected(self):
        self.rejected.emit()

    def validate(self):
        def error(msg):
            print(msg)
            QMessageBox.critical(self.ui, 'Image Calculator', msg)
            return False

        if not self.operand_file:
            return error('Please select an operand file')

        if not Path(self.operand_file).exists():
            msg = f'Operand file:\n\n"{self.operand_file}"\n\n does not exist'
            return error(msg)

        # Try to load the operand
        try:
            self.operand
        except Exception as e:
            return error(f'Failed to load operand with message:\n\n{e}')

        # Ensure the operand and the detector image are the same shape
        if self.detector_image.shape != self.operand.shape:
            msg = (
                f'Operand shape "{self.operand.shape}" does not match '
                f'detector image shape "{self.detector_image.shape}"'
            )
            return error(msg)

        return True

    def setup_detectors(self):
        w = self.ui.detector

        w.clear()
        w.addItems(list(self.images_dict))
        w.setEnabled(w.count() > 1)

    def setup_operations(self):
        w = self.ui.operation

        w.clear()
        w.addItems(list(IMAGE_CALCULATOR_OPERATIONS))

    def select_operand_file(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self.ui, 'Select Operand File')

        if selected_file:
            self.operand_file = selected_file

    @property
    def detector(self):
        return self.ui.detector.currentText()

    @property
    def detector_image(self):
        return self.images_dict[self.detector]

    @property
    def operation(self):
        return self.ui.operation.currentText()

    @property
    def operation_function(self):
        return IMAGE_CALCULATOR_OPERATIONS[self.operation]

    @property
    def operand_file(self):
        return self.ui.operand_file.text()

    @operand_file.setter
    def operand_file(self, v):
        self.ui.operand_file.setText(v)

    @property
    def operand(self):
        # Return the cached result if possible. Otherwise, generate a new one.
        prev_operand_file = getattr(self, '_prev_operand_file', None)
        prev_operand = getattr(self, '_prev_operand', None)

        if self.operand_file == prev_operand_file:
            # Return the cached result
            return prev_operand

        operand = self.load_operand_file()

        self._prev_operand = operand
        self._prev_operand_file = self.operand_file

        return operand

    def load_operand_file(self):
        options = {
            'empty-frames': 0,
            'max-file-frames': 0,
            'max-total-frames': 0,
        }

        # Open it in the standard hexrdgui way
        ims = ImageFileManager().open_file(self.operand_file, options)

        # Check if we need to perform aggregation
        if len(ims) > 1:
            ims = self.aggregate_imageseries(ims)
            if ims is None:
                msg = 'Aggregation is required for multi-frame images'
                raise Exception(msg)

        return ims[0]

    def aggregate_imageseries(self, ims):
        aggregation_methods = {
            'Maximum': imageseries.stats.max_iter,
            'Median': imageseries.stats.median_iter,
            'Average': imageseries.stats.average_iter,
        }

        msg = (
            f'Image Series is length {len(ims)}\n\nSelect aggregation '
            'method'
        )
        method, ok = QInputDialog.getItem(self.ui, 'Image Calculator', msg,
                                          list(aggregation_methods), 0, False)
        if not ok:
            return

        agg_func = aggregation_methods[method]

        self.progress_dialog.setWindowTitle('Aggregating Image Series')
        self.progress_dialog.setRange(0, 100)
        self.progress_dialog.reset_messages()
        self.progress_dialog.ui.show()

        num_frames = len(ims)
        step = int(num_frames / 100)
        step = step if step > 2 else 2
        nchunk = int(num_frames / step)
        if nchunk > num_frames or nchunk < 1:
            # One last sanity check
            nchunk = num_frames

        for i, img in enumerate(agg_func(ims, nchunk)):
            self.progress_dialog.setValue((i + 1) / nchunk * 100)
            # Make sure the progress dialog gets redrawn
            QCoreApplication.processEvents()

        self.progress_dialog.ui.hide()

        return [img]

    def calculate(self):
        # These should already be numpy arrays
        terms = [
            self.detector_image,
            self.operand,
        ]

        # Run the operation
        result = self.operation_function(*terms)

        # Convert to original dtype
        result = result.astype(self.detector_image.dtype)

        # Turn it into an imageseries and return
        return imageseries.open(None, 'array', data=result)
