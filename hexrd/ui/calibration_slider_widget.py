from PySide2.QtCore import QObject, QTimer, Signal

import numpy as np

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class CalibrationSliderWidget(QObject):

    # Conversions from configuration value to slider value and back
    CONF_VAL_TO_SLIDER_VAL = 10
    SLIDER_VAL_TO_CONF_VAL = 0.1

    def __init__(self, parent=None):
        super(CalibrationSliderWidget, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_slider_widget.ui', parent)

        self.update_gui_from_config()

        self.timer = None

        self.setup_connections()

    def setup_connections(self):
        self.ui.detector.currentIndexChanged.connect(
            self.update_gui_from_config)
        for widget in self.config_widgets():
            widget.valueChanged.connect(self.update_widget_counterpart)
            widget.valueChanged.connect(self.update_config_from_gui)

        self.ui.sb_translation_range.valueChanged.connect(self.update_ranges)
        self.ui.sb_tilt_range.valueChanged.connect(self.update_ranges)
        self.ui.sb_beam_range.valueChanged.connect(self.update_ranges)

    def update_ranges(self):
        r = self.ui.sb_translation_range.value()
        slider_r = r * self.CONF_VAL_TO_SLIDER_VAL
        for w in self.translation_widgets():
            v = w.value()
            r_val = slider_r if w.objectName().startswith('slider') else r
            w.setRange(v - r_val / 2.0, v + r_val / 2.0)

        r = self.ui.sb_tilt_range.value()
        slider_r = r * self.CONF_VAL_TO_SLIDER_VAL
        for w in self.tilt_widgets():
            v = w.value()
            r_val = slider_r if w.objectName().startswith('slider') else r
            w.setRange(v - r_val / 2.0, v + r_val / 2.0)

        r = self.ui.sb_beam_range.value()
        slider_r = r * self.CONF_VAL_TO_SLIDER_VAL
        for w in self.beam_widgets():
            v = w.value()
            r_val = slider_r if w.objectName().startswith('slider') else r
            w.setRange(v - r_val / 2.0, v + r_val / 2.0)

    def current_detector(self):
        return self.ui.detector.currentText()

    def current_detector_dict(self):
        return HexrdConfig().get_detector(self.current_detector())

    def translation_widgets(self):
        # Let's take advantage of the naming scheme
        prefixes = ['sb', 'slider']
        root = 'translation'
        suffixes = ['0', '1', '2']
        widget_names = [
            '_'.join([p, root, s])
            for p in prefixes
            for s in suffixes
        ]

        return [getattr(self.ui, x) for x in widget_names]

    def tilt_widgets(self):
        # Let's take advantage of the naming scheme
        prefixes = ['sb', 'slider']
        root = 'tilt'
        suffixes = ['0', '1', '2']
        widget_names = [
            '_'.join([p, root, s])
            for p in prefixes
            for s in suffixes
        ]

        return [getattr(self.ui, x) for x in widget_names]

    def transform_widgets(self):
        return self.translation_widgets() + self.tilt_widgets()

    def beam_widgets(self):
        # Let's take advantage of the naming scheme
        prefixes = ['sb', 'slider']
        roots = ['energy', 'azimuth', 'polar']
        suffixes = ['0']
        widget_names = [
            '_'.join([p, r, s])
            for p in prefixes
            for r in roots
            for s in suffixes
        ]

        return [getattr(self.ui, x) for x in widget_names]

    def config_widgets(self):
        return self.transform_widgets() + self.beam_widgets()

    def all_widgets(self):
        return self.config_widgets() + [self.ui.detector]

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
        value = sender.value()

        prefix, root, ind = name.split('_')

        if prefix == 'slider':
            value *= self.SLIDER_VAL_TO_CONF_VAL
        else:
            value *= self.CONF_VAL_TO_SLIDER_VAL

        counter = 'slider' if prefix == 'sb' else 'sb'

        counter_widget_name = '_'.join([counter, root, ind])
        counter_widget = getattr(self.ui, counter_widget_name)

        blocked = counter_widget.blockSignals(True)
        try:
            counter_widget.setValue(value)
        finally:
            counter_widget.blockSignals(blocked)

    def update_gui_from_config(self):
        self.update_detectors_from_config()

        previously_blocked = self.block_all_signals()
        try:
            for widget in self.config_widgets():
                self.update_widget_value(widget)

        finally:
            self.unblock_all_signals(previously_blocked)

        self.update_ranges()

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

        # Take advantage of the widget naming scheme
        prefix, key, ind = name.split('_')
        ind = int(ind)

        if prefix == 'slider':
            val *= self.SLIDER_VAL_TO_CONF_VAL

        if key in ['tilt', 'translation']:
            det = self.current_detector_dict()
            if key == 'tilt':
                # Convert to radians before saving
                val = np.radians(val)

            det['transform'][key]['value'][ind] = val

            # Since we modify the value directly instead of letting the
            # HexrdConfig() do it, let's also emit the signal it would
            # have emitted.
            HexrdConfig().detector_transform_modified.emit(
                self.current_detector()
            )
        else:
            iconfig = HexrdConfig().config['instrument']
            if key == 'energy':
                iconfig['beam'][key]['value'] = val
                HexrdConfig().update_active_material_energy()
            elif key == 'polar':
                iconfig['beam']['vector']['polar_angle']['value'] = val
            else:
                iconfig['beam']['vector'][key]['value'] = val

    def update_widget_value(self, widget):
        name = widget.objectName()

        # Take advantage of the widget naming scheme
        prefix, key, ind = name.split('_')
        ind = int(ind)

        if key in ['tilt', 'translation']:
            det = self.current_detector_dict()
            val = det['transform'][key]['value'][ind]
        else:
            iconfig = HexrdConfig().config['instrument']
            if key == 'energy':
                val = iconfig['beam'][key]['value']
            elif key == 'polar':
                val = iconfig['beam']['vector']['polar_angle']['value']
            else:
                val = iconfig['beam']['vector'][key]['value']

        if key == 'tilt':
            # Convert to degrees
            val = np.degrees(val)

        if prefix == 'slider':
            val *= self.CONF_VAL_TO_SLIDER_VAL

        # Make sure the widget's range will accept the value
        if val < widget.minimum():
            widget.setMinimum(val)
        elif val > widget.maximum():
            widget.setMaximum(val)

        widget.setValue(val)
