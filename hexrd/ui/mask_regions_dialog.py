from PySide2.QtCore import QObject

from hexrd.ui.ui_loader import UiLoader


class MaskRegionsDialog(QObject):

    def __init__(self, parent=None):
        super(MaskRegionsDialog, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('mask_regions_dialog.ui', parent)
    
    def show(self):
        self.ui.show()
