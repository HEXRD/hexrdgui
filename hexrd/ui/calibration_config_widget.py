from PySide2.QtCore import QObject
from PySide2.QtWidgets import QComboBox, QLineEdit, QPushButton

from hexrd.ui import constants
from hexrd.ui.ui_loader import UiLoader

class CalibrationConfigWidget(QObject):

    def __init__(self, config, parent=None):
        super(CalibrationConfigWidget, self).__init__(parent)

        self.cfg = config

        loader = UiLoader()
        self.ui = loader.load_file('calibration_config_widget.ui', parent)

        self.detector_widgets_disabled = False

        self.setup_connections()

    def setup_connections(self):
        self.ui.cal_energy.valueChanged.connect(self.on_energy_changed)
        self.ui.cal_energy_wavelength.valueChanged.connect(
            self.on_energy_wavelength_changed)

        self.ui.cal_det_current.currentIndexChanged.connect(
            self.on_detector_changed)
        self.ui.cal_det_current.editTextChanged.connect(
            self.on_detector_name_edited)
        self.ui.cal_det_remove.clicked.connect(self.on_detector_remove_clicked)
        self.ui.cal_det_add.clicked.connect(self.on_detector_add_clicked)

        all_widgets = self.get_all_widgets()
        skip_widgets = ['cal_det_current', 'cal_det_add', 'cal_det_remove']
        for widget in all_widgets:
            if widget.objectName() in skip_widgets:
                continue

            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.update_config_from_gui)
            elif isinstance(widget, QLineEdit):
                widget.textEdited.connect(self.update_config_from_gui)
            elif isinstance(widget, QPushButton):
                widget.pressed.connect(self.update_config_from_gui)
            else:
                widget.valueChanged.connect(self.update_config_from_gui)

    def on_energy_changed(self):
        val = self.ui.cal_energy.value()

        block_signals = self.ui.cal_energy_wavelength.blockSignals(True)
        try:
            new_wavelength = constants.KEV_TO_WAVELENGTH / val
            self.ui.cal_energy_wavelength.setValue(new_wavelength)
        finally:
            self.ui.cal_energy_wavelength.blockSignals(block_signals)

    def on_energy_wavelength_changed(self):
        val = self.ui.cal_energy_wavelength.value()

        block_signals = self.ui.cal_energy.blockSignals(True)
        try:
            new_energy = constants.WAVELENGTH_TO_KEV / val
            self.ui.cal_energy.setValue(new_energy)
        finally:
            self.ui.cal_energy.blockSignals(block_signals)

    def on_detector_changed(self):
        self.update_detector_from_config()

    def enable_detector_widgets(self, enable=True):
        detector_widgets = self.cfg.get_detector_widgets()
        detector_widgets.remove('cal_det_add')
        for widget in detector_widgets:
            gui_widget = getattr(self.ui, widget)
            gui_widget.setEnabled(enable)

        self.detector_widgets_disabled = not enable

    def on_detector_name_edited(self):
        new_name = self.ui.cal_det_current.currentText()
        detector_names = self.cfg.get_detector_names()

        # Ignore it if there is already a detector with this name
        if new_name in detector_names:
            return

        # Get the old name from the underlying item
        idx = self.ui.cal_det_current.currentIndex()
        old_name = self.ui.cal_det_current.itemText(idx)

        self.ui.cal_det_current.setItemText(idx, new_name)
        self.cfg.rename_detector(old_name, new_name)

    def on_detector_remove_clicked(self):
        current_detector = self.get_current_detector()
        idx = self.ui.cal_det_current.currentIndex()

        self.cfg.remove_detector(current_detector)
        if idx > 0:
            self.ui.cal_det_current.setCurrentIndex(idx - 1)
        else:
            self.update_detector_from_config()

    def on_detector_add_clicked(self):
        current_detector = self.get_current_detector()
        detector_names = self.cfg.get_detector_names()
        new_detector_name_base = 'detector_'
        for i in range(1000000):
            new_detector_name = new_detector_name_base + str(i + 1)
            if new_detector_name not in detector_names:
                self.cfg.add_detector(new_detector_name, current_detector)
                self.update_detector_from_config()
                self.ui.cal_det_current.setCurrentText(new_detector_name)
                return

    def update_config_from_gui(self):
        """This function only updates the sender value"""
        sender = self.sender()
        name = sender.objectName()
        if name == 'cal_energy_wavelength':
            # Need to update the `cal_energy` entry instead
            sender = self.ui.cal_energy
            name = sender.objectName()

        value = self._get_gui_value(sender)
        current_detector = self.get_current_detector()
        self.cfg.set_val_from_widget_name(name, value, current_detector)

    def update_gui_from_config(self):
        previously_blocked = self.block_all_signals()

        try:
            gui_yaml_paths = self.cfg.get_gui_yaml_paths()
            for var, path in gui_yaml_paths:
                if 'detector_name' in path:
                    # We give these special treatment
                    continue

                gui_var = getattr(self.ui, var)
                config_val = self.cfg.get_iconfig_val(path)

                self._set_gui_value(gui_var, config_val)
        finally:
            self.unblock_all_signals(previously_blocked)

        # Update the wavelength also
        self.on_energy_changed()

        self.update_detector_from_config()

    def update_detector_from_config(self):
        previously_blocked = self.block_all_signals()

        try:
            detector_names = self.cfg.get_detector_names()
            if not detector_names:
                # Disable detector widgets if there is no valid detector
                if not self.detector_widgets_disabled:
                    self.enable_detector_widgets(enable=False)

                return
            elif self.detector_widgets_disabled:
                # Enable detector widgets if they were previously disabled
                self.enable_detector_widgets(enable=True)

            cur_detector = detector_names[0]
            if self.ui.cal_det_current.currentText() in detector_names:
                cur_detector = self.ui.cal_det_current.currentText()

            gui_yaml_paths = self.cfg.get_gui_yaml_paths(['detectors',
                                                          'detector_name'])

            for var, path in gui_yaml_paths:
                gui_var = getattr(self.ui, var)
                full_path = ['detectors', cur_detector] + path
                config_val = self.cfg.get_iconfig_val(full_path)
                self._set_gui_value(gui_var, config_val)

            combo_items = []
            for i in range(self.ui.cal_det_current.count()):
                combo_items.append(self.ui.cal_det_current.itemText(i))

            if combo_items != detector_names:
                self.ui.cal_det_current.clear()
                self.ui.cal_det_current.addItems(detector_names)
                self.ui.cal_det_current.setCurrentText(cur_detector)

        finally:
            self.unblock_all_signals(previously_blocked)

    def get_current_detector(self):
        if self.detector_widgets_disabled:
            return None

        return self.ui.cal_det_current.currentText()

    def get_all_widgets(self):
        gui_yaml_paths = self.cfg.get_gui_yaml_paths()
        widgets = [x[0] for x in gui_yaml_paths]
        widgets += self.cfg.get_detector_widgets()
        widgets += ['cal_energy_wavelength']
        widgets = list(set(widgets))
        widgets = [getattr(self.ui, x) for x in widgets]
        return widgets

    def block_all_signals(self):
        previously_blocked = []
        all_widgets = self.get_all_widgets()

        for widget in all_widgets:
            previously_blocked.append(widget.blockSignals(True))

        return previously_blocked

    def unblock_all_signals(self, previously_blocked):
        all_widgets = self.get_all_widgets()

        for block, widget in zip(previously_blocked, all_widgets):
            widget.blockSignals(block)

    def _set_gui_value(self, gui_object, value):
        """This is for calling various set methods for GUI variables

        For instance, QComboBox will call "setCurrentText", while
        QSpinBox will call "setValue".
        """
        if isinstance(gui_object, QComboBox):
            gui_object.setCurrentText(value)
        else:
            # If it is anything else, just assume setValue()
            gui_object.setValue(value)

    def _get_gui_value(self, gui_object):
        """This is for calling various get methods for GUI variables

        For instance, QComboBox will call "currentText", while
        QSpinBox will call "value".
        """
        if isinstance(gui_object, QComboBox):
            return gui_object.currentText()
        else:
            # If it is anything else, just assume value()
            return gui_object.value()
