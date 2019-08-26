from PySide2.QtCore import QObject, QTimer, Signal

import numpy as np

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class CalibrationSliderWidget(QObject):

    """Emitted when a value changed after waiting a short time"""
    value_changed = Signal()

    def __init__(self, parent=None):
        super(CalibrationSliderWidget, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_slider_widget.ui', parent)

        self.setup_ranges()
        self.update_gui_from_config()

        self.timer = None

        self.setup_connections()

    def setup_connections(self):
        self.ui.detector.currentIndexChanged.connect(
            self.update_gui_from_config)
        for widget in self.transform_widgets():
            widget.valueChanged.connect(self.update_widget_counterpart)
            widget.valueChanged.connect(self.update_config_from_gui)

    def setup_ranges(self):
        for widget in self.transform_widgets():
            name = widget.objectName()

            # Take advantage of the widget naming scheme
            root = name.split('_')[1]

            if root == 'tilt':
                # The range is always -180 to 180 degrees
                widget.setRange(-180.0, 180.0)
            elif root == 'translation':
                # For now, the range is always -5000 to 5000
                widget.setRange(-5000, 5000)

    def current_detector(self):
        return self.ui.detector.currentText()

    def current_detector_dict(self):
        return HexrdConfig().get_detector(self.current_detector())

    def transform_widgets(self):
        # Let's take advantage of the naming scheme
        prefixes = ['sb', 'slider']
        roots = ['translation', 'tilt']
        suffixes = ['0', '1', '2']

        widget_names = [
            '_'.join([p, r, s])
            for p in prefixes
            for r in roots
            for s in suffixes
        ]

        return [getattr(self.ui, x) for x in widget_names]

    def all_widgets(self):
        return self.transform_widgets() + [self.ui.detector]

    def block_all_signals(self):
        previously_blocked = []
        all_widgets = self.all_widgets()

        for widget in all_widgets:
            previously_blocked.append(widget.blockSignals(True))

        return previously_blocked

    def unblock_all_signals(self, previously_blocked):
        all_widgets = self.all_widgets()

        for block, widget in zip(previously_blocked, all_widgets):
            widget.blockSignals(block)

    def on_detector_changed(self):
        self.update_gui_from_config()

    def update_widget_counterpart(self):
        sender = self.sender()
        name = sender.objectName()

        prefix, root, ind = name.split('_')

        counter = 'slider' if prefix == 'sb' else 'sb'

        counter_widget_name = '_'.join([counter, root, ind])
        counter_widget = getattr(self.ui, counter_widget_name)

        blocked = counter_widget.blockSignals(True)
        try:
            counter_widget.setValue(sender.value())
        finally:
            counter_widget.blockSignals(blocked)

    def update_gui_from_config(self):
        self.update_detectors_from_config()

        previously_blocked = self.block_all_signals()
        try:
            det = self.current_detector_dict()
            for widget in self.transform_widgets():
                name = widget.objectName()

                # Take advantage of the widget naming scheme
                key = name.split('_')[1]
                ind = int(name.split('_')[2])

                val = det['transform'][key]['value'][ind]
                if key == 'tilt':
                    # Convert to degrees
                    val = np.degrees(val)

                widget.setValue(val)
        finally:
            self.unblock_all_signals(previously_blocked)

    def update_detectors_from_config(self):
        widget = self.ui.detector

        old_detector = self.current_detector()
        old_detectors = [widget.itemText(x) for x in range(widget.count())]
        detectors = HexrdConfig().get_detector_names()

        if old_detectors == detectors:
            # The detectors didn't change. Nothing to update
            return

        blocked = widget.blockSignals(True)
        try:
            widget.clear()
            widget.addItems(detectors)
            if old_detector in detectors:
                # Switch to the old detector if possible
                widget.setCurrentText(old_detector)

        finally:
            widget.blockSignals(blocked)

    def update_config_from_gui(self, val):
        """This function only updates the sender value"""
        sender = self.sender()
        name = sender.objectName()

        det = self.current_detector_dict()

        # Take advantage of the widget naming scheme
        key = name.split('_')[1]
        ind = int(name.split('_')[2])

        if key == 'tilt':
            # Convert to radians before saving
            val = np.radians(val)

        det['transform'][key]['value'][ind] = val

        if self.timer is None:
            self.timer = QTimer()
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.value_changed)

        self.timer.start(100)
