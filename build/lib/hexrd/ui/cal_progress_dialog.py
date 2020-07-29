from PySide2.QtCore import Qt
from PySide2.QtWidgets import QProgressDialog


class CalProgressDialog(QProgressDialog):

    def __init__(self, parent=None):
        super(CalProgressDialog, self).__init__(parent)

        self.setWindowTitle('Calibration Running')
        self.setLabelText('Please wait...')

        # Indeterminate state
        self.setRange(0, 0)

        # No cancel button
        self.setCancelButton(None)

        # No close button in the corner
        self.setWindowFlags((self.windowFlags() | Qt.CustomizeWindowHint) &
                            ~Qt.WindowCloseButtonHint)

        # This is necessary to prevent the dialog from automatically
        # appearing after it is initialized
        self.reset()

    def keyPressEvent(self, e):
        # Do not let the user close the dialog by pressing escape
        if e.key() != Qt.Key_Escape:
            super(CalProgressDialog, self).keyPressEvent(e)
