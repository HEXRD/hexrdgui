from PySide2.QtCore import QObject

from hexrd.ui.ui_loader import UiLoader


class CalibrationCrystalSliderWidget(QObject):

    def __init__(self, parent=None):
        super(CalibrationCrystalSliderWidget, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_crystal_slider_widget.ui', parent)
