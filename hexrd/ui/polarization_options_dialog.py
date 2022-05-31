from hexrd.ui.hexrd_config import HexrdConfig
from hexrd.ui.ui_loader import UiLoader
from hexrd.ui.utils import block_signals


class PolarizationOptionsDialog:

    def __init__(self, parent=None):
        loader = UiLoader()
        self.ui = loader.load_file('polarization_options_dialog.ui',
                                   parent)

        self.update_gui()
        self.setup_connections()

    def setup_connections(self):
        self.ui.accepted.connect(self.accept)
        self.ui.horizontal.valueChanged.connect(self.horizontal_modified)
        self.ui.vertical.valueChanged.connect(self.vertical_modified)

    def exec_(self):
        return self.ui.exec_()

    def accept(self):
        # When the dialog is accepted, save the settings in HexrdConfig.
        options = HexrdConfig().config['image']['polarization']
        options['unpolarized'] = self.ui.unpolarized.isChecked()
        options['f_hor'] = self.ui.horizontal.value()
        options['f_vert'] = self.ui.vertical.value()

    def update_gui(self):
        options = HexrdConfig().config['image']['polarization']
        self.ui.unpolarized.setChecked(options['unpolarized'])
        self.ui.horizontal.setValue(options['f_hor'])
        self.ui.vertical.setValue(options['f_vert'])

    def horizontal_modified(self, v):
        # Set the vertical to be 1 - horizontal
        with block_signals(self.ui.vertical):
            self.ui.vertical.setValue(1 - v)

    def vertical_modified(self, v):
        # Set the horizontal to be 1 - vertical
        with block_signals(self.ui.horizontal):
            self.ui.horizontal.setValue(1 - v)
