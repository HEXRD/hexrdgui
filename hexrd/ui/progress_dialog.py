from PySide2.QtCore import Qt
from PySide2.QtWidgets import QProgressDialog


class ProgressDialog(QProgressDialog):

    def __init__(self, parent=None):
        super(ProgressDialog, self).__init__(parent)

        # Some default window title and text
        self.setWindowTitle('Hexrd')
        self.setLabelText('Please wait...')

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
            super(ProgressDialog, self).keyPressEvent(e)
