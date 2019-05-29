from PySide2.QtCore import QFile
from PySide2.QtUiTools import QUiLoader

from .image_viewer import ImageViewer
from .menu_bar import MenuBar
from .main_window import MainWindow
from .status_bar import StatusBar

class UiLoader(QUiLoader):
    def __init__(self, parent=None):
        super(UiLoader, self).__init__(parent)

        self.registerCustomWidget(ImageViewer)
        self.registerCustomWidget(MainWindow)
        self.registerCustomWidget(MenuBar)
        self.registerCustomWidget(StatusBar)

    def load_file(self, file_path):
        """Load a UI file and return the widget"""
        try:
            f = QFile(file_path)
            f.open(QFile.ReadOnly)
            return self.load(f)
        finally:
            f.close()
