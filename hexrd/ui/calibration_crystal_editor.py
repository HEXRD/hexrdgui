from PySide2.QtCore import QObject

from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader


class CalibrationCrystalEditor(QObject):

    def __init__(self, parent=None):
        super(CalibrationCrystalEditor, self).__init__(parent)

        loader = UiLoader()
        self.ui = loader.load_file('calibration_crystal_editor.ui', parent)

        self.set_defaults_if_missing()

        self.setup_connections()
        self.update_gui_from_config()

    def exec_(self):
        return self.ui.exec_()

    def all_widgets(self):
        widgets = [
            self.ui.grain_id,
            self.ui.inv_stretch_0,
            self.ui.inv_stretch_1,
            self.ui.inv_stretch_2,
            self.ui.inv_stretch_3,
            self.ui.inv_stretch_4,
            self.ui.inv_stretch_5,
            self.ui.orientation_0,
            self.ui.orientation_1,
            self.ui.orientation_2,
            self.ui.position_0,
            self.ui.position_1,
            self.ui.position_2
        ]

        return widgets

    def setup_connections(self):
        # Write to the config if accepted
        self.ui.accepted.connect(self.update_config_from_gui)

    def block_widgets(self):
        previous = []
        for widget in self.all_widgets():
            previous.append(widget.blockSignals(True))

        return previous

    def unblock_widgets(self, previous):
        for widget, block in zip(self.all_widgets(), previous):
            widget.blockSignals(block)

    def update_gui_from_config(self):
        block_list = self.block_widgets()
        try:
            for widget in self.all_widgets():
                name, ind = self.config_name_from_widget(widget)
                value = self.get_config_value(name, ind)
                widget.setValue(value)
        finally:
            self.unblock_widgets(block_list)

    def update_config_from_gui(self):
        for widget in self.all_widgets():
            name, ind = self.config_name_from_widget(widget)
            value = widget.value()
            self.set_config_value(name, value, ind)

    def config_name_from_widget(self, widget):
        # Take advantage of the similarity between the config keys
        # and the widget names.
        name = widget.objectName()
        ind = None

        if name[-1].isdigit():
            # This is stored in the config as a list
            # Split by the last occurrence of '_'
            split = name.split('_')
            name = '_'.join(split[:-1])
            ind = int(split[-1])

        return name, ind

    def set_config_value(self, key, value, ind=None):
        d = self.root_dict()
        if ind is None:
            d[key] = value
        else:
            d[key][ind] = value

    def get_config_value(self, key, ind=None):
        d = self.root_dict()
        if ind is None:
            return d[key]
        else:
            return d[key][ind]

    def root_dict(self):
        return HexrdConfig().config['calibration']['crystal']

    def set_defaults_if_missing(self):
        # TODO: we should do this for the entire config in HexrdConfig
        # to assist with backward compatibility.
        defaults = HexrdConfig().default_config['calibration']['crystal']
        d = HexrdConfig().config['calibration'].setdefault('crystal', defaults)
        for key in defaults.keys():
            d.setdefault(key, defaults[key])
